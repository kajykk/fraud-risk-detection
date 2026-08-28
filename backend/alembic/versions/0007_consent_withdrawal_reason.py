"""consent_records 增加撤回原因列（PIPL 撤回合规留痕）。

问题：POST /pipl/consent/withdraw 已接收 withdrawal_reason（自由文本），
但 consent_records 表无对应列，数据主体撤回时提供的理由被静默丢弃——
违反 PIPL §16 撤回同意的证据留痕义务。

方案：新增可空 withdrawal_reason（Text），撤回端点持久化该字段。

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consent_records",
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("consent_records", "withdrawal_reason")
