"""MLScoringEngine：三模态并行评分 + 熔断（D03 §4.3 / ADR-011）。

评分路径由 ML_ENGINE_MODE 配置（app.config.MLRemoteConfig）：
- auto（默认）：先调用独立推理服务 ml-serving(:8501) 的 POST /v1/score
  （结构化 XGBoost / 文本 BERT / 行为 1D-CNN 三模态并行 + 服务侧融合），
  连接 2s / 读 5s 超时；网络、超时或非 2xx 响应 → 记录 warning 并回退本地启发式。
- remote：仅远程（失败同样回退启发式，保证评分主路径可用性）。
- heuristic：仅本地金额启发式，不发网络请求。

远程调用带轻量熔断器（参照 ml/scoring 连续失败计数 + Kill Switch 思路）：
连续失败 ≥ 阈值后打开，冷却期内的请求直接走启发式，期满半开放行一次探测。

响应契约不变：
- fused_score ← 远程 risk_score；structured/text/behavior ← modality_scores.*
  （fallback 字段映射为本地 fallback_used，fallback_flags 统一为 dict[str, bool]）。
- 若远程响应携带可选 shap 贡献则透传至 ModalityScores.shap_contributions；
  否则为 None，下游沿用 app/services/shap_provider.py 的规则式 stub。

本地启发式路径（原实现保留为回退）：
- structured/text/behavior 各模态 asyncio.gather + 单模态超时熔断
  （Redis 历史均值 → 默认 0.5），融合权重 {struct: 0.6, text: 0.2, behavior: 0.2}，
  熔断模态降权至 0.05。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModalityScore:
    """单模态评分。"""

    modality: str
    score: float
    fallback_used: bool = False
    latency_ms: int = 0


@dataclass
class ModalityScores:
    """三模态评分汇总。"""

    structured: ModalityScore | None = None
    text: ModalityScore | None = None
    behavior: ModalityScore | None = None
    fused_score: float = 0.0
    fallback_flags: dict[str, bool] = field(default_factory=dict)
    total_latency_ms: int = 0
    # 远程 SHAP 贡献透传（/v1/score 可选字段）；None = 下游沿用规则式 stub
    shap_contributions: dict[str, Any] | None = None


@dataclass
class RemoteCircuitBreaker:
    """远程推理轻量熔断器（closed → open → 半开恢复）。"""

    failure_threshold: int = 5
    recovery_seconds: float = 30.0
    consecutive_failures: int = 0
    opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            # 冷却期满：半开，放行下一次请求作探测
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


def _build_http_client() -> httpx.AsyncClient:
    """构建 ml-serving HTTP 客户端（连接/读超时来自配置）。"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.ml_read_timeout_seconds,
            connect=settings.ml_connect_timeout_seconds,
        ),
    )


