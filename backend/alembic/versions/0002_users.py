"""users 表 + api_keys 查表 RLS 策略（P0 认证加固）。

1. users：登录用户表，启用 RLS（tenant_id 隔离）
2. api_keys：新增 key_hash 查表策略（app.api_key_lookup setting），
   供 TenantMiddleware 在未知租户时按哈希查找 API Key（仅返回哈希匹配行）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-01 08:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. users
    # ------------------------------------------------------------------ #
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(100), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("roles", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # users 启用 RLS（ADR-015）
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY tenant_isolation ON users FOR ALL USING "
        "(tenant_id = current_setting('app.tenant_id')::uuid);"
    )

    # ------------------------------------------------------------------ #
    # 2. api_keys 查表策略：允许在 app.api_key_lookup 与 key_hash 匹配时 SELECT
    #    （中间件在未知租户上下文下按哈希查找 API Key 的唯一通道）
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE POLICY api_key_lookup ON api_keys FOR SELECT USING "
        "(key_hash = current_setting('app.api_key_lookup', true));"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS api_key_lookup ON api_keys;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users;")
    op.drop_table("users")
