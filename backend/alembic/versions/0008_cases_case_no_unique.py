"""cases.case_no 唯一约束（业务编号防碰撞静默重复）。

问题：case_no 由日期 + 6 位随机数构成（API 侧数字 6 位 / worker 侧 hex 6 位），
表无唯一约束——并发创建时碰撞不报错，产生重复业务编号，
破坏"案件编号可作业务主键"的契约（工单/审计/申诉引用均依赖其唯一性）。

方案：
1. 存量去重：重复 case_no 追加 `-<序号>` 后缀保留；
2. 全局唯一索引（case_no 含日期，全局唯一语义正确）。

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 存量去重：为重复 case_no 追加序号后缀（保留原值可追溯）
    op.execute(
        """
        UPDATE cases c SET case_no = c.case_no || '-' || r.seq
        FROM (
            SELECT id,
                   row_number() OVER (PARTITION BY case_no ORDER BY created_at)::int AS seq
            FROM cases
        ) r
        WHERE c.id = r.id AND r.seq > 1;
        """
    )
    op.create_index("uq_cases_case_no", "cases", ["case_no"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_cases_case_no", table_name="cases")