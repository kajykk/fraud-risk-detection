"""漂移检测子模块（D03 §4.5 复用 DWS drift_detector）。

对应 baseline §3.12：
    drift_severity: LOW | MEDIUM | HIGH | CRITICAL
    drift_metric: PSI | KL | KS | WASSERSTEIN
"""

from .detector import (
    PSI_STABLE,
    PSI_SLIGHT,
    PSI_SIGNIFICANT,
    DriftDetector,
    compute_kl,
    compute_psi,
)
from .alerter import DriftAlerter, DriftAlertRecord

__all__ = [
    "DriftDetector",
    "DriftAlerter",
    "DriftAlertRecord",
    "compute_psi",
    "compute_kl",
    "PSI_STABLE",
    "PSI_SLIGHT",
    "PSI_SIGNIFICANT",
]
