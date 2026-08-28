"""漂移检测（后端 Worker 侧，PSI 纯函数）。

与 ml/drift/detector.py 阈值保持一致（baseline §3.12）：
- PSI < 0.1 → LOW（稳定）
- 0.1 ≤ PSI < 0.25 → MEDIUM（轻微漂移）
- PSI ≥ 0.25 → CRITICAL（显著漂移，触发 L2 模型级 Kill Switch）
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PSI_STABLE = 0.1
PSI_SLIGHT = 0.25


@dataclass(frozen=True)
class DriftResult:
    """漂移检测结果。"""

    metric_type: str  # PSI | KL
    value: float
    threshold: float
    severity: str  # LOW | MEDIUM | CRITICAL
    is_drifted: bool


def compute_psi(
    current_dist: list[float],
    reference_dist: list[float],
    n_bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """计算 PSI（Population Stability Index）。

    numpy 向量化实现（searchsorted 分桶），语义与原逐样本循环一致：
    落在 [bins[0], bins[-1]] 之外的值不计数，等于最大边界值归最后一桶。

    Args:
        current_dist: 当前样本值列表
        reference_dist: 基线样本值列表
        n_bins: 分桶数
        eps: 防 log(0) 平滑项
    """
    if not current_dist or not reference_dist:
        return 0.0
    import numpy as np

    sorted_ref = sorted(reference_dist)
    # 等频分桶：n_bins+1 个边界（含 min/max），对一般分布有效
    quantiles = [
        sorted_ref[min(len(sorted_ref) - 1, int(len(sorted_ref) * i / n_bins))]
        for i in range(n_bins + 1)
    ]
    bins = sorted(set(quantiles))
    if len(bins) < 2:
        # 参考分布退化为常数（零方差），无法分桶 → 视为无漂移
        return 0.0
    edges = np.array(bins, dtype=np.float64)

    def histogram(values: list[float]) -> list[float]:
        v = np.asarray(values, dtype=np.float64)
        # 区间外（v < bins[0] 或 v > bins[-1]）与原实现一致：不计入任何桶
        valid = (v >= edges[0]) & (v <= edges[-1])
        idx = np.searchsorted(edges, v[valid], side="right") - 1
        # 等于最大边界值 → 归入最后一个桶
        idx[idx == len(edges) - 1] = len(edges) - 2
        counts = np.bincount(idx, minlength=len(edges) - 1).astype(np.float64)
        total = float(counts.sum()) or 1.0
        return [float(x / total) for x in counts]

    p_ref = histogram(reference_dist)
    p_cur = histogram(current_dist)

    psi = 0.0
    for p, q in zip(p_ref, p_cur, strict=False):
        p = max(p, eps)
        q = max(q, eps)
        psi += (p - q) * math.log(p / q)
    return float(psi)


def classify_severity(value: float) -> tuple[str, bool]:
    """PSI → (severity, is_drifted)。"""
    if value < PSI_STABLE:
        return "LOW", False
    if value < PSI_SLIGHT:
        return "MEDIUM", True
    return "CRITICAL", True


__all__ = [
    "PSI_SLIGHT",
    "PSI_STABLE",
    "DriftResult",
    "classify_severity",
    "compute_psi",
]
