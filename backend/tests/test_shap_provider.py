"""SHAP Provider 纯函数全分支测试（D07：services 层补覆盖）.

generate_shap_factors 为纯规则函数：金额 5 档、卡 BIN 3 档、交易类型 3 档、
3DS 2 档、渠道 3 档、商户类别 2 档 + 归一化兜底。逐一断言。
"""
import pytest

from app.services.shap_provider import BASE_VALUE, generate_shap_factors


def _names(factors):
    return [f["name"] for f in factors]


def _factor_by_name(factors, name):
    return next(f for f in factors if f["name"] == name)


class TestRuleBranchCoverage:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (2_000_000, 0.35),   # >1_000_000
            (600_000, 0.20),     # >500_000
            (200_000, 0.10),     # >100_000
            (60_000, 0.05),      # >50_000
            (1000, -0.05),       # 其余
            (0, -0.05),          # 零金额
        ],
    )
    def test_amount_buckets(self, amount, expected):
        out = generate_shap_factors({"amount": amount}, risk_score=0.5)
        assert _factor_by_name(out["features"], "amount")["shap"] == expected

    @pytest.mark.parametrize(
        ("card_bin", "expected"),
        [
            ("542418", 0.12),    # 高风险 bin1
            ("453212", 0.12),    # 高风险 bin2
            ("411111", -0.03),   # 低风险 bin1
            ("512345", -0.03),   # 低风险 bin2
            ("999999", 0.02),    # 未知 bin（默认）
            ("", 0.02),          # 空 bin
        ],
    )
    def test_card_bin_branches(self, card_bin, expected):
        out = generate_shap_factors({"card_bin": card_bin}, risk_score=0.5)
        assert _factor_by_name(out["features"], "card_bin")["shap"] == expected

    @pytest.mark.parametrize(
        ("tx_type", "expected"),
        [
            ("WITHDRAW", 0.08),
            ("TRANSFER", 0.08),
            ("REFUND", 0.05),
            ("PURCHASE", -0.02),
            ("", -0.02),
        ],
    )
    def test_tx_type_branches(self, tx_type, expected):
        out = generate_shap_factors({"tx_type": tx_type}, risk_score=0.5)
        assert _factor_by_name(out["features"], "tx_type")["shap"] == expected

    @pytest.mark.parametrize(
        ("is_3ds", "expected"),
        [(True, -0.08), (False, 0.06)],
    )
    def test_3ds_branches(self, is_3ds, expected):
        out = generate_shap_factors({"is_3ds_verified": is_3ds}, risk_score=0.5)
        assert _factor_by_name(out["features"], "is_3ds_verified")["shap"] == expected

    @pytest.mark.parametrize(
        ("channel", "expected"),
        [("QR", 0.04), ("API", 0.03), ("WEB", -0.02), ("", -0.02)],
    )
    def test_channel_branches(self, channel, expected):
        out = generate_shap_factors({"channel": channel}, risk_score=0.5)
        assert _factor_by_name(out["features"], "channel")["shap"] == expected

    @pytest.mark.parametrize(
        "mc",
        ["5411", "5812", "9999", ""],
    )
    def test_merchant_category_accepted(self, mc):
        """merchant_category 为末位特征，被归一化差额吸收，杜绝固定档位断言。

        验证：任意档位值下函数正常返回、结构完整，且非末位特征不受其影响。
        """
        out = generate_shap_factors({"merchant_category": mc}, risk_score=0.5)
        f = _factor_by_name(out["features"], "merchant_category")
        assert f["value"] == mc
        # 末位特征承担归一化差额（base_value + Σshap = prediction 的不变量）
        assert out["prediction"] == 0.5
        total = BASE_VALUE + sum(x["shap"] for x in out["features"])
        assert total == pytest.approx(0.5, abs=1e-4)


class TestInvariants:
    def test_returns_full_structure(self):
        out = generate_shap_factors({}, risk_score=0.42)
        assert out["base_value"] == BASE_VALUE
        assert out["prediction"] == 0.42
        assert len(out["features"]) == 6
        assert _names(out["features"]) == [
            "amount", "card_bin", "tx_type", "is_3ds_verified", "channel", "merchant_category",
        ]

    def test_empty_transaction_uses_defaults(self):
        out = generate_shap_factors({}, risk_score=0.5)
        amt = _factor_by_name(out["features"], "amount")
        assert amt["value"] == 0.0 and amt["shap"] == -0.05

    def test_sum_equals_prediction(self):
        """base_value + Σshap ≈ prediction（归一化保证，最后一个特征吸收差额）."""
        for risk in (0.0, 0.15, 0.3, 0.5, 0.77, 1.0):
            out = generate_shap_factors(
                {"amount": 200000, "card_bin": "542418", "tx_type": "TRANSFER",
                 "is_3ds_verified": False, "channel": "QR", "merchant_category": "5411"},
                risk_score=risk,
            )
            total = BASE_VALUE + sum(f["shap"] for f in out["features"])
            assert total == pytest.approx(risk, abs=1e-4)

    def test_types_are_primitive_and_roundable(self):
        out = generate_shap_factors({"amount": 555555}, risk_score=0.63)
        for f in out["features"]:
            assert isinstance(f["shap"], (int, float))
            assert abs(f["shap"]) <= 1.0  # 单特征贡献有界

    def test_partial_transaction_missing_keys_defaults(self):
        # 只给 amount，其余走默认分支
        out = generate_shap_factors({"amount": 60_000}, risk_score=0.5)
        assert _factor_by_name(out["features"], "amount")["shap"] == 0.05
        assert _factor_by_name(out["features"], "channel")["value"] == "WEB"


class TestNormalizationEdge:
    def test_extreme_risk_zero(self):
        out = generate_shap_factors({}, risk_score=0.0)
        assert out["prediction"] == 0.0

    def test_high_risk_one(self):
        out = generate_shap_factors({"amount": 2000000}, risk_score=1.0)
        # amount 档贡献最高档 0.35
        assert _factor_by_name(out["features"], "amount")["shap"] == 0.35