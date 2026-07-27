"""MLScoringEngine：三模态并行评分 + 熔断（D03 §4.3 / ADR-011）。

三模态并行执行（asyncio.gather）：
- structured → LightGBM（P99 20ms）
- text → BERT 金融微调（P99 30ms）
- behavior → 1D-CNN + IsolationForest（P99 25ms）

单模态超时 30ms 即熔断：
1. 优先返回 Redis 历史分数均值（key: ml:{tenant}:{modality}:recent_scores）
2. 无历史 → 默认 0.5
3. 三模态均超时 → 触发 L3 模态级 Kill Switch → 降级规则引擎单轨

融合策略：
- 加权 weights = {struct: 0.6, text: 0.2, behavior: 0.2}
- 熔断模态降权至 0.05，其余模态按比例放大
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.services.kill_switch import KillSwitchScope, kill_switch

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


class MLScoringEngine:
    """三模态并行 ML 评分引擎。"""

    def __init__(self) -> None:
        self.timeout_seconds = settings.scoring_modality_timeout_ms / 1000.0
        self.weights = {
            "structured": settings.fusion_weight_structured,
            "text": settings.fusion_weight_text,
            "behavior": settings.fusion_weight_behavior,
        }
        self.fallback_weight = settings.fallback_weight_degraded
        self.default_score = settings.fallback_default_score

    async def predict_parallel(
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
            self._predict_with_fallback("structured", self._predict_structured, features, tenant_id),
            self._predict_with_fallback("text", self._predict_text, text, tenant_id),
            self._predict_with_fallback("behavior", self._predict_behavior, behavior, tenant_id),
            return_exceptions=True,
        )
        structured, text_result, behavior = results

        modality_scores = ModalityScores(
            structured=self._to_modality_score("structured", structured),
            text=self._to_modality_score("text", text_result),
            behavior=self._to_modality_score("behavior", behavior),
            total_latency_ms=int((time.perf_counter() - start) * 1000),
        )

        # 检查三模态是否全部熔断
        all_fallback = all(
            getattr(modality_scores, m) is not None
            and getattr(modality_scores, m).fallback_used
            for m in ("structured", "text", "behavior")
        )
        if all_fallback:
            logger.warning("all_modalities_fallback", tenant_id=tenant_id)
            # 触发 L3 模态级 Kill Switch
            # TODO: activate kill switch for modality

        modality_scores.fused_score = self._fuse(modality_scores)
        return modality_scores

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
            score = await asyncio.wait_for(predict_fn(input_data, tenant_id), timeout=self.timeout_seconds)
            return ModalityScore(
                modality=modality,
                score=float(score),
                fallback_used=False,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except (asyncio.TimeoutError, Exception) as exc:
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
        """structured → LightGBM。TODO: 接入真实模型。"""
        # 骨架：返回基于金额的启发式分数
        amount = features.get("amount", 0)
        if amount > 500000:  # 5000 元以上
            return 0.65
        return 0.15

    async def _predict_text(self, text: str | None, tenant_id: str) -> float:
        """text → BERT 金融微调。TODO: 接入真实模型。"""
        # 骨架：无文本返回中性
        if not text:
            return 0.3
        return 0.4

    async def _predict_behavior(self, behavior: list[float] | None, tenant_id: str) -> float:
        """behavior → 1D-CNN + IsolationForest。TODO: 接入真实模型。"""
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


__all__ = ["MLScoringEngine", "ModalityScore", "ModalityScores", "ml_engine"]
