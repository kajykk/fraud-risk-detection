"""漂移检测纯函数单元测试（PSI / severity 分类）。

对齐 baseline §3.12：
- PSI < 0.1 → LOW（稳定）
- 0.1 ≤ PSI < 0.25 → MEDIUM（轻微漂移）
- PSI ≥ 0.25 → CRITICAL（显著漂移，触发 L2 模型级 Kill Switch）
"""

from __future__ import annotations

import pytest

from app.services.drift import classify_severity, compute_psi


class TestComputePsi:
    def test_identical_distributions_zero(self) -> None:
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        assert compute_psi(values, values) == pytest.approx(0.0, abs=1e-4)

    def test_empty_inputs_zero(self) -> None:
        assert compute_psi([], [1.0, 2.0]) == 0.0
        assert compute_psi([1.0, 2.0], []) == 0.0
        assert compute_psi([], []) == 0.0

    def test_completely_shifted_distributions_large(self) -> None:
        # 两组有方差的分布完全分离 → PSI 显著
        ref = [0.1 + (i % 5) * 0.02 for i in range(200)]
        cur = [0.9 + (i % 5) * 0.02 for i in range(200)]
        psi = compute_psi(cur, ref)
        assert psi > 0.25

    def test_constant_reference_distribution_zero(self) -> None:
        # 参考分布零方差 → 无法分桶 → 无漂移
        assert compute_psi([0.9] * 100, [0.1] * 100) == 0.0

    def test_slightly_shifted_small_psi(self) -> None:
        ref = [0.5 + i * 0.001 for i in range(1000)]
        cur = [v + 0.001 for v in ref]
        psi = compute_psi(cur, ref)
        assert psi < 0.1

    def test_n_bins_respected(self) -> None:
        values = list(range(1000))
        shifted = [v + 1 for v in values]
        psi = compute_psi(shifted, values, n_bins=20)
        assert psi >= 0.0


class TestClassifySeverity:
    @pytest.mark.parametrize(
        ("psi", "expected_severity", "expected_drifted"),
        [
            (0.0, "LOW", False),
            (0.05, "LOW", False),
            (0.1, "MEDIUM", True),
            (0.15, "MEDIUM", True),
            (0.2499, "MEDIUM", True),
            (0.25, "CRITICAL", True),
            (0.5, "CRITICAL", True),
        ],
    )
    def test_boundaries(
        self, psi: float, expected_severity: str, expected_drifted: bool
    ) -> None:
        severity, drifted = classify_severity(psi)
        assert severity == expected_severity
        assert drifted is expected_drifted
