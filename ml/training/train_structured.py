"""训练 XGBoost 结构化模态。

对应 D03 §4.3：
    structured → XGBoost → score_struct

关键契约（修复历史缺陷）：
- 训练使用带列名的 DataFrame，booster.feature_names 即为真实特征名；
  serving 侧 StructuredModality._format_features 按 name 取值才能对齐，
  否则全部 miss → 全零向量（模型失明且无报错）。
- 指标一律在分层 holdout 上计算；训练集自评会虚高（AUC≈1.0），
  导致发布门槛（AUC≥0.92）形同虚设。

输出：model_versions 表 status=REGISTERED，model_type=STRUCTURED。
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    # holdout 评估数据（pipeline 用于融合层 Stacking 对齐）
    val_indices: list[int] = field(default_factory=list)
    val_labels: list[int] = field(default_factory=list)
    val_probas: list[float] = field(default_factory=list)


def train(
    features: list[list[float]],
    labels: list[int],
    save_path: str,
    params: dict[str, Any] | None = None,
    feature_names: list[str] | None = None,
) -> StructuredTrainResult:
    """训练 XGBoost 二分类模型。

    Args:
        features: 训练特征矩阵（List[List[float]]）
        labels: 标签（0/1）
        save_path: 模型保存路径（.json 或 .xgb）
        params: XGBoost 超参数
        feature_names: 特征名列表（与 FeatureStore.schema.feature_names 对齐；
            提供后 booster 携带真实列名，serving 端按名取值才可对齐）
    """
    import numpy as np  # type: ignore
    import xgboost as xgb  # type: ignore

    X = np.asarray(features, dtype=np.float32)
    y = np.asarray(labels, dtype=np.int32)
    n_samples, n_features = X.shape

    if feature_names is not None and len(feature_names) != n_features:
        raise ValueError(
            f"feature_names length {len(feature_names)} != n_features {n_features}"
        )

    from .evaluate import stratified_split

    train_idx, val_idx = stratified_split(labels)

    # 类别不平衡：scale_pos_weight = 负样本数/正样本数
    pos = max(int((y == 1).sum()), 1)
    neg = max(int((y == 0).sum()), 1)

    default_params: dict[str, Any] = {
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
        "scale_pos_weight": neg / pos,
    }
    if params:
        default_params.update(params)

    # 带列名的 DataFrame 训练 → 模型内嵌 feature_names（训练↔服务特征契约）
    if feature_names is not None:
        import pandas as pd  # type: ignore

        X_fit = pd.DataFrame(X, columns=list(feature_names))
    else:
        X_fit = X

    model = xgb.XGBClassifier(**default_params)

    if val_idx:
        X_train = X_fit.iloc[train_idx] if hasattr(X_fit, "iloc") else X_fit[train_idx]
        X_val = X_fit.iloc[val_idx] if hasattr(X_fit, "iloc") else X_fit[val_idx]
        model.fit(X_train, y[train_idx])
        eval_labels = y[val_idx]
        probas = model.predict_proba(X_val)[:, 1]
        metric_source = "holdout"
    else:
        # 数据过少或单类别：无法切分，退回训练集评估并如实标注
        logger.warning("structured.train.eval_on_train_fallback", n_samples=n_samples)
        model.fit(X_fit, y)
        eval_labels = y
        probas = model.predict_proba(X_fit)[:, 1]
        metric_source = "train"

    from .evaluate import compute_auc, compute_f1, compute_recall_at_fpr

    metrics = {
        "auc": compute_auc(eval_labels.tolist(), probas.tolist()),
        "f1": compute_f1(
            eval_labels.tolist(), (probas >= 0.5).astype(int).tolist()
        ),
        "recall_at_1pct_fpr": compute_recall_at_fpr(
            eval_labels.tolist(), probas.tolist(), fpr_threshold=0.01
        ),
        "metric_source": 1.0 if metric_source == "holdout" else 0.0,
    }
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    # 通过底层 Booster 保存：跨 xgboost 版本稳定，且保留 feature_names 契约
    model.get_booster().save_model(save_path)
    logger.info(
        "structured.train.done",
        save_path=save_path,
        n_samples=n_samples,
        n_features=n_features,
        metric_source=metric_source,
        metrics={k: v for k, v in metrics.items() if k != "metric_source"},
    )
    return StructuredTrainResult(
        model_path=save_path,
        n_samples=n_samples,
        n_features=n_features,
        metrics=metrics,
        val_indices=val_idx,
        val_labels=eval_labels.tolist(),
        val_probas=[float(p) for p in probas],
    )


__all__ = ["train", "StructuredTrainResult"]
