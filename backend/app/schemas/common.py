"""通用响应/分页/枚举（D05 §2.3 / §2.4）。

统一响应格式：
    { "code": "OK", "message": "...", "data": ..., "request_id": "...",
      "trace_id": "...", "timestamp": "..." }
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


def _utcnow():
    return datetime.now(UTC)


class ErrorCode(str, Enum):
    """业务错误码（D05 §12）。"""

    OK = "OK"
    INVALID_PARAMS = "INVALID_PARAMS"
    INVALID_JSON = "INVALID_JSON"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    SCOPE_INSUFFICIENT = "SCOPE_INSUFFICIENT"
    TENANT_SUSPENDED = "TENANT_SUSPENDED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 规则相关
    RULE_DSL_INVALID = "RULE_DSL_INVALID"
    RULE_NOT_DRAFT = "RULE_NOT_DRAFT"
    RULE_NOT_DELETABLE = "RULE_NOT_DELETABLE"
    RULE_STATUS_TRANSITION_INVALID = "RULE_STATUS_TRANSITION_INVALID"
    APPROVER_REQUIRED = "APPROVER_REQUIRED"
    CANARY_THRESHOLD_NOT_MET = "CANARY_THRESHOLD_NOT_MET"
    NO_ROLLBACK_TARGET = "NO_ROLLBACK_TARGET"
    TARGET_VERSION_NOT_FOUND = "TARGET_VERSION_NOT_FOUND"
    # 模型相关
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    MODEL_ARTIFACTS_HASH_MISMATCH = "MODEL_ARTIFACTS_HASH_MISMATCH"
    MODEL_VERSION_EXISTS = "MODEL_VERSION_EXISTS"
    MODEL_METRICS_INSUFFICIENT = "MODEL_METRICS_INSUFFICIENT"
    MODEL_HAS_TRAFFIC = "MODEL_HAS_TRAFFIC"
    MODEL_NOT_DELETABLE = "MODEL_NOT_DELETABLE"
    MODEL_NOT_EDITABLE = "MODEL_NOT_EDITABLE"
    ARTIFACTS_HASH_IMMUTABLE = "ARTIFACTS_HASH_IMMUTABLE"
    # SHAP 相关
    SHAP_NOT_READY = "SHAP_NOT_READY"
    SHAP_EXPIRED = "SHAP_EXPIRED"
    SHAP_COMPUTATION_FAILED = "SHAP_COMPUTATION_FAILED"
    # PIPL 相关
    SUBJECT_NOT_VERIFIED = "SUBJECT_NOT_VERIFIED"
    SUBJECT_NOT_FOUND = "SUBJECT_NOT_FOUND"
    LEGAL_HOLD_CONFLICT = "LEGAL_HOLD_CONFLICT"
    CONSENT_ALREADY_GRANTED = "CONSENT_ALREADY_GRANTED"
    CONSENT_NOT_FOUND = "CONSENT_NOT_FOUND"
    CONSENT_ALREADY_WITHDRAWN = "CONSENT_ALREADY_WITHDRAWN"
    POLICY_VERSION_OUTDATED = "POLICY_VERSION_OUTDATED"
    RECTIFICATION_NOT_ALLOWED = "RECTIFICATION_NOT_ALLOWED"


class RiskBand(str, Enum):
    """风险等级（基准 §3.5）。"""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Decision(str, Enum):
    """决策枚举（基准 §3.1）。"""

    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    DENY = "DENY"
    CHALLENGE = "CHALLENGE"


class CaseStatus(str, Enum):
    """案件状态（基准 §3.2）。"""

    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"
    FALSE_ALARM = "FALSE_ALARM"


class ModelStatus(str, Enum):
    """模型状态（基准 §3.3）。"""

    REGISTERED = "REGISTERED"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RuleStatus(str, Enum):
    """规则版本状态（基准 §3.4）。"""

    DRAFT = "DRAFT"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RuleAction(str, Enum):
    """规则动作（基准 §3.4，2 值，区别于 decision 4 值）。"""

    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应格式（D05 §2.3）。"""

    code: str = ErrorCode.OK.value
    message: str = "success"
    data: T | None = None
    request_id: str | None = None
    trace_id: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)


class PageMeta(BaseModel):
    """分页元信息（D05 §2.4）。"""

    page: int = 1
    page_size: int = 20
    total: int = 0


class PageResponse(BaseModel, Generic[T]):
    """分页响应（D05 §2.4）。"""

    items: list[T]
    page: int = 1
    page_size: int = 20
    total: int = 0


class HealthStatus(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
    version: str = "1.1.0"
    checks: dict[str, str] = Field(default_factory=dict)


__all__ = [
    "ApiResponse",
    "CaseStatus",
    "Decision",
    "ErrorCode",
    "HealthStatus",
    "ModelStatus",
    "PageMeta",
    "PageResponse",
    "RiskBand",
    "RuleAction",
    "RuleStatus",
]
