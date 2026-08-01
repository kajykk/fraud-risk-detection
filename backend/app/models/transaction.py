"""交易与评分模型（D04 V1.1 §3.2）。

表：transactions / scores / shap_explanations
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


def _utcnow():
    return datetime.now(UTC)


class Transaction(Base, PKMixin, TenantMixin):
    """交易表（D04 §3.2，含 channel/risk_features/is_recurring/parent_tx_id）。"""

    __tablename__ = "transactions"

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    external_tx_id: Mapped[str] = mapped_column(String(100), nullable=False)
    card_token: Mapped[str] = mapped_column(String(64), nullable=False)
    card_bin: Mapped[str] = mapped_column(String(6), nullable=False)
    card_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    # tx_type: PURCHASE / WITHDRAW / REFUND / TRANSFER / TOPUP / PAYMENT（基准 §3.8）
    tx_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # channel: WEB / APP / POS / API / QR（基准 §3.8）
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_3ds_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    merchant_city: Mapped[str | None] = mapped_column(String(50), nullable=True)
    merchant_category: Mapped[str | None] = mapped_column(String(10), nullable=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[Any] = mapped_column(INET, nullable=True)
    user_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_tx_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Score(Base, PKMixin, TenantMixin):
    """评分记录表（D04 §3.2 / 基准 §4.2）。

    risk_score 类型：DECIMAL(5,4)，0.0000-1.0000（基准 §3.5）。
    decision 枚举：ALLOW / REVIEW / DENY / CHALLENGE（基准 §3.1）。
    """

    __tablename__ = "scores"

    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    # risk_score: DECIMAL(5,4)
    risk_score: Mapped[Any] = mapped_column(Numeric(5, 4), nullable=False)
    # risk_band: LOW / MEDIUM / HIGH / CRITICAL（基准 §3.5）
    risk_band: Mapped[str] = mapped_column(String(10), nullable=False)
    # decision: ALLOW / REVIEW / DENY / CHALLENGE（基准 §3.1）
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_hits: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    modality_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feature_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ShapExplanation(Base, PKMixin, TenantMixin):
    """SHAP 解释表（D04 §3.2）。"""

    __tablename__ = "shap_explanations"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    factors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    base_value: Mapped[Any] = mapped_column(Numeric(10, 6), nullable=False)
    output_value: Mapped[Any] = mapped_column(Numeric(10, 6), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["Score", "ShapExplanation", "Transaction"]
