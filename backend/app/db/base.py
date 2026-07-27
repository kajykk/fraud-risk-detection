"""SQLAlchemy Base + 公共字段 mixin（D04 V1.1 §1 设计原则）。

Mixin：
- TimestampMixin: created_at / updated_at（TIMESTAMPTZ）
- TenantMixin: tenant_id（UUID，多租户隔离，ADR-015）
- SoftDeleteMixin: deleted_at（软删除）
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid7_default() -> uuid.UUID:
    """生成 UUID（占位用 uuid4，生产应替换为 uuid7 实现）。

    TODO: 实现 RFC 9562 UUIDv7（时间戳排序），生产环境使用 uuid7 保证索引局部性。
    """
    return uuid.uuid4()


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类。"""

    # 类型注解映射，便于 Mapped[uuid.UUID] / Mapped[datetime] 自动推断
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
    }


class TimestampMixin:
    """时间戳 mixin：created_at / updated_at。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantMixin:
    """多租户 mixin：tenant_id（ADR-015，强制非空）。"""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """软删除 mixin：deleted_at。"""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class PKMixin:
    """主键 mixin：UUID v7 主键。"""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_uuid7_default,
    )


__all__ = ["Base", "PKMixin", "SoftDeleteMixin", "TenantMixin", "TimestampMixin"]
