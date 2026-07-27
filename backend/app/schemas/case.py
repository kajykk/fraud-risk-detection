"""案件 schemas（D05 §8）。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import CaseStatus


class CaseType(str, Enum):
    """案件类型（基准 §3.7）。"""

    FRAUD = "FRAUD"
    AML = "AML"
    CHARGEBACK = "CHARGEBACK"


class CaseLevel(str, Enum):
    """案件等级（基准 §3.7）。"""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseCreate(BaseModel):
    """POST /cases 请求体（D05 §8.2）。"""

    external_tx_id: str
    priority: CaseLevel = CaseLevel.P1
    assignee_id: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class CaseUpdate(BaseModel):
    """PATCH /cases/{case_id} 请求体（D05 §8.4）。"""

    status: CaseStatus | None = None
    assignee_id: str | None = None
    comment: str | None = None


class CaseOut(BaseModel):
    """案件详情。"""

    id: str
    case_no: str
    type: CaseType
    level: CaseLevel
    status: CaseStatus
    transaction_id: str | None = None
    score_id: str | None = None
    assigned_to: str | None = None
    amount: int = 0
    description: str | None = None
    graph_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    confirmed_at: datetime | None = None
    closed_at: datetime | None = None


class CaseEventOut(BaseModel):
    """案件事件。"""

    id: str
    case_id: str
    action: str
    from_status: str | None = None
    to_status: str | None = None
    operator_id: str
    comment: str | None = None
    created_at: datetime


class CaseCloseRequest(BaseModel):
    """POST /cases/{case_id}:close 请求体（D05 §8.6）。"""

    conclusion: str
    loss_amount: int = 0
    recovery_amount: int = 0
    reportable_to_aml: bool = False
    comment: str | None = None


class CommentCreate(BaseModel):
    """POST /cases/{case_id}/comments 请求体。"""

    comment: str


__all__ = [
    "CaseCloseRequest",
    "CaseCreate",
    "CaseEventOut",
    "CaseLevel",
    "CaseOut",
    "CaseType",
    "CaseUpdate",
    "CommentCreate",
]
