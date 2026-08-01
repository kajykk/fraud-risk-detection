"""SQLAlchemy ORM 模型（按 D04 V1.1）。

模块组织：
- tenant.py: tenants / merchants / api_keys
- transaction.py: transactions / scores / shap_explanations
- case.py: cases / case_events / appeals
- rule.py: rules / rule_versions
- model_version.py: model_versions / drift_alerts
- aml.py: aml_reports / sanction_screenings
- pipl.py: consent_records / deletion_requests / fairness_reports
- audit.py: audit_logs（含 sequence_no）
"""

from app.models.aml import AmlReport, SanctionScreening
from app.models.audit import AuditLog
from app.models.case import Appeal, Case, CaseEvent
from app.models.model_version import DriftAlert, ModelVersion
from app.models.pipl import ConsentRecord, DeletionRequest, FairnessReport
from app.models.rule import Rule, RuleVersion
from app.models.tenant import ApiKey, Merchant, Tenant
from app.models.transaction import Score, ShapExplanation, Transaction
from app.models.user import User

__all__ = [
    "AmlReport",
    "ApiKey",
    "Appeal",
    "AuditLog",
    "Case",
    "CaseEvent",
    "ConsentRecord",
    "DeletionRequest",
    "DriftAlert",
    "FairnessReport",
    "Merchant",
    "ModelVersion",
    "Rule",
    "RuleVersion",
    "SanctionScreening",
    "Score",
    "ShapExplanation",
    "Tenant",
    "Transaction",
    "User",
]
