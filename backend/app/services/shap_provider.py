"""Mock SHAP Provider — 基于交易特征的规则式特征贡献生成。

不依赖 shap 库，根据交易特征计算各特征对风险评分的贡献值。
base_value + sum(shap_values) = prediction
"""

from __future__ import annotations

from typing import Any

BASE_VALUE = 0.15


def generate_shap_factors(
    transaction: dict[str, Any],
    risk_score: float,
) -> dict[str, Any]:
    """生成 mock SHAP 特征贡献。

    Args:
        transaction: 交易特征字典
        risk_score: 实际风险评分（0-1）

    Returns:
        {
            "base_value": 0.15,
            "prediction": risk_score,
            "features": [
                {"name": "amount", "value": ..., "shap": ...},
                ...
            ]
        }
    """
    amount = float(transaction.get("amount", 0))
    card_bin = str(transaction.get("card_bin", ""))
    tx_type = str(transaction.get("tx_type", "PURCHASE"))

    # 各特征贡献（正=推高风险，负=拉低风险）
    factors = []

    # 1. 金额特征（越大贡献越高）
    if amount > 1_000_000:
        amt_shap = 0.35
    elif amount > 500_000:
        amt_shap = 0.20
    elif amount > 100_000:
        amt_shap = 0.10
    elif amount > 50_000:
        amt_shap = 0.05
    else:
        amt_shap = -0.05
    factors.append({"name": "amount", "value": amount, "shap": round(amt_shap, 4)})

    # 2. 卡 BIN 风险
    if card_bin in ("542418", "453212"):
        bin_shap = 0.12
    elif card_bin in ("411111", "512345"):
        bin_shap = -0.03
    else:
        bin_shap = 0.02
    factors.append({"name": "card_bin", "value": card_bin, "shap": round(bin_shap, 4)})

    # 3. 交易类型
    if tx_type in ("WITHDRAW", "TRANSFER"):
        type_shap = 0.08
    elif tx_type == "REFUND":
        type_shap = 0.05
    else:
        type_shap = -0.02
    factors.append({"name": "tx_type", "value": tx_type, "shap": round(type_shap, 4)})

    # 4. 3DS 验证状态
    is_3ds = transaction.get("is_3ds_verified", False)
    if is_3ds:
        ds_shap = -0.08
    else:
        ds_shap = 0.06
    factors.append({"name": "is_3ds_verified", "value": is_3ds, "shap": round(ds_shap, 4)})

    # 5. 渠道
    channel = str(transaction.get("channel", "WEB"))
    if channel == "QR":
        ch_shap = 0.04
    elif channel == "API":
        ch_shap = 0.03
    else:
        ch_shap = -0.02
    factors.append({"name": "channel", "value": channel, "shap": round(ch_shap, 4)})

    # 6. 商户类别
    merchant_cat = str(transaction.get("merchant_category", ""))
    if merchant_cat in ("5411", "5812"):
        mc_shap = 0.05
    else:
        mc_shap = 0.0
    factors.append({"name": "merchant_category", "value": merchant_cat, "shap": round(mc_shap, 4)})

    # 归一化：确保 base_value + sum(shap) ≈ prediction
    total_shap = sum(f["shap"] for f in factors)
    # 调整最后一个特征使总和匹配
    diff = risk_score - BASE_VALUE - total_shap
    factors[-1]["shap"] = round(factors[-1]["shap"] + diff, 4)

    return {
        "base_value": BASE_VALUE,
        "prediction": risk_score,
        "features": factors,
    }
