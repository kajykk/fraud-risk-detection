"""FRD ML 模块（D03 §1.3 / §4.3）。

子模块：
- scoring: 三模态并行评分推理服务（ADR-011）
- training: 训练管道（XGBoost / BERT / 1D-CNN / Fusion）
- drift: PSI/KL 漂移检测 + 告警
- tests: 单元测试
"""

__all__ = ["scoring", "training", "drift"]
