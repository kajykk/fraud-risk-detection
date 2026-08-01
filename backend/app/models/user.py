"""用户模型（D04 V1.1 §3.1 补充）。

表：users
- 平台/商户后台登录用户（/auth/login）
- roles: TENANT_ADMIN / MERCHANT_ADMIN / RISK_ANALYST / RISK_MANAGER / AUDITOR /
  COMPLIANCE_OFFICER / DEVOPS_OPS（D05 §3.2 角色矩阵）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin, TimestampMixin


def _utcnow():
    return datetime.now(UTC)


class User(Base, PKMixin, TenantMixin, TimestampMixin):
    """用户表。

    status: ACTIVE / INACTIVE / LOCKED
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # roles: 角色列表（D05 §3.2）
    roles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # status: ACTIVE / INACTIVE / LOCKED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["User"]
