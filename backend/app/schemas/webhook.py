"""Webhook schemas（D05 §11）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.webhook import validate_webhook_secret, validate_webhook_url


class WebhookCreate(BaseModel):
    """POST /webhooks 请求体（D05 §11.1）。

    merchant_id 显式指定配置写入的目标商户行；缺失/非法由端点
    返回 400（INVALID_PARAMS），不走 Pydantic 必填（避免 422 语义）。
    """

    merchant_id: str | None = None
    url: str
    events: list[str]
    secret: str
    challenge_expected: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_webhook_url(v)

    @field_validator("secret")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        return validate_webhook_secret(v)


class WebhookUpdate(BaseModel):
    """PUT /webhooks/{id} 请求体（D05 §11.4）。

    merchant_id 必须与路径 {id} 一致（缺失/不一致端点返回 400）。
    secret 可选：省略时保留原签名密钥（仅改 URL/事件无需重输 secret）。
    """

    merchant_id: str | None = None
    url: str
    events: list[str]
    secret: str | None = None
    challenge_expected: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_webhook_url(v)

    @field_validator("secret")
    @classmethod
    def _check_secret(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_webhook_secret(v)


class WebhookOut(BaseModel):
    """Webhook 详情。"""

    id: str
    url: str
    events: list[str] = Field(default_factory=list)
    status: str = "PENDING_VERIFICATION"
    secret_hash: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    last_delivery_at: datetime | None = None
    last_delivery_status: str | None = None
    challenge_id: str | None = None


class WebhookTestRequest(BaseModel):
    """POST /webhooks/{id}/test 请求体（D05 §11.6）。"""

    event_type: str
    test_payload: dict[str, Any] | None = None


class WebhookTestResponse(BaseModel):
    """POST /webhooks/{id}/test 响应。"""

    delivery_id: str
    webhook_id: str
    event_type: str
    status: str = "PENDING"
    signature_header: str


class DeliveryAttempt(BaseModel):
    """投递尝试记录。"""

    attempt_no: int
    sent_at: datetime
    response_code: int | None = None
    response_body_snippet: str | None = None
    latency_ms: int | None = None
    next_retry_at: datetime | None = None


class WebhookDeliveryOut(BaseModel):
    """投递记录（D05 §11.7）。"""

    delivery_id: str
    event_id: str
    event_type: str
    webhook_id: str
    status: str
    is_test: bool = False
    attempts: list[DeliveryAttempt] = Field(default_factory=list)
    delivered_at: datetime | None = None
    dead_lettered_at: datetime | None = None
    dead_letter_reason: str | None = None


__all__ = [
    "DeliveryAttempt",
    "WebhookCreate",
    "WebhookDeliveryOut",
    "WebhookOut",
    "WebhookTestRequest",
    "WebhookTestResponse",
    "WebhookUpdate",
]
