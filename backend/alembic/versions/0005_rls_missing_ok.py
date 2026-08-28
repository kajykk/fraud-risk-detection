"""RLS 策略加固：current_setting 统一 missing_ok。

问题（D04 §9.4 / ADR-015 复核）：
- 0001/0002 的 tenant_isolation 策略使用 current_setting('app.tenant_id')
  （无 missing_ok 标志）。FORCE ROW LEVEL SECURITY 下，凡未执行
  SET app.tenant_id 的会话查询受保护表（api_key_lookup 认证路径、
  seed 脚本、运维任务等），策略求值即抛
  "unrecognized configuration parameter: app.tenant_id"。

方案：
- 统一替换为 current_setting('app.tenant_id', true)：
  * 未设置租户上下文 → 条件求值为 NULL → 行不可见（fail-closed），不再抛错；
  * 已设置租户上下文 → 与原策略行为完全一致；
- 全局表（rules / model_versions，tenant_id 可空）保留 `OR tenant_id IS NULL` 分支。

注：rule_versions 维持严格租户隔离不变（当前 API 无全局规则创建路径，
其版本行始终归属创建租户）。

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None

# 与 0001._RLS_TABLES 一致 + 0002 的 users
_RLS_TABLES = [
    "merchants",
    "api_keys",
    "transactions",
    "scores",
    "shap_explanations",
    "cases",
    "case_events",
    "appeals",
    "rules",
    "rule_versions",
    "model_versions",
    "drift_alerts",
    "aml_reports",
    "sanction_screenings",
    "consent_records",
    "deletion_requests",
    "fairness_reports",
    "audit_logs",
    "users",
]

# tenant_id 可空的"全局表"（策略含 NULL 分支）
_GLOBAL_TABLES = {"rules", "model_versions"}


def _policy_clause(table: str) -> str:
    if table in _GLOBAL_TABLES:
        return (
            "(tenant_id = current_setting('app.tenant_id', true)::uuid "
            "OR tenant_id IS NULL)"
        )
    return "tenant_id = current_setting('app.tenant_id', true)::uuid"


def _drop_policy(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")


def _create_policy(table: str, *, missing_ok: bool) -> None:
    if missing_ok:
        clause = _policy_clause(table)
    else:
        if table in _GLOBAL_TABLES:
            clause = (
                "(tenant_id = current_setting('app.tenant_id')::uuid "
                "OR tenant_id IS NULL)"
            )
        else:
            clause = "tenant_id = current_setting('app.tenant_id')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"FOR ALL USING ({clause}) WITH CHECK ({clause});"
    )


def upgrade() -> None:
    # 每张表的 DROP+CREATE 包在独立语句序列中；DDL 无事务性要求，
    # 策略重建为原子语义（同事务内先删后建由 alembic 连接执行）
    for table in _RLS_TABLES:
        _drop_policy(table)
        _create_policy(table, missing_ok=True)


def downgrade() -> None:
    # 回滚到 0001-0004 的原始严格策略（无 missing_ok）
    for table in _RLS_TABLES:
        _drop_policy(table)
        _create_policy(table, missing_ok=False)
