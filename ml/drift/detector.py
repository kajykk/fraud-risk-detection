"""PSI / KL 散度漂移检测。

阈值（baseline §2.1 + 任务说明）：
- PSI < 0.1            → 稳定（STABLE / LOW）
- 0.1 ≤ PSI < 0.25     → 轻微漂移（MEDIUM）
- PSI ≥ 0.25           → 显著漂移（CRITICAL）

触发：
- PSI ≥ 0.1 即写入 drift_alerts 表（D04 §3.5）
- PSI ≥ 0.25 触发 L2 模型级 Kill Switch（ADR-013）
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


# PSI 阈值
PSI_STABLE = 0.1
PSI_SLIGHT = 0.25  # ≥0.25 触发显著漂移（CRITICAL，ADR-013 L2 Kill Switch）


@dataclass(frozen=True)
class DriftResult:
    """漂移检测结果。"""

    metric_type: str  # PSI | KL | KS | WASSERSTEIN
    value: float
    threshold: float
    severity: str  # LOW | MEDIUM | HIGH | CRITICAL
    is_drifted: bool


def compute_psi(
    current_dist: list[float],
    reference_dist: list[float],
    n_bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """计算 PSI（Population Stability Index）。

    Args:
        current_dist: 当前样本值列表
        reference_dist: 基线样本值列表
        n_bins: 分桶数
        eps: 防 log(0) 平滑项

    Returns:
        psi: float
    """
    if not current_dist or not reference_dist:
        return 0.0
    # 用 reference_dist 分位数作为切分点
    sorted_ref = sorted(reference_dist)
    quantiles = [
        sorted_ref[int(len(sorted_ref) * (i + 1) / n_bins) - 1]
        for i in range(n_bins - 1)
    ]
    bins = [-math.inf] + quantiles + [math.inf]

    def histogram(values: list[float]) -> list[float]:
        counts = [0.0] * n_bins
        for v in values:
            for i in range(n_bins):
                if bins[i] <= v < bins[i + 1]:
                    counts[i] += 1.0
                    break
        total = sum(counts) or 1.0
        return [c / total for c in counts]

    p_ref = histogram(reference_dist)
    p_cur = histogram(current_dist)

    psi = 0.0
    for p, q in zip(p_ref, p_cur, strict=False):
        p = max(p, eps)
        q = max(q, eps)
        psi += (p - q) * math.log(p / q)
    return float(psi)


def compute_kl(p: list[float], q: list[float], eps: float = 1e-6) -> float:
    """KL 散度 KL(p || q)。

    Args:
        p: 当前分布（概率列表，需归一化或会被归一化）
        q: 基线分布
        eps: 平滑项

    Returns:
        kl: float
    """
    if not p or not q or len(p) != len(q):
        return 0.0
    sum_p = sum(p) or 1.0
    sum_q = sum(q) or 1.0
    norm_p = [x / sum_p for x in p]
    norm_q = [x / sum_q for x in q]
    kl = 0.0
    for pi, qi in zip(norm_p, norm_q, strict=False):
        pi = max(pi, eps)
        qi = max(qi, eps)
        kl += pi * math.log(pi / qi)
    return float(kl)


def classify_severity(metric_type: str, value: float) -> tuple[str, bool]:
    """根据指标值返回 (severity, is_drifted)。"""
    if metric_type == "PSI":
        if value < PSI_STABLE:
            return "LOW", False
        if value < PSI_SLIGHT:
            return "MEDIUM", True
        return "CRITICAL", True
    # KL 默认阈值 0.1
    if value < 0.1:
        return "LOW", False
    if value < 0.5:
        return "MEDIUM", True
    return "CRITICAL", True


class DriftDetector:
    """漂移检测器。"""

    def detect_psi(
        self,
        current: list[float],
        reference: list[float],
        n_bins: int = 10,
    ) -> DriftResult:
        value = compute_psi(current, reference, n_bins=n_bins)
        severity, is_drifted = classify_severity("PSI", value)
        return DriftResult(
            metric_type="PSI",
            value=value,
            threshold=PSI_STABLE,
            severity=severity,
            is_drifted=is_drifted,
        )

    def detect_kl(
        self, current: list[float], reference: list[float]
    ) -> DriftResult:
        value = compute_kl(current, reference)
        severity, is_drifted = classify_severity("KL", value)
        return DriftResult(
            metric_type="KL",
            value=value,
            threshold=0.1,
            severity=severity,
            is_drifted=is_drifted,
        )


__all__ = [
    "PSI_STABLE",
    "PSI_SLIGHT",
    "DriftResult",
    "DriftDetector",
    "compute_psi",
    "compute_kl",
    "classify_severity",
]
