"""训练融合层（Stacking 元学习器）。

对应 D03 §4.3：
    三模态融合 (5ms):
     fusion_priority_engine 加权 weights = {struct: 0.6, text: 0.2, behavior: 0.2}
     熔断模态降权至 0.05，其余模态权重按比例放大
     Stacking 元学习器融合

输出：model_versions 表 status=REGISTERED，model_type=FUSION。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class FusionTrainResult:
    model_path: str
    n_samples: int
    metrics: dict[str, float]


def train(
    structured_scores: list[float],
    text_scores: list[float],
    behavior_scores: list[float],
    labels: list[int],
    save_path: str,
) -> FusionTrainResult:
    """训练 Stacking 元学习器（基于三模态分数输入）。

    元学习器：LogisticRegression（轻量、可解释）。
    输入特征：[structured, text, behavior] 三模态分数。
    """
    import numpy as np  # type: ignore
    from sklearn.linear_model import LogisticRegression  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    X = np.column_stack(
        [
            np.asarray(structured_scores, dtype=np.float32),
            np.asarray(text_scores, dtype=np.float32),
            np.asarray(behavior_scores, dtype=np.float32),
        ]
    )
    y = np.asarray(labels, dtype=np.int32)

    if len(set(y.tolist())) < 2:
        logger.warning("fusion.train.single_class_skipped", n_samples=len(y))
        return FusionTrainResult(model_path=save_path, n_samples=len(y), metrics={"auc": 0.5})

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = LogisticRegression(
        penalty="l2", C=1.0, solver="lbfgs", max_iter=200, random_state=42
    )
    model.fit(X_train, y_train)
    probas = model.predict_proba(X_test)[:, 1]

    import joblib  # type: ignore

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, save_path)

    from .evaluate import compute_auc, compute_f1, compute_recall_at_fpr

    metrics = {
        "auc": compute_auc(y_test.tolist(), probas.tolist()),
        "f1": compute_f1(y_test.tolist(), (probas >= 0.5).astype(int).tolist()),
        "recall_at_1pct_fpr": compute_recall_at_fpr(
            y_test.tolist(), probas.tolist(), fpr_threshold=0.01
        ),
    }
    logger.info("fusion.train.done", save_path=save_path, n_samples=len(y), metrics=metrics)
    return FusionTrainResult(model_path=save_path, n_samples=len(y), metrics=metrics)


__all__ = ["train", "FusionTrainResult"]
