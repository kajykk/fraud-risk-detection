"""反洗钱模型（D04 V1.1 §3.6）。

表：aml_reports / sanction_screenings
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


def _utcnow():
    return datetime.now(UTC)


class AmlReport(Base, PKMixin, TenantMixin):
    """反洗钱报告表（D04 §3.6）。

    report_type: LARGE / SUSPICIOUS（基准 §3.9）
    status: PENDING / SUBMITTED / ACCEPTED / REJECTED（基准 §3.9）
    """

    __tablename__ = "aml_reports"

    # report_type: LARGE / SUSPICIOUS
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    report_no: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_xml: Mapped[str] = mapped_column(Text, nullable=False)
    # status: PENDING / SUBMITTED / ACCEPTED / REJECTED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_to: Mapped[str | None] = mapped_column(String(50), nullable=True)
    submission_receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class SanctionScreening(Base, PKMixin, TenantMixin):
    """制裁名单筛查表（D04 §3.6）。"""

    __tablename__ = "sanction_screenings"

    # entity_type: PERSON / ENTITY
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # list_source: UN / OFAC / PEP
    list_source: Mapped[str] = mapped_column(String(50), nullable=False)
    match_score: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    matched_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # status: PENDING / CLEARED / BLOCKED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


__all__ = ["AmlReport", "SanctionScreening"]
