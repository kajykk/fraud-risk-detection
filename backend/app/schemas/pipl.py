"""PIPL schemas（D05 §13）。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConsentTypeEnum(str, Enum):
    EXPLICIT = "EXPLICIT"
    IMPLICIT_BY_ACTION = "IMPLICIT_BY_ACTION"


class ConsentPurpose(str, Enum):
    """同意用途（基准 §3.11）。"""

    TRANSACTION_SCORING = "TRANSACTION_SCORING"
    FRAUD_DETECTION = "FRAUD_DETECTION"
    AML_REPORT = "AML_REPORT"
    MARKETING = "MARKETING"
    RESEARCH = "RESEARCH"


class ConsentStatus(str, Enum):
    """同意状态（基准 §3.11）。"""

    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class LegalBasis(str, Enum):
    CONSENT = "CONSENT"
    CONTRACT = "CONTRACT"
    LEGAL_OBLIGATION = "LEGAL_OBLIGATION"
    VITAL_INTEREST = "VITAL_INTEREST"
    PUBLIC_TASK = "PUBLIC_TASK"
    LEGITIMATE_INTEREST = "LEGITIMATE_INTEREST"


class ConsentCreate(BaseModel):
    """POST /pipl/consent 请求体（D05 §13.1）。"""

    user_id: str
    verification_token: str
    consent_type: ConsentTypeEnum
    purpose: ConsentPurpose
    legal_basis: LegalBasis
    scope: list[str]
    policy_version: str
    expires_at: datetime | None = None
    evidence: dict[str, Any]


class ConsentOut(BaseModel):
    """同意记录详情。"""

    consent_id: str
    user_id: str
    status: ConsentStatus
    purpose: ConsentPurpose
    legal_basis: LegalBasis
    consent_type: ConsentTypeEnum
    scope: list[str] = Field(default_factory=list)
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    withdrawn_at: datetime | None = None
    policy_version: str
    evidence_ref: str | None = None


class ConsentWithdraw(BaseModel):
    """POST /pipl/consent/withdraw 请求体（D05 §13.2）。"""

    user_id: str
    verification_token: str
    consent_id: str
    withdrawal_reason: str | None = None
    effective_immediately: bool = True


class DataExportRequest(BaseModel):
    """GET /pipl/data-export 请求参数（D05 §13.4）。"""

    user_id: str
    verification_token: str
    scope: str
    format: str = "JSON"
    start_date: str | None = None
    end_date: str | None = None
    delivery_method: str = "OSS_PRESIGNED_URL"


class DataExportStatusOut(BaseModel):
    """GET /pipl/data-export/{task_id}/status 响应（D05 §13.5）。"""

    task_id: str
    user_id: str
    status: str
    scope: list[str] = Field(default_factory=list)
    format: str = "JSON"
    download_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class DeletionRequestIn(BaseModel):
    """POST /pipl/deletion 请求体（D05 §13.6）。"""

    user_id: str
    verification_token: str
    scope: list[str]
    reason: str
    retain_for_aml: bool = True
    legal_hold_review: bool = True


class DeletionStatusOut(BaseModel):
    """GET /pipl/deletion/{request_id}/status 响应（D05 §13.7）。"""

    request_id: str
    user_id: str
    status: str
    scope: list[str] = Field(default_factory=list)
    deleted_count: int = 0
    anonymized_count: int = 0
    retained_count: int = 0
    retention_reason: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class RectificationItem(BaseModel):
    """更正项。"""

    resource_type: str
    resource_id: str
    field: str
    current_value: Any
    corrected_value: Any
    evidence: str


class RectificationRequest(BaseModel):
    """POST /pipl/rectification 请求体（D05 §13.8）。"""

    user_id: str
    verification_token: str
    corrections: list[RectificationItem]
    reason: str


class RectificationStatusOut(BaseModel):
    """更正请求状态。"""

    request_id: str
    user_id: str
    status: str
    correction_count: int
    estimated_seconds: int = 120


__all__ = [
    "ConsentCreate",
    "ConsentOut",
    "ConsentStatus",
    "ConsentTypeEnum",
    "ConsentPurpose",
    "ConsentWithdraw",
    "DataExportRequest",
    "DataExportStatusOut",
    "DeletionRequestIn",
    "DeletionStatusOut",
    "LegalBasis",
    "RectificationItem",
    "RectificationRequest",
    "RectificationStatusOut",
]
