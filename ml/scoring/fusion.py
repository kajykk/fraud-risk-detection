"""三模态分数融合（ADR-011 §4.3）。

D03 §4.3 融合策略：
- 加权融合 weights = {struct: 0.6, text: 0.2, behavior: 0.2}
- 熔断模态降权至 0.05，其余模态权重按比例放大
- 可选 Stacking 元学习器（预留接口）
"""

from __future__ import annotations

from typing import Dict, Optional

import structlog

from .config import settings
from .modalities.structured import ModalityScore

logger = structlog.get_logger(__name__)


class FusionEngine:
    """三模态融合引擎（加权 + Stacking 预留）。"""

    def __init__(self) -> None:
        self._weights: Dict[str, float] = dict(settings.fusion.weights)
        self._fallback_weight: float = settings.fusion.fallback_weight
        self._meta_model: Optional[object] = None  # Stacking 元学习器

    def set_meta_model(self, model: object) -> None:
        """注入 Stacking 元学习器（可选）。"""
        self._meta_model = model

    def fuse(self, scores: Dict[str, ModalityScore]) -> float:
        """三模态加权融合。

        Args:
            scores: {modality_name: ModalityScore}

        Returns:
            fused_score: 0.0 - 1.0
        """
        if not scores:
            return 0.5

        # Step 1: 计算每个模态的有效权重（熔断模态降权至 fallback_weight）
        effective_weights: Dict[str, float] = {}
        for name, score in scores.items():
            base = self._weights.get(name, 0.0)
            if score.fallback:
                effective_weights[name] = self._fallback_weight
            else:
                effective_weights[name] = base

        # Step 2: 归一化（其余模态按比例放大）
        total = sum(effective_weights.values())
        if total <= 0:
            return 0.5
        normalized = {k: v / total for k, v in effective_weights.items()}

        # Step 3: 加权求和
        fused = sum(normalized[name] * scores[name].score for name in scores)

        # Step 4: 若启用 Stacking 元学习器，覆盖加权结果
        if self._meta_model is not None:
            try:
                fused = self._apply_meta_model(scores, fused)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fusion.meta_model.failed", error=str(exc))

        return float(min(max(fused, 0.0), 1.0))

    def _apply_meta_model(
        self, scores: Dict[str, ModalityScore], weighted_score: float
    ) -> float:
        """Stacking 元学习器融合（占位实现）。"""
        # TODO: 加载训练好的 fusion.pt，输入 [struct, text, behavior] → 输出最终分数
        # 当前作为骨架占位，直接返回加权分数
        logger.debug("fusion.meta_model.placeholder", weighted=weighted_score)
        return weighted_score

    def to_band(self, score: float) -> str:
        """风险等级阈值（baseline §3.5）。"""
        thresholds = settings.fusion.band_thresholds
        if score < thresholds["LOW"]:
            return "LOW"
        if score < thresholds["MEDIUM"]:
            return "MEDIUM"
        if score < thresholds["HIGH"]:
            return "HIGH"
        return "CRITICAL"


__all__ = ["FusionEngine"]
