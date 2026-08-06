"""rules.rule_id 唯一约束（防跨租户规则号碰撞越权）。

问题：rule_id 各租户独立从 R0001 递增，但无唯一约束。结合旧版 _load_rule
的 `tenant_id = X OR tenant_id IS NULL` 匹配，跨租户 rule_id 碰撞时可能命中
他租户/全局规则（H7 伴生项）。

方案：对 rules 建 (tenant_id, rule_id) 唯一索引。
说明：SQLAlchemy UniqueConstraint 对 NULL 不生效，因此附加创建
partial unique index（`WHERE tenant_id IS NOT NULL`）兜底租户内唯一。
PostgreSQL 的 UNIQUE 对 NULL 视为不同行，故分开处理：
- 非空租户：唯一由 partial index 保证
- 空租户（全局规则，仅运维写入）：放开限制
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 非全局规则（tenant_id IS NOT NULL）：(tenant_id, rule_id) 唯一
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rules_tenant_rule_id "
        "ON rules (tenant_id, rule_id) WHERE tenant_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_rules_tenant_rule_id;")