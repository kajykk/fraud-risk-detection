"""Webhook 路由（D05 §11）。

CRUD + /test + /deliveries。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdate,
)

router = APIRouter()


@router.post("", response_model=ApiResponse[WebhookOut])
async def create_webhook(
    req: WebhookCreate,
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """注册 Webhook（含 challenge 验证）。"""
    # TODO: 写 merchants.webhook_url + 触发 challenge
    return ApiResponse(data=WebhookOut(id="wh_TODO", url=req.url, events=req.events, status="PENDING_VERIFICATION", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.get("", response_model=ApiResponse[PageResponse[WebhookOut]])
async def list_webhooks(
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[PageResponse[WebhookOut]]:
    """分页查询 Webhook 列表。"""
    return ApiResponse(data=PageResponse(items=[], total=0))


@router.get("/{webhook_id}", response_model=ApiResponse[WebhookOut])
async def get_webhook(
    webhook_id: str,
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """查询 Webhook 详情。"""
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"webhook not found: {webhook_id}")


@router.put("/{webhook_id}", response_model=ApiResponse[WebhookOut])
async def update_webhook(
    webhook_id: str,
    req: WebhookUpdate,
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """更新 Webhook（URL 变更需重新 challenge）。"""
    return ApiResponse(data=WebhookOut(id=webhook_id, url=req.url, events=req.events, status="PENDING_VERIFICATION", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    _user: dict = Depends(require_scope("webhook:write")),
) -> None:
    """注销 Webhook（软删除，30 天保留期）。"""
    return None


@router.post("/{webhook_id}/test", response_model=ApiResponse[WebhookTestResponse])
async def test_webhook(
    webhook_id: str,
    req: WebhookTestRequest,
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookTestResponse]:
    """手动触发测试事件投递。"""
    # TODO: 调用 webhook_service.deliver
    return ApiResponse(data=WebhookTestResponse(delivery_id="dlv_TODO", webhook_id=webhook_id, event_type=req.event_type, status="PENDING", signature_header="t=0,v1=TODO"))


@router.get("/{webhook_id}/deliveries", response_model=ApiResponse[PageResponse[WebhookDeliveryOut]])
async def list_deliveries(
    webhook_id: str,
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[PageResponse[WebhookDeliveryOut]]:
    """查询 Webhook 投递记录。"""
    return ApiResponse(data=PageResponse(items=[], total=0))
