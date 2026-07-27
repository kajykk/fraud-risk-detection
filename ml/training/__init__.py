"""ML 训练管道子模块。

管道主流程（D03 §4.3 / D04 §3.5）：
    load_data → feature_eng → train → evaluate → register

模块：
- pipeline: 训练管道主入口
- data_loader: 数据加载（PostgreSQL + 特征工程）
- feature_store: 特征存储
- train_structured: 训练 XGBoost
- train_text: 微调 BERT
- train_behavior: 训练 1D-CNN
- train_fusion: 训练融合层
- evaluate: 评估（AUC/F1/Recall@1%FPR/PSI）
- register: 注册到 model_versions 表（status=REGISTERED）
"""

__all__ = [
    "pipeline",
    "data_loader",
    "feature_store",
    "train_structured",
    "train_text",
    "train_behavior",
    "train_fusion",
    "evaluate",
    "register",
]
