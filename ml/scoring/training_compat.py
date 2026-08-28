"""serving 与 training 的特征契约共享层（轻量、无重依赖）。

ml/scoring 不直接依赖 ml/training（避免引入 pandas/sklearn 等训练依赖），
仅复用特征名常量，保证"训练 ↔ 服务"两侧 schema 单一事实源。
"""

from __future__ import annotations

# 延迟导入 training.feature_store（仅 stdlib + structlog 依赖，安全）
try:  # pragma: no cover
    from ..training.feature_store import DEFAULT_STRUCTURED_FEATURES

    STRUCTURED_FEATURE_NAMES: list[str] = list(DEFAULT_STRUCTURED_FEATURES.feature_names)
except Exception:  # noqa: BLE001
    STRUCTURED_FEATURE_NAMES = []

__all__ = ["STRUCTURED_FEATURE_NAMES"]
