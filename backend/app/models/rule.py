"""规则引擎模型（D04 V1.1 §3.4）。

表：rules / rule_versions

注意：rule_versions 必须含 tenant_id（D04 V1.1 Major 修订，基准 §4.3 例外条款）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


def _utcnow():
    return datetime.now(UTC)


class Rule(Base, PKMixin, TenantMixin):
    """规则表（D04 §3.4）。

    注：tenant_id 可空（null 表示全局规则，D04 §9.2）。此处声明为可空。
    action: BLOCK / REVIEW（基准 §3.4，2 值，区别于 decision 4 值）
    """

    __tablename__ = "rules"

    # 覆盖 TenantMixin 的 tenant_id 为可空（全局规则）
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(  # type: ignore[assignment]
        UUID(as_uuid=True), nullable=True, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # category: AMOUNT / GEO / DEVICE / VELOCITY / AML
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    # action: BLOCK / REVIEW（基准 §3.4）
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class RuleVersion(Base, PKMixin, TenantMixin):
    """规则版本表（D04 §3.4，V1.1 Major：强制 tenant_id 非空）。

    status: DRAFT / CANARY / ACTIVE / RETIRED（基准 §3.4）
    """

    __tablename__ = "rule_versions"

    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    # status: DRAFT / CANARY / ACTIVE / RETIRED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["Rule", "RuleVersion"]
