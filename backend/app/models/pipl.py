"""PIPL 合规模型（D04 V1.1 §3.8-3.10）。

表：consent_records / deletion_requests / fairness_reports
（V1.1 新增三张 PIPL 合规表，均启用 RLS）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


def _utcnow():
    return datetime.now(UTC)


class ConsentRecord(Base, PKMixin, TenantMixin):
    """同意记录表（D04 §3.8，PIPL §14-16）。

    consent_status: GRANTED / WITHDRAWN / EXPIRED（基准 §3.11）
    purpose: TRANSACTION_SCORING / FRAUD_DETECTION / AML_REPORT / MARKETING / RESEARCH（基准 §3.11）
    """

    __tablename__ = "consent_records"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # consent_type: DATA_PROCESSING / MARKETING / THIRD_PARTY_SHARE（D04 §3.8）
    consent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # consent_status: GRANTED / WITHDRAWN / EXPIRED
    consent_status: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # purpose: TRANSACTION_SCORING / FRAUD_DETECTION / AML_REPORT / MARKETING / RESEARCH
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    # legal_basis: CONSENT / CONTRACT / LEGAL_OBLIGATION
    legal_basis: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DeletionRequest(Base, PKMixin, TenantMixin):
    """删除请求表（D04 §3.9，PIPL §45-47）。

    request_type: ACCOUNT_DELETION / DATA_PORTABILITY / RECTIFICATION
    status: PENDING / PROCESSING / COMPLETED / REJECTED（基准 §3.8 deletion_request_status）
    """

    __tablename__ = "deletion_requests"

    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # request_type: ACCOUNT_DELETION / DATA_PORTABILITY / RECTIFICATION
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # status: PENDING / PROCESSING / COMPLETED / REJECTED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # verification_method: ID_CARD / PHONE_OTP / EMAIL_OTP / FACE
    verification_method: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class FairnessReport(Base, PKMixin, TenantMixin):
    """公平性报告表（D04 §3.10，PIPL §24 自动化决策公平性）。

    protected_attribute: AGE / GENDER / REGION
    status: PASS / FAIL / REVIEW（基准 §3.9）
    合规阈值：disparate_impact_ratio >= 0.8（80% rule）
    """

    __tablename__ = "fairness_reports"

    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    report_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    report_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # protected_attribute: AGE / GENDER / REGION
    protected_attribute: Mapped[str] = mapped_column(String(20), nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_rate: Mapped[Any] = mapped_column(Numeric(10, 6), nullable=False)
    disparate_impact_ratio: Mapped[Any] = mapped_column(Numeric(10, 6), nullable=False)
    threshold: Mapped[Any] = mapped_column(Numeric(5, 4), nullable=False, default=0.8)
    # status: PASS / FAIL / REVIEW
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("threshold >= 0.8", name="ck_fairness_reports_threshold_min"),
        CheckConstraint(
            "disparate_impact_ratio >= 0", name="ck_fairness_reports_dir_nonneg"
        ),
    )


__all__ = ["ConsentRecord", "DeletionRequest", "FairnessReport"]
