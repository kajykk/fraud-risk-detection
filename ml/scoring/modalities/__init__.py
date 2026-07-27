"""三模态推理子模块（ADR-011）。

模态清单：
- structured: XGBoost 结构化模态（金额/时间/商户/设备/历史特征）
- text: BERT 金融微调文本模态（备注/对话）
- behavior: 1D-CNN 行为时序模态（点击流/输入节奏）

每个模态实现统一接口：
    load_model() -> None
    predict(features) -> ModalityScore
    fallback(tenant_id) -> ModalityScore  # 熔断兜底
"""

from .structured import StructuredModality
from .text import TextModality
from .behavior import BehaviorModality

__all__ = ["StructuredModality", "TextModality", "BehaviorModality"]
