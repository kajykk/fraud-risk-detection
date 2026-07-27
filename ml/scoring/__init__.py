"""FRD ML 评分推理服务（三模态并行 + 熔断，ADR-011）。

子模块：
- main: FastAPI 推理服务入口（端口 8501）
- engine: MLScoringEngine（三模态并行 + 30ms 熔断 + 加权融合）
- modalities: 结构化 / 文本 / 行为时序三模态推理
- fusion: 三模态分数融合
- shap_explainer: SHAP Top5 解释（异步 + 24h 缓存）
"""

__all__ = ["engine", "modalities", "fusion", "shap_explainer", "main", "config"]
