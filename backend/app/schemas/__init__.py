"""Pydantic schemas（按 D05 V1.1）。

模块组织：common / auth / transaction / score / case / rule / model_version / pipl / webhook
"""

from app.schemas.auth import Token, TokenRequest
from app.schemas.case import CaseCreate, CaseEventOut, CaseOut, CaseUpdate
from app.schemas.common import ApiResponse, ErrorCode, PageMeta, PageResponse, RiskBand
from app.schemas.model_version import (
    ModelCanaryRequest,
    ModelOut,
    ModelPromoteRequest,
    ModelRegisterRequest,
    ModelRollbackRequest,
    ModelRetireRequest,
)
from app.schemas.pipl import (
    ConsentCreate,
    ConsentOut,
    ConsentWithdraw,
    DataExportRequest,
    DeletionRequestIn,
    DeletionStatusOut,
    RectificationRequest,
)
from app.schemas.rule import (
    RuleCreate,
    RuleOut,
    RulePromoteRequest,
    RuleRollbackRequest,
    RuleVersionCreate,
    RuleVersionOut,
)
from app.schemas.score import ShapResult, ShapStatus, ShapTriggerRequest
from app.schemas.transaction import TransactionScoreRequest, TransactionScoreResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookTestRequest,
    WebhookUpdate,
)

__all__ = [
    "ApiResponse",
    "CaseCreate",
    "CaseEventOut",
    "CaseOut",
    "CaseUpdate",
    "ConsentCreate",
    "ConsentOut",
    "ConsentWithdraw",
    "DataExportRequest",
    "DeletionRequestIn",
    "DeletionStatusOut",
    "ErrorCode",
    "ModelCanaryRequest",
    "ModelOut",
    "ModelPromoteRequest",
    "ModelRegisterRequest",
    "ModelRollbackRequest",
    "ModelRetireRequest",
    "PageMeta",
    "PageResponse",
    "RectificationRequest",
    "RiskBand",
    "RuleCreate",
    "RuleOut",
    "RulePromoteRequest",
    "RuleRollbackRequest",
    "RuleVersionCreate",
    "RuleVersionOut",
    "ShapResult",
    "ShapStatus",
    "ShapTriggerRequest",
    "Token",
    "TokenRequest",
    "TransactionScoreRequest",
    "TransactionScoreResponse",
    "WebhookCreate",
    "WebhookDeliveryOut",
    "WebhookOut",
    "WebhookTestRequest",
    "WebhookUpdate",
]
