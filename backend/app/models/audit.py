"""审计日志模型（D04 V1.1 §3.7）。

表：audit_logs（含 sequence_no，独立连接池串行写入）

串行写入约束（D04 §3.7）：
- 独立连接池
- sequence_no 基于 tenant_id 维度递增（Redis INCR key: audit_seq:{tenant_id}）
- 哈希链：current_hash = sha256(prev_hash || canonical_json(payload))
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


def _utcnow():
    return datetime.now(UTC)


class AuditLog(Base, PKMixin, TenantMixin):
    """审计日志表（D04 §3.7）。

    保留期 7 年（反洗钱合规要求，基准 §2.3）。
    按 created_at 月度分区。
    """

    __tablename__ = "audit_logs"

    # 租户内递增序列号（保证顺序性）
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ip: Mapped[Any] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # 哈希链
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 是否 CDE 区
    cde_zone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


__all__ = ["AuditLog"]
