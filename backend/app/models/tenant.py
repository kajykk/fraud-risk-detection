"""租户与商户模型（D04 V1.1 §3.1）。

表：tenants / merchants / api_keys
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin, TimestampMixin


def _utcnow():
    return datetime.now(UTC)


class Tenant(Base, PKMixin, TimestampMixin):
    """租户表（D04 §3.1）。

    注：自身即租户，不含 tenant_id，不启用 RLS（D04 §9.2）。
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    # type: BANK / PAYMENT / MERCHANT（基准 §3.6）
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="BANK")
    # plan: STANDARD / PRO / ENTERPRISE（基准 §3.6）
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="STANDARD")
    # status: ACTIVE / INACTIVE
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    encryption_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # pci_scope: CDE / NON_CDE（基准 §3.6）
    pci_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="CDE")


class Merchant(Base, PKMixin, TenantMixin, TimestampMixin):
    """商户表（D04 §3.1）。"""

    __tablename__ = "merchants"

    merchant_no: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_whitelist: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    rate_limit_qps: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    risk_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ApiKey(Base, PKMixin, TenantMixin):
    """API Key 表（D04 §3.1）。"""

    __tablename__ = "api_keys"

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    ip_whitelist: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


__all__ = ["ApiKey", "Merchant", "Tenant"]
