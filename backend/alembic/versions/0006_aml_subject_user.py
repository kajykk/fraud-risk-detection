"""aml_reports 增加数据主体字段（PIPL 法律保留按用户关联）。

问题（合规缺陷）：
- tasks_pipl.delete_data 的法律保留检查原为骨架实现：
  `WHERE tenant_id IS NOT NULL` —— 租户内任意成员的任意 AML 报告
  会阻断所有人的删除请求（反洗钱 7 年保留被无限扩大）。
- 根因：aml_reports 只有 transaction_id / case_id，无数据主体字段。

方案：
- 新增可空列 subject_user_account_id（String(100)，与
  transactions.user_account_id 同构）；
- (tenant_id, subject_user_account_id) 索引支撑删除任务的高频判定；
- 回填两路：报告直接关联交易（transaction_id → transactions）；
  经案件二跳（case_id → cases.transaction_id → transactions）。
- 可空设计：历史孤儿数据不阻断迁移，由删除任务的联表兜底复查。

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aml_reports",
        sa.Column("subject_user_account_id", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_aml_reports_tenant_subject",
        "aml_reports",
        ["tenant_id", "subject_user_account_id"],
    )

    # 回填路径①：报告直接关联交易
    op.execute(
        """
        UPDATE aml_reports ar
        SET subject_user_account_id = t.user_account_id
        FROM transactions t
        WHERE ar.transaction_id = t.id
          AND ar.subject_user_account_id IS NULL;
        """
    )
    # 回填路径②：经案件二跳（cases.transaction_id）
    op.execute(
        """
        UPDATE aml_reports ar
        SET subject_user_account_id = t.user_account_id
        FROM cases c
        JOIN transactions t ON t.id = c.transaction_id
        WHERE ar.case_id = c.id
          AND ar.subject_user_account_id IS NULL
          AND t.user_account_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_aml_reports_tenant_subject", table_name="aml_reports")
    op.drop_column("aml_reports", "subject_user_account_id")
