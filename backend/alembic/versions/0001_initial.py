"""FRD initial schema: tenants / merchants / api_keys / transactions / scores /
shap_explanations / cases / case_events / appeals / rules / rule_versions /
model_versions / drift_alerts / aml_reports / sanction_screenings /
consent_records / deletion_requests / fairness_reports / audit_logs

依据：
- D04 V1.1 数据库设计
- FRD-BASELINE-V1.1 §3 统一枚举字典、§4 字段映射表
- ADR-015 多租户 RLS 强制隔离

Revision ID: 0001
Revises:
Create Date: 2026-07-27 08:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# RLS 业务表清单（含 tenant_id，需启用 RLS + 创建 tenant_isolation 策略）
# 注：rules / model_versions 的 tenant_id 可空（全局规则/模型），策略需包含 NULL 判断
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
]


def _enable_rls(table: str, allow_null_tenant: bool = False) -> None:
    """启用 RLS 并创建 tenant_isolation 策略。

    Args:
        table: 表名
        allow_null_tenant: True 时策略包含 tenant_id IS NULL（全局规则/模型）
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    using_clause = (
        f"tenant_id = current_setting('app.tenant_id')::uuid OR tenant_id IS NULL"
        if allow_null_tenant
        else f"tenant_id = current_setting('app.tenant_id')::uuid"
    )
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"FOR ALL USING ({using_clause}) "
        f"WITH CHECK ({using_clause});"
    )


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. tenants（自身即租户，不含 tenant_id，不启用 RLS）
    # ------------------------------------------------------------------ #
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="BANK"),
        sa.Column("plan", sa.String(20), nullable=False, server_default="STANDARD"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("encryption_key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("pci_scope", sa.String(20), nullable=False, server_default="CDE"),
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
    op.create_index("ix_tenants_code", "tenants", ["code"], unique=True)

    # ------------------------------------------------------------------ #
    # 2. merchants
    # ------------------------------------------------------------------ #
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_no", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("industry", sa.String(50), nullable=True),
        sa.Column("size", sa.String(20), nullable=True),
        sa.Column("contact_name", sa.String(100), nullable=True),
        sa.Column("contact_phone_encrypted", sa.Text, nullable=True),
        sa.Column("webhook_url", sa.Text, nullable=True),
        sa.Column("webhook_secret", sa.Text, nullable=True),
        sa.Column("ip_whitelist", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("rate_limit_qps", sa.Integer, nullable=False, server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("risk_profile", postgresql.JSONB, nullable=False, server_default="{}"),
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
    op.create_index("ix_merchants_tenant_id", "merchants", ["tenant_id"])
    op.create_index(
        "ix_merchants_tenant_merchant_no",
        "merchants",
        ["tenant_id", "merchant_no"],
        unique=True,
    )

    # ------------------------------------------------------------------ #
    # 3. api_keys
    # ------------------------------------------------------------------ #
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(10), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("ip_whitelist", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_merchant_id", "api_keys", ["merchant_id"])

    # ------------------------------------------------------------------ #
    # 4. transactions（D04 §3.2 / 基准 §4.1）
    # ------------------------------------------------------------------ #
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_tx_id", sa.String(100), nullable=False),
        sa.Column("card_token", sa.String(64), nullable=False),
        sa.Column("card_bin", sa.String(6), nullable=False),
        sa.Column("card_last4", sa.String(4), nullable=False),
        sa.Column("amount", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("tx_type", sa.String(20), nullable=True),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("is_3ds_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("merchant_city", sa.String(50), nullable=True),
        sa.Column("merchant_category", sa.String(10), nullable=True),
        sa.Column("device_fingerprint", sa.String(64), nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("user_account_id", sa.String(100), nullable=True),
        sa.Column("note_text", sa.Text, nullable=True),
        sa.Column("risk_features", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("parent_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])
    op.create_index(
        "ix_transactions_tenant_external_tx_id",
        "transactions",
        ["tenant_id", "external_tx_id"],
        unique=True,
    )
    op.create_index("ix_transactions_user_account_id", "transactions", ["user_account_id"])
    op.create_index("ix_transactions_occurred_at", "transactions", ["occurred_at"])
    op.create_index(
        "ix_transactions_tenant_occurred_at",
        "transactions",
        ["tenant_id", "occurred_at"],
    )

    # ------------------------------------------------------------------ #
    # 5. scores（基准 §4.2 risk_score DECIMAL(5,4)）
    # ------------------------------------------------------------------ #
    op.create_table(
        "scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("rule_version", sa.String(50), nullable=False),
        sa.Column("risk_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("risk_band", sa.String(10), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("rule_hits", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("modality_scores", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("feature_values", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("cached", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_scores_tenant_id", "scores", ["tenant_id"])
    op.create_index("ix_scores_transaction_id", "scores", ["transaction_id"])
    op.create_index("ix_scores_tenant_scored_at", "scores", ["tenant_id", "scored_at"])

    # ------------------------------------------------------------------ #
    # 6. shap_explanations
    # ------------------------------------------------------------------ #
    op.create_table(
        "shap_explanations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("factors", postgresql.JSONB, nullable=False),
        sa.Column("base_value", sa.Numeric(10, 6), nullable=False),
        sa.Column("output_value", sa.Numeric(10, 6), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_shap_explanations_tenant_id", "shap_explanations", ["tenant_id"])
    op.create_index("ix_shap_explanations_score_id", "shap_explanations", ["score_id"])

    # ------------------------------------------------------------------ #
    # 7. cases（基准 §3.7 case.level P0-P3）
    # ------------------------------------------------------------------ #
    op.create_table(
        "cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_no", sa.String(50), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("escalated_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("chargeback_id", sa.String(100), nullable=True),
        sa.Column("graph_summary", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cases_tenant_id", "cases", ["tenant_id"])
    op.create_index("ix_cases_tenant_status", "cases", ["tenant_id", "status"])
    op.create_index("ix_cases_tenant_level", "cases", ["tenant_id", "level"])
    op.create_index("ix_cases_transaction_id", "cases", ["transaction_id"])

    # ------------------------------------------------------------------ #
    # 8. case_events
    # ------------------------------------------------------------------ #
    op.create_table(
        "case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_case_events_tenant_id", "case_events", ["tenant_id"])
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])

    # ------------------------------------------------------------------ #
    # 9. appeals（基准 §3.10 appeal_status 4 值）
    # ------------------------------------------------------------------ #
    op.create_table(
        "appeals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appellant_type", sa.String(20), nullable=False),
        sa.Column("appellant_id", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("llm_analysis", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_appeals_tenant_id", "appeals", ["tenant_id"])
    op.create_index("ix_appeals_case_id", "appeals", ["case_id"])
    op.create_index("ix_appeals_tenant_status", "appeals", ["tenant_id", "status"])

    # ------------------------------------------------------------------ #
    # 10. rules（tenant_id 可空：全局规则）
    # ------------------------------------------------------------------ #
    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("expression", sa.Text, nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="50"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("current_version", sa.String(20), nullable=False, server_default="v1"),
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
    op.create_index("ix_rules_tenant_id", "rules", ["tenant_id"])
    op.create_index(
        "ix_rules_tenant_rule_id",
        "rules",
        ["tenant_id", "rule_id"],
        unique=True,
    )
    op.create_index("ix_rules_tenant_priority", "rules", ["tenant_id", "priority"])

    # ------------------------------------------------------------------ #
    # 11. rule_versions（V1.1 Major：强制 tenant_id 非空）
    # ------------------------------------------------------------------ #
    op.create_table(
        "rule_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("expression", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("canary_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rule_versions_tenant_id", "rule_versions", ["tenant_id"])
    op.create_index(
        "ix_rule_versions_rule_id_version",
        "rule_versions",
        ["rule_id", "version"],
        unique=True,
    )
    op.create_index("ix_rule_versions_status", "rule_versions", ["status"])

    # ------------------------------------------------------------------ #
    # 12. model_versions（tenant_id 可空：全局模型）
    # ------------------------------------------------------------------ #
    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_type", sa.String(30), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="REGISTERED"),
        sa.Column("metrics", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("training_data_hash", sa.String(64), nullable=False),
        sa.Column("feature_names", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("artifacts_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("canary_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("canary_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_hours", sa.Integer, nullable=False, server_default="168"),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_model_versions_tenant_id", "model_versions", ["tenant_id"])
    op.create_index(
        "ix_model_versions_tenant_version",
        "model_versions",
        ["tenant_id", "version"],
        unique=True,
    )
    op.create_index("ix_model_versions_status", "model_versions", ["status"])

    # ------------------------------------------------------------------ #
    # 13. drift_alerts（基准 §3.12）
    # ------------------------------------------------------------------ #
    op.create_table(
        "drift_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("modality", sa.String(20), nullable=False),
        sa.Column("metric_type", sa.String(10), nullable=False),
        sa.Column("metric_value", sa.Numeric(10, 4), nullable=False),
        sa.Column("threshold", sa.Numeric(10, 4), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_drift_alerts_tenant_id", "drift_alerts", ["tenant_id"])
    op.create_index(
        "ix_drift_alerts_model_severity",
        "drift_alerts",
        ["model_version", "severity"],
    )

    # ------------------------------------------------------------------ #
    # 14. aml_reports（基准 §3.9）
    # ------------------------------------------------------------------ #
    op.create_table(
        "aml_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(20), nullable=False),
        sa.Column("report_no", sa.String(50), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.BigInteger, nullable=False),
        sa.Column("content_xml", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_to", sa.String(50), nullable=True),
        sa.Column("submission_receipt", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_aml_reports_tenant_id", "aml_reports", ["tenant_id"])
    op.create_index(
        "ix_aml_reports_tenant_status",
        "aml_reports",
        ["tenant_id", "status"],
    )
    op.create_index("ix_aml_reports_transaction_id", "aml_reports", ["transaction_id"])

    # ------------------------------------------------------------------ #
    # 15. sanction_screenings
    # ------------------------------------------------------------------ #
    op.create_table(
        "sanction_screenings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("entity_id_hash", sa.String(64), nullable=False),
        sa.Column("list_source", sa.String(50), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("matched_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "screened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sanction_screenings_tenant_id", "sanction_screenings", ["tenant_id"])
    op.create_index(
        "ix_sanction_screenings_entity_id_hash",
        "sanction_screenings",
        ["entity_id_hash"],
    )

    # ------------------------------------------------------------------ #
    # 16. consent_records（基准 §3.11）
    # ------------------------------------------------------------------ #
    op.create_table(
        "consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("consent_type", sa.String(30), nullable=False),
        sa.Column("consent_status", sa.String(20), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("legal_basis", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_consent_records_tenant_id", "consent_records", ["tenant_id"])
    op.create_index(
        "ix_consent_records_tenant_user",
        "consent_records",
        ["tenant_id", "user_id"],
    )
    op.create_index(
        "ix_consent_records_tenant_status",
        "consent_records",
        ["tenant_id", "consent_status"],
    )

    # ------------------------------------------------------------------ #
    # 17. deletion_requests
    # ------------------------------------------------------------------ #
    op.create_table(
        "deletion_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verification_method", sa.String(30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_deletion_requests_tenant_id", "deletion_requests", ["tenant_id"])
    op.create_index(
        "ix_deletion_requests_tenant_status",
        "deletion_requests",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_deletion_requests_tenant_user",
        "deletion_requests",
        ["tenant_id", "user_id"],
    )

    # ------------------------------------------------------------------ #
    # 18. fairness_reports（PIPL §24 自动化决策公平性）
    # ------------------------------------------------------------------ #
    op.create_table(
        "fairness_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("report_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("protected_attribute", sa.String(20), nullable=False),
        sa.Column("group_count", sa.Integer, nullable=False),
        sa.Column("selection_rate", sa.Numeric(10, 6), nullable=False),
        sa.Column("disparate_impact_ratio", sa.Numeric(10, 6), nullable=False),
        sa.Column("threshold", sa.Numeric(5, 4), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("threshold >= 0.8", name="ck_fairness_reports_threshold_min"),
        sa.CheckConstraint(
            "disparate_impact_ratio >= 0", name="ck_fairness_reports_dir_nonneg"
        ),
    )
    op.create_index("ix_fairness_reports_tenant_id", "fairness_reports", ["tenant_id"])
    op.create_index(
        "ix_fairness_reports_model_version",
        "fairness_reports",
        ["model_version"],
    )

    # ------------------------------------------------------------------ #
    # 19. audit_logs（D04 §3.7，含 sequence_no + 哈希链）
    # ------------------------------------------------------------------ #
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.BigInteger, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_value", postgresql.JSONB, nullable=True),
        sa.Column("after_value", postgresql.JSONB, nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("current_hash", sa.String(64), nullable=False),
        sa.Column("cde_zone", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index(
        "ix_audit_logs_tenant_sequence",
        "audit_logs",
        ["tenant_id", "sequence_no"],
        unique=True,
    )
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ------------------------------------------------------------------ #
    # 启用 RLS（ADR-015）
    # ------------------------------------------------------------------ #
    for table in _RLS_TABLES:
        allow_null = table in ("rules", "model_versions")
        _enable_rls(table, allow_null_tenant=allow_null)


def downgrade() -> None:
    """回滚：按反向顺序 drop 所有表。"""
    # 先 drop RLS 策略与表
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.drop_table(table)
    op.drop_table("tenants")
