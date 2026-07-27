"""结构化模态推理（XGBoost）。

对应 D03 §4.3：
    structured → XGBoost → score_struct (P99 20ms)

输入：交易结构化特征（金额/时间/商户/设备/历史）
输出：ModalityScore(score, label, latency_ms)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import structlog

from ..config import settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ModalityScore:
    """单模态评分结果。"""

    score: float  # 0.0 - 1.0
    modality: str
    latency_ms: float
    fallback: bool = False
    label: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class StructuredModality:
    """结构化模态（XGBoost predict_proba）。

    使用 XGBoost 2.1 加载 .xgb / .json 工件，输出欺诈概率。
    若模型未加载或推理失败 → 走 fallback。
    """

    name = "structured"

    def __init__(self) -> None:
        self._model: Optional[Any] = None  # xgboost.Booster
        self._feature_names: Optional[list[str]] = None
        self._redis: Optional[Any] = None

    async def load_model(self, redis_client: Optional[Any] = None) -> None:
        """加载 XGBoost 模型工件。

        Args:
            redis_client: 用于读取历史分数滑动窗口（熔断兜底）
        """
        self._redis = redis_client
        try:
            import xgboost as xgb  # type: ignore

            path = settings.models.structured_path
            booster = xgb.Booster()
            booster.load_model(path)
            self._model = booster
            self._feature_names = getattr(booster, "feature_names", None)
            logger.info("structured.model.loaded", path=path)
        except Exception as exc:  # noqa: BLE001
            logger.error("structured.model.load_failed", error=str(exc))
            self._model = None

    async def predict(self, features: Dict[str, Any], tenant_id: str) -> ModalityScore:
        """同步推理包装为协程，避免阻塞事件循环。

        Args:
            features: 结构化特征 dict（金额/时间/商户/设备/历史）
            tenant_id: 租户 ID（用于历史分数查询）
        """
        if self._model is None:
            return await self.fallback(tenant_id, reason="model_not_loaded")

        start = time.perf_counter()
        try:
            import numpy as np  # type: ignore
            import xgboost as xgb  # type: ignore

            row = self._format_features(features)
            dmat = xgb.DMatrix(np.asarray([row], dtype=np.float32))
            probas = self._model.predict(dmat)
            score = float(probas[0])
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ModalityScore(
                score=score,
                modality=self.name,
                latency_ms=latency_ms,
                label="fraud_proba",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("structured.predict.failed", error=str(exc))
            return await self.fallback(tenant_id, reason="predict_exception")

    def _format_features(self, features: Dict[str, Any]) -> list[float]:
        """按特征名顺序构造数值向量（缺失补 0）。"""
        if self._feature_names:
            return [float(features.get(name, 0.0)) for name in self._feature_names]
        return [float(v) for v in features.values()]

    async def fallback(self, tenant_id: str, reason: str = "unknown") -> ModalityScore:
        """熔断兜底：返回该模态 Redis 历史分数均值，无历史 → 0.5（ADR-011）。"""
        score = await self._lookup_recent_score(tenant_id)
        logger.warning(
            "structured.fallback.triggered",
            tenant_id=tenant_id,
            reason=reason,
            score=score,
        )
        return ModalityScore(
            score=score,
            modality=self.name,
            latency_ms=0.0,
            fallback=True,
            label=f"fallback:{reason}",
        )

    async def _lookup_recent_score(self, tenant_id: str) -> float:
        """读取 Redis 滑动窗口历史均值（key: ml:{tenant_id}:structured:recent_scores）。"""
        if self._redis is None:
            return settings.structured.default_score
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            values = await self._redis.lrange(key, 0, settings.structured.recent_scores_window - 1)
            if not values:
                return settings.structured.default_score
            nums = [float(v) for v in values if v is not None]
            if not nums:
                return settings.structured.default_score
            return sum(nums) / len(nums)
        except Exception as exc:  # noqa: BLE001
            logger.warning("structured.history.read_failed", error=str(exc))
            return settings.structured.default_score

    async def record_score(self, tenant_id: str, score: float) -> None:
        """将本次分数写入 Redis 滑动窗口（供后续熔断兜底使用）。"""
        if self._redis is None:
            return
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            await self._redis.rpush(key, float(score))
            await self._redis.ltrim(
                key, -settings.structured.recent_scores_window, -1
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("structured.history.write_failed", error=str(exc))


__all__ = ["ModalityScore", "StructuredModality"]
