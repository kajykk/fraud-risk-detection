"""模型评估指标。

对应 D03 §4.3 / baseline §2.1：
- AUC ≥ 0.92
- Recall@1%FPR ≥ 0.85
- 模型 PSI 7d < 0.25
- 误报率 ≤ 5%（生产）

漂移相关 PSI/KL 实现见 ml/drift/detector.py。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def compute_auc(labels: list[int], probas: list[float]) -> float:
    """AUC-ROC。"""
    try:
        from sklearn.metrics import roc_auc_score  # type: ignore

        if len(set(labels)) < 2:
            return 0.5
        return float(roc_auc_score(labels, probas))
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate.auc.failed", error=str(exc))
        return 0.5


def compute_f1(labels: list[int], preds: list[int]) -> float:
    """F1 分数。"""
    try:
        from sklearn.metrics import f1_score  # type: ignore

        return float(f1_score(labels, preds, zero_division=0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate.f1.failed", error=str(exc))
        return 0.0


def compute_recall_at_fpr(
    labels: list[int], probas: list[float], fpr_threshold: float = 0.01
) -> float:
    """Recall@1%FPR：FPR=1% 时的 Recall。"""
    try:
        import numpy as np  # type: ignore
        from sklearn.metrics import roc_curve  # type: ignore

        if len(set(labels)) < 2:
            return 0.0
        fpr, tpr, _ = roc_curve(labels, probas)
        # 找到 fpr <= fpr_threshold 的最大 tpr
        mask = fpr <= fpr_threshold
        if not mask.any():
            return 0.0
        return float(np.max(tpr[mask]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate.recall_at_fpr.failed", error=str(exc))
        return 0.0


def compute_precision_recall(
    labels: list[int], probas: list[float], threshold: float = 0.5
) -> tuple[float, float]:
    """精确率/召回率。"""
    try:
        from sklearn.metrics import precision_score, recall_score  # type: ignore

        preds = [1 if p >= threshold else 0 for p in probas]
        return (
            float(precision_score(labels, preds, zero_division=0)),
            float(recall_score(labels, preds, zero_division=0)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("evaluate.precision_recall.failed", error=str(exc))
        return 0.0, 0.0


def compute_confusion(
    labels: list[int], probas: list[float], threshold: float = 0.5
) -> dict[str, int]:
    """混淆矩阵。"""
    tp = fp = tn = fn = 0
    preds = [1 if p >= threshold else 0 for p in probas]
    for label, pred in zip(labels, preds, strict=False):
        if label == 1 and pred == 1:
            tp += 1
        elif label == 0 and pred == 1:
            fp += 1
        elif label == 0 and pred == 0:
            tn += 1
        else:
            fn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def aggregate_metrics(
    labels: list[int], probas: list[float]
) -> dict[str, float]:
    """聚合评估指标（AUC/F1/Recall@1%FPR + 混淆矩阵）。"""
    preds = [1 if p >= 0.5 else 0 for p in probas]
    return {
        "auc": compute_auc(labels, probas),
        "f1": compute_f1(labels, preds),
        "recall_at_1pct_fpr": compute_recall_at_fpr(labels, probas, 0.01),
        **{k: float(v) for k, v in compute_confusion(labels, probas).items()},
    }


__all__ = [
    "compute_auc",
    "compute_f1",
    "compute_recall_at_fpr",
    "compute_precision_recall",
    "compute_confusion",
    "aggregate_metrics",
]