class MLScoringEngine:
    """三模态并行 ML 评分引擎（remote/auto/heuristic 三档模式）。"""

    def __init__(self) -> None:
        self.timeout_seconds = settings.scoring_modality_timeout_ms / 1000.0
        self.weights = {
            "structured": settings.fusion_weight_structured,
            "text": settings.fusion_weight_text,
            "behavior": settings.fusion_weight_behavior,
        }
        self.fallback_weight = settings.fallback_weight_degraded
        self.default_score = settings.fallback_default_score
        self._breaker = RemoteCircuitBreaker(
            failure_threshold=settings.ml_breaker_failure_threshold,
            recovery_seconds=settings.ml_breaker_recovery_seconds,
        )

    async def predict_parallel(
        self,
        features: dict[str, Any],
        text: str | None,
        behavior: list[float] | None,
        tenant_id: str,
    ) -> ModalityScores:
        """三模态评分入口：remote/auto 先走 ml-serving，失败回退本地启发式。"""
        mode = settings.ml_engine_mode
        if mode != "heuristic":
            if self._breaker.is_open:
                logger.warning(
                    "ml_remote_circuit_open_skip",
                    tenant_id=tenant_id,
                    consecutive_failures=self._breaker.consecutive_failures,
                )
            else:
                try:
                    scores = await self._predict_remote(features, text, behavior, tenant_id)
                    self._breaker.record_success()
                    return scores
                except Exception as exc:  # noqa: BLE001
                    self._breaker.record_failure()
                    logger.warning(
                        "ml_remote_failed_fallback_heuristic",
                        tenant_id=tenant_id,
                        mode=mode,
                        error=str(exc),
                    )
        return await self._predict_local(features, text, behavior, tenant_id)

    # ------------------------------------------------------------------
    # 远程路径（ml-serving :8501）
    # ------------------------------------------------------------------

    async def _predict_remote(
        self,
        features: dict[str, Any],
        text: str | None,
        behavior: list[float] | None,
        tenant_id: str,
    ) -> ModalityScores:
        """POST {ml_service_url}/v1/score（X-Api-Key 鉴权），映射响应契约。"""
        payload = {
            "tenant_id": tenant_id,
            "transaction_id": str(features.get("external_tx_id") or uuid.uuid4()),
            "structured_features": features,
            "text_content": text or "",
            "behavior_series": self._normalize_series(behavior),
        }
        headers: dict[str, str] = {}
        if settings.ml_api_key:
            headers["X-Api-Key"] = settings.ml_api_key

        async with _build_http_client() as client:
            response = await client.post(
                f"{settings.ml_service_url}/v1/score",
                json=payload,
                headers=headers,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("ml-serving response is not a JSON object")
        return self._map_remote_response(data)

    @staticmethod
    def _normalize_series(behavior: list[float] | None) -> list[list[float]]:
        """backend 扁平序列 [f1, f2..] → 服务端 list[list[float]]；二维则透传。"""
        series = behavior or []
        if not series:
            return []
        if isinstance(series[0], (int | float)):
            return [[float(v)] for v in series]
        return [[float(v) for v in row] for row in series]

    @staticmethod
    def _map_remote_response(data: dict[str, Any]) -> ModalityScores:
        """ScoreResponse → 本地 ModalityScores（类型契约不变）。"""
        modality_scores = data.get("modality_scores") or {}
        if not isinstance(modality_scores, dict):
            raise ValueError("malformed modality_scores in remote response")
        raw_score = data.get("risk_score", modality_scores.get("fused_score"))
        if raw_score is None:
            raise ValueError("missing risk_score in remote response")

        def _modality(name: str) -> ModalityScore | None:
            entry = modality_scores.get(name)
            if not isinstance(entry, dict) or "score" not in entry:
                return None
            try:
                score = float(entry["score"])
                latency = float(entry.get("latency_ms") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"malformed modality entry: {name}") from exc
            return ModalityScore(
                modality=name,
                score=score,
                fallback_used=bool(entry.get("fallback", False)),
                latency_ms=int(latency),
            )

        shap_raw = data.get("shap") or modality_scores.get("shap")
        return ModalityScores(
            structured=_modality("structured"),
            text=_modality("text"),
            behavior=_modality("behavior"),
            fused_score=float(raw_score),
            fallback_flags={
                name: bool((modality_scores.get(name) or {}).get("fallback", False))
                for name in ("structured", "text", "behavior")
            },
            total_latency_ms=int(float(data.get("latency_ms") or 0)),
            shap_contributions=shap_raw if isinstance(shap_raw, dict) else None,
        )

    # ------------------------------------------------------------------
    # 本地启发式路径（原实现，作为远程不可用时的回退）
    # ------------------------------------------------------------------

    async def _predict_local(
        self,
        features: dict[str, Any],
        text: str | None,
        behavior: list[float] | None,
        tenant_id: str,
    ) -> ModalityScores:
        """三模态并行执行（asyncio.gather + 单模态超时熔断）。

        D03 §4.1 预算：三模态并行 max(20, 30, 25) = 30ms。
        """
        start = time.perf_counter()
        results = await asyncio.gather(
            self._predict_with_fallback(
                "structured", self._predict_structured, features, tenant_id
            ),
            self._predict_with_fallback("text", self._predict_text, text, tenant_id),
            self._predict_with_fallback("behavior", self._predict_behavior, behavior, tenant_id),
            return_exceptions=True,
        )
        structured, text_result, behavior_result = results

        modality_scores = ModalityScores(
            structured=self._to_modality_score("structured", structured),
            text=self._to_modality_score("text", text_result),
            behavior=self._to_modality_score("behavior", behavior_result),
            total_latency_ms=int((time.perf_counter() - start) * 1000),
        )

        # 检查三模态是否全部熔断
        all_fallback = all(
            getattr(modality_scores, m) is not None and getattr(modality_scores, m).fallback_used
            for m in ("structured", "text", "behavior")
        )
        if all_fallback:
            logger.warning("all_modalities_fallback", tenant_id=tenant_id)
            # 触发 L3 模态级 Kill Switch
            # TODO: activate kill switch for modality

        modality_scores.fused_score = self._fuse(modality_scores)
        return modality_scores

    def _to_modality_score(self, modality: str, result: Any) -> ModalityScore | None:
        """Convert an asyncio.gather result into a ModalityScore (or None on exception)."""
        if isinstance(result, ModalityScore):
            return result
        if isinstance(result, Exception):
            logger.error(
                "modality_gather_exception",
                modality=modality,
                error=str(result),
            )
            return None
        return None

    async def _predict_with_fallback(
        self,
        modality: str,
        predict_fn: Any,
        input_data: Any,
        tenant_id: str,
    ) -> ModalityScore:
        """单模态预测 + 超时熔断回退。"""
        start = time.perf_counter()
        try:
            score = await asyncio.wait_for(
                predict_fn(input_data, tenant_id), timeout=self.timeout_seconds
            )
            return ModalityScore(
                modality=modality,
                score=float(score),
                fallback_used=False,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except (TimeoutError, Exception) as exc:
            logger.warning(
                "modality_fallback_triggered",
                modality=modality,
                tenant_id=tenant_id,
                error=str(exc),
            )
            fallback_score = await self._get_fallback_score(modality, tenant_id)
            return ModalityScore(
                modality=modality,
                score=fallback_score,
                fallback_used=True,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

    async def _predict_structured(self, features: dict[str, Any], tenant_id: str) -> float:
        """structured 回退启发式：金额阈值（真实推理在 ml-serving）。"""
        amount = features.get("amount", 0)
        if amount > 500000:  # 5000 元以上
            return 0.65
        return 0.15

    async def _predict_text(self, text: str | None, tenant_id: str) -> float:
        """text 回退启发式：无文本返回中性。"""
        if not text:
            return 0.3
        return 0.4

    async def _predict_behavior(self, behavior: list[float] | None, tenant_id: str) -> float:
        """behavior 回退启发式：无序列返回中性。"""
        if not behavior:
            return 0.3
        return 0.35

    async def _get_fallback_score(self, modality: str, tenant_id: str) -> float:
        """熔断回退：Redis 历史分数均值，无历史 → 默认 0.5。"""
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            key = f"ml:{tenant_id}:{modality}:recent_scores"
            # 取最近 100 次滑动窗口均值
            scores = await redis.lrange(key, 0, 99)
            if scores:
                nums = [float(s) for s in scores]
                return sum(nums) / len(nums)
        except Exception:
            pass
        return self.default_score

    def _fuse(self, scores: ModalityScores) -> float:
        """三模态融合（加权 + 熔断降权）。

        weights = {struct: 0.6, text: 0.2, behavior: 0.2}
        熔断模态降权至 0.05，其余模态按比例放大。
        """
        weight_map = dict(self.weights)
        for modality in ("structured", "text", "behavior"):
            ms: ModalityScore | None = getattr(scores, modality)
            if ms is not None and ms.fallback_used:
                weight_map[modality] = self.fallback_weight
                scores.fallback_flags[modality] = True
            else:
                scores.fallback_flags[modality] = False

        total_weight = sum(weight_map.values())
        if total_weight == 0:
            return self.default_score

        fused = 0.0
        for modality in ("structured", "text", "behavior"):
            ms: ModalityScore | None = getattr(scores, modality)
            if ms is not None:
                fused += ms.score * (weight_map[modality] / total_weight)
        return min(1.0, max(0.0, fused))


# 单例
ml_engine = MLScoringEngine()


__all__ = [
    "MLScoringEngine",
    "ModalityScore",
    "ModalityScores",
    "RemoteCircuitBreaker",
    "ml_engine",
]
