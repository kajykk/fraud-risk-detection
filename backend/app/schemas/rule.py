"""规则 schemas（D05 §5）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import RuleAction, RuleStatus


class RuleCreate(BaseModel):
    """POST /rules 请求体（D05 §5.2）。"""

    name: str
    description: str | None = None
    dsl: str
    severity: str = "WARN"
    action: str = "REVIEW"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)


class RuleUpdate(BaseModel):
    """PUT /rules/{rule_id} 请求体（D05 §5.4）。"""

    name: str | None = None
    description: str | None = None
    dsl: str | None = None
    severity: str | None = None
    action: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scope: dict[str, Any] | None = None


class RuleOut(BaseModel):
    """规则详情。"""

    id: str
    rule_id: str
    name: str
    description: str | None = None
    dsl: str
    severity: str
    action: str
    status: RuleStatus
    version: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    hit_count_24h: int = 0
    false_positive_rate: float = 0.0
    created_at: datetime
    updated_at: datetime


class RuleVersionCreate(BaseModel):
    """POST /rules/{rule_id}/versions 请求体（D05 §5.6）。"""

    dsl: str
    change_summary: str | None = None
    severity: str | None = None
    action: str | None = None


class RuleVersionOut(BaseModel):
    """规则版本。"""

    id: str
    rule_id: str
    version: str
    dsl: str
    status: RuleStatus
    canary_percent: int = 0
    created_by: str
    created_at: datetime
    promoted_at: datetime | None = None


class RulePromoteRequest(BaseModel):
    """POST /rules/{rule_id}/promote 请求体（D05 §5.7）。"""

    from_status: RuleStatus
    to_status: RuleStatus
    canary_percentage: int | None = None
    approver_id: str
    observation_hours: int | None = None
    rollback_thresholds: dict[str, Any] | None = None


class RuleRollbackRequest(BaseModel):
    """POST /rules/{rule_id}/rollback 请求体（D05 §5.8）。"""

    target_version: int | None = None
    reason: str
    approver_id: str


__all__ = [
    "RuleCreate",
    "RuleOut",
    "RulePromoteRequest",
    "RuleRollbackRequest",
    "RuleUpdate",
    "RuleVersionCreate",
    "RuleVersionOut",
]
