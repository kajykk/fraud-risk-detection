"""特征存储（Feature Store）。

职责：
- 训练时特征工程：原始字段 → 数值向量
- 推理时特征对齐：保证训练/推理特征顺序一致
- 特征 schema 版本化（与 model_versions.feature_names 对齐）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class FeatureSchema:
    """特征 schema（写入 model_versions.feature_names JSONB）。"""

    name: str
    version: str
    feature_names: List[str]
    categorical_features: List[str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "feature_names": self.feature_names,
                "categorical_features": self.categorical_features,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "FeatureSchema":
        data = json.loads(raw)
        return cls(
            name=data["name"],
            version=data["version"],
            feature_names=data["feature_names"],
            categorical_features=data.get("categorical_features", []),
        )


# 默认结构化特征 schema（与 D04 transactions 字段对齐）
DEFAULT_STRUCTURED_FEATURES = FeatureSchema(
    name="structured_v1",
    version="v1",
    feature_names=[
        "amount_log",
        "hour_of_day",
        "day_of_week",
        "is_night",
        "merchant_risk_score",
        "card_age_days",
        "user_txn_count_24h",
        "user_txn_count_7d",
        "user_amount_sum_24h",
        "device_txn_count_1h",
        "ip_txn_count_1h",
        "is_new_device",
        "is_new_ip",
        "is_cross_border",
        "merchant_category_risk",
        "channel_web",
        "channel_app",
        "channel_pos",
        "channel_api",
        "channel_qr",
        "tx_type_purchase",
        "tx_type_withdraw",
        "tx_type_refund",
        "tx_type_transfer",
        "tx_type_topup",
        "tx_type_payment",
    ],
    categorical_features=["channel", "tx_type", "merchant_category"],
)


class FeatureStore:
    """特征存储 + 工程入口。"""

    def __init__(self, schema: FeatureSchema = DEFAULT_STRUCTURED_FEATURES) -> None:
        self.schema = schema

    def engineer(self, raw: Dict[str, Any]) -> List[float]:
        """原始特征 → 数值向量（按 schema.feature_names 顺序）。"""
        vector: List[float] = []
        for name in self.schema.feature_names:
            vector.append(float(self._extract(raw, name)))
        return vector

    def _extract(self, raw: Dict[str, Any], name: str) -> float:
        if name in raw:
            try:
                return float(raw[name])
            except (TypeError, ValueError):
                return 0.0
        # 派生特征
        if name == "amount_log":
            amt = raw.get("amount", 0.0)
            try:
                import math

                return math.log1p(max(float(amt), 0.0))
            except (TypeError, ValueError):
                return 0.0
        if name == "hour_of_day":
            ts = raw.get("occurred_at")
            if ts is None:
                return 0.0
            try:
                import datetime as dt

                t = ts if isinstance(ts, dt.datetime) else dt.datetime.fromisoformat(str(ts))
                return float(t.hour)
            except Exception:  # noqa: BLE001
                return 0.0
        if name == "is_night":
            ts = raw.get("occurred_at")
            try:
                import datetime as dt

                t = ts if isinstance(ts, dt.datetime) else dt.datetime.fromisoformat(str(ts))
                return 1.0 if t.hour in {0, 1, 2, 3, 4, 5} else 0.0
            except Exception:  # noqa: BLE001
                return 0.0
        # one-hot 编码
        for prefix in ("channel", "tx_type"):
            if name.startswith(f"{prefix}_"):
                value = name[len(prefix) + 1 :].upper()
                actual = str(raw.get(prefix, "")).upper()
                return 1.0 if actual == value else 0.0
        return 0.0

    def save_schema(self, path: str | Path) -> None:
        Path(path).write_text(self.schema.to_json(), encoding="utf-8")

    def load_schema(self, path: str | Path) -> FeatureSchema:
        self.schema = FeatureSchema.from_json(Path(path).read_text(encoding="utf-8"))
        return self.schema


__all__ = ["FeatureSchema", "FeatureStore", "DEFAULT_STRUCTURED_FEATURES"]
