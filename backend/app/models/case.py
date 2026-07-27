"""案件与申诉模型（D04 V1.1 §3.3）。

表：cases / case_events / appeals
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


class Case(Base, PKMixin, TenantMixin):
    """案件表（D04 §3.3）。

    type: FRAUD / AML / CHARGEBACK（基准 §3.7）
    level: P0 / P1 / P2 / P3（基准 §3.7）
    status: OPEN / IN_REVIEW / CONFIRMED / CLOSED / FALSE_ALARM（基准 §3.2）
    """

    __tablename__ = "cases"

    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    score_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    case_no: Mapped[str] = mapped_column(String(50), nullable=False)
    # type: FRAUD / AML / CHARGEBACK
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    # level: P0 / P1 / P2 / P3
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    # status: OPEN / IN_REVIEW / CONFIRMED / CLOSED / FALSE_ALARM
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    chargeback_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    graph_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseEvent(Base, PKMixin, TenantMixin):
    """案件事件表（D04 §3.3）。"""

    __tablename__ = "case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class Appeal(Base, PKMixin, TenantMixin):
    """申诉表（D04 §3.3）。

    status: PENDING / APPROVED / REJECTED / WITHDRAWN（基准 §3.10）
    """

    __tablename__ = "appeals"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # appellant_type: MERCHANT / CARDHOLDER
    appellant_type: Mapped[str] = mapped_column(String(20), nullable=False)
    appellant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # status: PENDING / APPROVED / REJECTED / WITHDRAWN
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


__all__ = ["Appeal", "Case", "CaseEvent"]
