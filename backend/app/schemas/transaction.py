"""交易 schemas（D05 §4）。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import Decision, RiskBand


class TxType(StrEnum):
    """交易类型（基准 §3.8）。"""

    PURCHASE = "PURCHASE"
    WITHDRAW = "WITHDRAW"
    REFUND = "REFUND"
    TRANSFER = "TRANSFER"
    TOPUP = "TOPUP"
    PAYMENT = "PAYMENT"


class Channel(StrEnum):
    """渠道（基准 §3.8）。"""

    WEB = "WEB"
    APP = "APP"
    POS = "POS"
    API = "API"
    QR = "QR"


class TransactionScoreRequest(BaseModel):
    """POST /transactions/score 请求体（D05 §4.1）。

    金额单位：分（int64），必须 > 0。
    card_token 为 Tokenization 后的 Token，不能传 PAN。
    """

    external_tx_id: str = Field(..., description="外部交易号，唯一")
    tx_type: TxType
    amount: int = Field(..., gt=0, description="金额（分）")
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    occurred_at: datetime
    card_token: str
    card_bin: str = Field(..., min_length=6, max_length=6)
    card_last4: str = Field(..., min_length=4, max_length=4)
    merchant_id: str | None = None
    mcc: str | None = None
    merchant_category: str | None = None
    acquirer_id: str | None = None
    device_fingerprint_hash: str | None = None
    ip_address: str | None = None
    ip_geo: dict[str, Any] | None = None
    user_id: str
    user_account_id: str | None = None
    user_created_at: datetime | None = None
    channel: Channel | None = None
    is_3ds_verified: bool = False
    merchant_city: str | None = None
    shipping_country: str | None = Field(default=None, min_length=2, max_length=2)
    billing_country: str | None = Field(default=None, min_length=2, max_length=2)
    note_text: str | None = None
    metadata: dict[str, Any] | None = None
    # 异步深度分析
    analysis_depth: str | None = Field(default="STANDARD", description="STANDARD / DEEP")


class Explainability(BaseModel):
    """评分可解释性。"""

    model_contribution: float = 0.0
    rule_contribution: float = 0.0
    shap_status: str = "PENDING"
    shap_task_id: str | None = None


class RuleHit(BaseModel):
    """命中规则。"""

    rule_id: str
    rule_name: str | None = None
    severity: str | None = None


class TransactionScoreResponse(BaseModel):
    """POST /transactions/score 响应（D05 §4.1）。"""

    decision: Decision
    risk_score: float = Field(..., ge=0.0, le=1.0, description="0.0000-1.0000")
    risk_band: RiskBand
    model_version: str
    rule_hits: list[RuleHit] = Field(default_factory=list)
    explainability: Explainability = Field(default_factory=Explainability)
    latency_ms: int
    case_id: str | None = None
    decision_id: str


class TransactionDetail(BaseModel):
    """GET /transactions/{external_tx_id} 响应（D05 §4.6）。"""

    external_tx_id: str
    decision: Decision
    risk_score: float
    risk_band: RiskBand
    model_version: str
    rule_hits: list[RuleHit] = Field(default_factory=list)
    explainability: Explainability = Field(default_factory=Explainability)
    tx_type: TxType | None = None
    channel: Channel | None = None
    is_3ds_verified: bool = False
    user_created_at: datetime | None = None
    acquirer_id: str | None = None
    shipping_country: str | None = None
    billing_country: str | None = None
    case_id: str | None = None
    decision_id: str
    created_at: datetime


class AsyncScoreResponse(BaseModel):
    """POST /transactions/score/async 响应（D05 §4.2）。"""

    task_id: str
    status: str = "RUNNING"
    estimated_seconds: int = 30
    callback_event: str = "transaction.analysis_completed"


class BatchScoreRequest(BaseModel):
    """POST /transactions/score/batch 请求体（D05 §4.4）。"""

    transactions: list[TransactionScoreRequest] = Field(..., max_length=100)


class BatchScoreResultItem(BaseModel):
    """批量评分单项结果。"""

    external_tx_id: str
    decision: Decision
    risk_score: float
    risk_band: RiskBand
    error: str | None = None


class BatchScoreResponse(BaseModel):
    """批量评分响应。"""

    results: list[BatchScoreResultItem]
    success_count: int
    failure_count: int


class FeedbackRequest(BaseModel):
    """POST /transactions/feedback 请求体（D05 §4.5）。"""

    external_tx_id: str
    label: str = Field(..., description="FRAUD / NOT_FRAUD / SUSPECTED")
    label_source: str
    labeled_at: datetime
    evidence: str | None = None


__all__ = [
    "AsyncScoreResponse",
    "BatchScoreRequest",
    "BatchScoreResponse",
    "BatchScoreResultItem",
    "Channel",
    "Explainability",
    "FeedbackRequest",
    "RuleHit",
    "TransactionDetail",
    "TransactionScoreRequest",
    "TransactionScoreResponse",
    "TxType",
]
