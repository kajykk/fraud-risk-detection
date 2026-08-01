"""MLScoringEngine - 三模态并行评分引擎（ADR-011 核心）。

严格遵循 D03 V1.1 §4.3 ADR-011：
- 三模态并行执行（asyncio.gather）
- 单模态超时 30ms（asyncio.wait_for timeout=0.030）
- 超时熔断：返回该模态 Redis 历史分数均值（最近 100 次），无历史 → 0.5
- 三模态均超时 → 触发 L3 模态级 Kill Switch（ADR-013）
- 融合阶段感知 fallback_flags，对熔断模态降权至 0.05

输出 ModalityScores（D04 scores.modality_scores JSONB 字段对齐）：
    {
        "structured": {"score": 0.32, "latency_ms": 18.5, "fallback": false},
        "text":       {"score": 0.71, "latency_ms": 28.2, "fallback": false},
        "behavior":   {"score": 0.45, "latency_ms": 0.0,  "fallback": true,
                       "reason": "timeout"},
        "fused_score": 0.42,
        "risk_band": "MEDIUM",
        "fallback_flags": {"behavior": "timeout"}
    }
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .config import settings
from .fusion import FusionEngine
from .modalities.behavior import BehaviorModality
from .modalities.structured import ModalityScore, StructuredModality
from .modalities.text import TextModality

logger = structlog.get_logger(__name__)


@dataclass
class ModalityScores:
    """三模态评分聚合结果（对齐 D04 scores.modality_scores 字段）。"""

    structured: ModalityScore
    text: ModalityScore
    behavior: ModalityScore
    fused_score: float
    risk_band: str
    latency_ms: float
    fallback_flags: dict[str, str] = field(default_factory=dict)
    all_fallback: bool = False  # 三模态均熔断 → 触发 L3 Kill Switch

    def to_dict(self) -> dict[str, Any]:
        return {
            "structured": {
                "score": self.structured.score,
                "latency_ms": self.structured.latency_ms,
                "fallback": self.structured.fallback,
                "label": self.structured.label,
            },
            "text": {
                "score": self.text.score,
                "latency_ms": self.text.latency_ms,
                "fallback": self.text.fallback,
                "label": self.text.label,
            },
            "behavior": {
                "score": self.behavior.score,
                "latency_ms": self.behavior.latency_ms,
                "fallback": self.behavior.fallback,
                "label": self.behavior.label,
            },
            "fused_score": self.fused_score,
            "risk_band": self.risk_band,
            "latency_ms": self.latency_ms,
            "fallback_flags": self.fallback_flags,
            "all_fallback": self.all_fallback,
        }


class MLScoringEngine:
    """三模态并行评分引擎（ADR-011）。

    生命周期：
        engine = MLScoringEngine()
        await engine.load(redis_client)
        scores = await engine.predict(features, text, series, tenant_id)

    严格约束（D03 §4.3）：
        - 三模态 asyncio.gather 并行
        - 单模态 asyncio.wait_for timeout=0.030
        - 熔断返回历史分数或默认 0.5
        - 三模态均超时 → all_fallback=True（外层触发 L3 Kill Switch）
    """

    def __init__(self) -> None:
        self.structured = StructuredModality()
        self.text = TextModality()
        self.behavior = BehaviorModality()
        self.fusion = FusionEngine()
        self._redis: Any | None = None
        self._failure_counters: dict[str, int] = {
            "structured": 0,
            "text": 0,
            "behavior": 0,
        }

    async def load(self, redis_client: Any | None = None) -> None:
        """加载三模态模型工件 + Redis 客户端。"""
        self._redis = redis_client
        await asyncio.gather(
            self.structured.load_model(redis_client),
            self.text.load_model(redis_client),
            self.behavior.load_model(redis_client),
            return_exceptions=True,
        )

    async def predict(
        self,
        structured_features: dict[str, Any],
        text_content: str,
        behavior_series: list[list[float]],
        tenant_id: str,
    ) -> ModalityScores:
        """三模态并行评分（ADR-011 严格实现）。

        Args:
            structured_features: 结构化特征 dict
            text_content: 文本内容（备注/对话）
            behavior_series: 行为时序序列
            tenant_id: 租户 ID

        Returns:
            ModalityScores
        """
        start = time.perf_counter()

        # ADR-011 三模态并行：asyncio.gather + asyncio.wait_for timeout=0.030
        results = await asyncio.gather(
            self._predict_with_timeout(
                self.structured.predict(structured_features, tenant_id),
                settings.structured,
                "structured",
                tenant_id,
            ),
            self._predict_with_timeout(
                self.text.predict(text_content, tenant_id),
                settings.text,
                "text",
                tenant_id,
            ),
            self._predict_with_timeout(
                self.behavior.predict(behavior_series, tenant_id),
                settings.behavior,
                "behavior",
                tenant_id,
            ),
            return_exceptions=False,
        )
        structured_score, text_score, behavior_score = results

        # 记录历史分数（供熔断兜底）
        await asyncio.gather(
            self.structured.record_score(tenant_id, structured_score.score),
            self.text.record_score(tenant_id, text_score.score),
            self.behavior.record_score(tenant_id, behavior_score.score),
            return_exceptions=True,
        )

        # 构造 fallback_flags
        fallback_flags: dict[str, str] = {}
        for name, score in (
            ("structured", structured_score),
            ("text", text_score),
            ("behavior", behavior_score),
        ):
            if score.fallback:
                reason = (score.label or "fallback").replace("fallback:", "")
                fallback_flags[name] = reason
                self._failure_counters[name] += 1
            else:
                self._failure_counters[name] = 0

        all_fallback = (
            structured_score.fallback
            and text_score.fallback
            and behavior_score.fallback
        )

        # 三模态融合（融合阶段感知 fallback_flags 降权）
        scores_dict = {
            "structured": structured_score,
            "text": text_score,
            "behavior": behavior_score,
        }
        fused_score = self.fusion.fuse(scores_dict)
        risk_band = self.fusion.to_band(fused_score)

        latency_ms = (time.perf_counter() - start) * 1000.0

        if all_fallback:
            logger.error(
                "ml.engine.all_modality_fallback",
                tenant_id=tenant_id,
                fallback_flags=fallback_flags,
                # ADR-013 L3 模态级 Kill Switch 由外层规则触发
            )
        else:
            logger.info(
                "ml.engine.predict.done",
                tenant_id=tenant_id,
                fused_score=fused_score,
                risk_band=risk_band,
                latency_ms=latency_ms,
                fallback_flags=fallback_flags,
            )

        return ModalityScores(
            structured=structured_score,
            text=text_score,
            behavior=behavior_score,
            fused_score=fused_score,
            risk_band=risk_band,
            latency_ms=latency_ms,
            fallback_flags=fallback_flags,
            all_fallback=all_fallback,
        )

    async def _predict_with_timeout(
        self,
        coro: Any,
        modality_cfg: Any,
        modality_name: str,
        tenant_id: str,
    ) -> ModalityScore:
        """单模态超时熔断（asyncio.wait_for timeout=0.030）。

        超时 → 走模态 fallback（Redis 历史分数或默认 0.5）。
        """
        timeout_seconds = modality_cfg.timeout_ms / 1000.0
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "ml.modality.timeout",
                modality=modality_name,
                tenant_id=tenant_id,
                timeout_ms=modality_cfg.timeout_ms,
            )
            return await self._fallback_modality(modality_name, tenant_id, "timeout")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ml.modality.exception",
                modality=modality_name,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return await self._fallback_modality(modality_name, tenant_id, "exception")

    async def _fallback_modality(
        self, modality_name: str, tenant_id: str, reason: str
    ) -> ModalityScore:
        """统一熔断兜底入口（ADR-011）。"""
        modality = {
            "structured": self.structured,
            "text": self.text,
            "behavior": self.behavior,
        }.get(modality_name)
        if modality is None:
            return ModalityScore(
                score=0.5,
                modality=modality_name,
                latency_ms=0.0,
                fallback=True,
                label=f"fallback:{reason}",
            )
        return await modality.fallback(tenant_id, reason=reason)

    def should_trigger_l3_kill_switch(self, modality_name: str) -> bool:
        """ADR-013 L3 模态级 Kill Switch 升级判断。

        5min 内模态连续熔断 > 50 次 → 升级 L3 Kill Switch。
        """
        return (
            self._failure_counters.get(modality_name, 0)
            >= settings.modality_failure_threshold
        )


__all__ = ["MLScoringEngine", "ModalityScores"]
