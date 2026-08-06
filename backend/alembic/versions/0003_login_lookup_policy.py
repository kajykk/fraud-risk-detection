"""users 表登录查表策略（修复登录 RLS 死锁）。

问题：0002 对 users 表 FORCE RLS 且策略要求 app.tenant_id，
但 /auth/login 在未知租户上下文中无法设置该参数 → 登录查询必然报错。

方案：新增 login_lookup 策略，允许在 app.user_login 与 username 匹配时 SELECT
（与 api_keys 的 api_key_lookup 查表策略同构）。
策略为 OR 关系：未命中 login_lookup 的行仍受 tenant_isolation 约束。

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 允许在 app.user_login 与 username 匹配时 SELECT（登录查表通道）
    op.execute(
        "CREATE POLICY login_lookup ON users FOR SELECT USING "
        "(username = current_setting('app.user_login', true));"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS login_lookup ON users;")
