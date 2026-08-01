"""训练 XGBoost 结构化模态。

对应 D03 §4.3：
    structured → XGBoost → score_struct

输出：model_versions 表 status=REGISTERED，model_type=STRUCTURED。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class StructuredTrainResult:
    model_path: str
    n_samples: int
    n_features: int
    metrics: dict[str, float]


def train(
    features: list[list[float]],
    labels: list[int],
    save_path: str,
    params: dict[str, Any] | None = None,
) -> StructuredTrainResult:
    """训练 XGBoost 二分类模型。

    Args:
        features: 训练特征矩阵（List[List[float]]）
        labels: 标签（0/1）
        save_path: 模型保存路径（.json 或 .xgb）
        params: XGBoost 超参数
    """
    import numpy as np  # type: ignore
    import xgboost as xgb  # type: ignore

    X = np.asarray(features, dtype=np.float32)
    y = np.asarray(labels, dtype=np.int32)
    n_samples, n_features = X.shape

    default_params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 1,
        "gamma": 0.0,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "random_state": 42,
        "n_jobs": -1,
    }
    if params:
        default_params.update(params)

    model = xgb.XGBClassifier(**default_params)
    model.fit(X, y)
    probas = model.predict_proba(X)[:, 1]

    from .evaluate import compute_auc, compute_f1, compute_recall_at_fpr

    metrics = {
        "auc": compute_auc(y, probas),
        "f1": compute_f1(y, (probas >= 0.5).astype(int)),
        "recall_at_1pct_fpr": compute_recall_at_fpr(y, probas, fpr_threshold=0.01),
    }
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_model(save_path)
    logger.info(
        "structured.train.done",
        save_path=save_path,
        n_samples=n_samples,
        n_features=n_features,
        metrics=metrics,
    )
    return StructuredTrainResult(
        model_path=save_path,
        n_samples=n_samples,
        n_features=n_features,
        metrics=metrics,
    )


__all__ = ["train", "StructuredTrainResult"]
