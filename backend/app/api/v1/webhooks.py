"""Webhook 路由（D05 §11）。

CRUD + challenge 验证 + /test + /deliveries。

说明：无独立 webhook 表，复用 merchants 表存储 webhook 配置
（webhook_url / webhook_secret(加密) 字段，events/secret_hash/challenge_id 存于 risk_profile）。

安全约束：
- webhook_secret 落库前 Fernet 加密（静态不可读，防 DB 泄露伪造 HMAC）
- 注册时可选 challenge 回显校验：challenge_expected=True 时目标必须
  响应 2xx 且回显 challenge_id，否则保持 PENDING_VERIFICATION
- /test 投递前重新校验 URL（SSRF 纵深防御）
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import NotFoundError
from app.db.session import session_scope
from app.models.tenant import Merchant
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.services.webhook import (
    decrypt_webhook_secret,
    encrypt_webhook_secret,
    validate_webhook_url,
    webhook_service,
)

router = APIRouter()

_TEST_DELIVERY_TIMEOUT_SECONDS = 3.0
_CHALLENGE_TIMEOUT_SECONDS = 3.0


def _secret_hash(secret: str) -> str:
    """计算 secret 的 SHA-256 前 16 位作为展示用哈希。"""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def _merchant_to_out(merchant: Merchant) -> WebhookOut:
    """Merchant ORM → WebhookOut（events/status/challenge_id 从 risk_profile 读取）。"""
    risk_profile = merchant.risk_profile or {}
    status = risk_profile.get("webhook_status")
    if not status:
        status = "ACTIVE" if merchant.webhook_url else merchant.status
    return WebhookOut(
        id=str(merchant.id),
        url=merchant.webhook_url or "",
        events=list(risk_profile.get("webhook_events", [])),
        status=status,
        secret_hash=risk_profile.get("secret_hash"),
        created_at=merchant.created_at,
        updated_at=merchant.updated_at,
        last_delivery_at=risk_profile.get("last_delivery_at"),
        last_delivery_status=risk_profile.get("last_delivery_status"),
        challenge_id=risk_profile.get("challenge_id"),
    )


async def _load_merchant(session, webhook_id: str, tenant_id: str) -> Merchant:
    """按主键加载商户（webhook 配置载体），找不到抛 NotFoundError。"""
    result = await session.execute(
        select(Merchant).where(
            Merchant.id == uuid.UUID(webhook_id),
            Merchant.tenant_id == uuid.UUID(tenant_id),
        )
    )
    merchant = result.scalar_one_or_none()
    if merchant is None:
        raise NotFoundError(f"webhook not found: {webhook_id}")
    return merchant


async def _run_challenge(url: str, challenge_id: str) -> bool:
    """发送 challenge 回调：目标须响应 2xx 且响应体回显 challenge_id。

    通过校验 → True；网络/非 2xx/无回显 → False（保持 PENDING_VERIFICATION）。
    """
    try:
        async with httpx.AsyncClient(timeout=_CHALLENGE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                content=json.dumps({"challenge_id": challenge_id}),
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            return False
        body = response.text or ""
        return challenge_id in body
    except httpx.HTTPError:
        return False


def _set_pending(merchant: Merchant, risk_profile: dict, challenge_id: str) -> None:
    """进入待验证状态。"""
    merchant.status = "PENDING_VERIFICATION"
    risk_profile["webhook_status"] = "PENDING_VERIFICATION"
    risk_profile["challenge_id"] = challenge_id


@router.post("", response_model=ApiResponse[WebhookOut])
async def create_webhook(
    req: WebhookCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """注册 Webhook。

    challenge_expected=True（默认）：发送 challenge 回调，回显通过才 ACTIVE；
    否则保持 PENDING_VERIFICATION 直至 POST /{id}/challenge/verify。
    """
    challenge_id = f"ch_{uuid.uuid4()}"
    verified = False
    if req.challenge_expected:
        verified = await _run_challenge(req.url, challenge_id)

    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(Merchant)
            .where(Merchant.tenant_id == uuid.UUID(tenant_id))
            .order_by(Merchant.created_at.asc())
            .limit(1)
        )
        merchant = result.scalar_one_or_none()
        if merchant is None:
            prefix = req.url.split("//")[-1][:12] or "default"
            merchant = Merchant(
                tenant_id=uuid.UUID(tenant_id),
                merchant_no=f"M{int(time.time())}{uuid.uuid4().hex[:6]}",
                name=f"webhook-{prefix}",
                webhook_url=req.url,
                webhook_secret=encrypt_webhook_secret(req.secret),
                status="ACTIVE",
                risk_profile={},
            )
            session.add(merchant)
        else:
            merchant.webhook_url = req.url
            merchant.webhook_secret = encrypt_webhook_secret(req.secret)
            merchant.status = "ACTIVE"
        risk_profile = dict(merchant.risk_profile or {})
        risk_profile["webhook_events"] = list(req.events)
        risk_profile["secret_hash"] = _secret_hash(req.secret)
        if verified or not req.challenge_expected:
            risk_profile["webhook_status"] = "ACTIVE"
            risk_profile["challenge_verified_at"] = datetime.now(UTC).isoformat()
        else:
            _set_pending(merchant, risk_profile, challenge_id)
        merchant.risk_profile = risk_profile
        await session.flush()
        await session.refresh(merchant)
        return ApiResponse(data=_merchant_to_out(merchant))


@router.get("", response_model=ApiResponse[PageResponse[WebhookOut]])
async def list_webhooks(
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[PageResponse[WebhookOut]]:
    """分页查询 Webhook 列表（已配置 webhook 的商户）。"""
    async with session_scope(tenant_id) as session:
        scope_filter = or_(
            Merchant.webhook_url.isnot(None),
            Merchant.risk_profile.has_key("webhook_events"),
        )
        total = (
            await session.execute(
                select(func.count())
                .select_from(Merchant)
                .where(Merchant.tenant_id == uuid.UUID(tenant_id), scope_filter)
            )
        ).scalar() or 0
        result = await session.execute(
            select(Merchant)
            .where(Merchant.tenant_id == uuid.UUID(tenant_id), scope_filter)
            .order_by(Merchant.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [_merchant_to_out(m) for m in result.scalars().all()]
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )


@router.get("/{webhook_id}", response_model=ApiResponse[WebhookOut])
async def get_webhook(
    webhook_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """查询 Webhook 详情。"""
    async with session_scope(tenant_id) as session:
        merchant = await _load_merchant(session, webhook_id, tenant_id)
        return ApiResponse(data=_merchant_to_out(merchant))


@router.put("/{webhook_id}", response_model=ApiResponse[WebhookOut])
async def update_webhook(
    webhook_id: str,
    req: WebhookUpdate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """更新 Webhook（URL/secret 变更时重发 challenge 验证；secret 省略则保留原值）。"""
    async with session_scope(tenant_id) as session:
        merchant = await _load_merchant(session, webhook_id, tenant_id)
        merchant.webhook_url = req.url
        if req.secret is not None:
            merchant.webhook_secret = encrypt_webhook_secret(req.secret)
        elif merchant.webhook_secret is None:
            raise NotFoundError(f"webhook secret not configured: {webhook_id}")
        risk_profile = dict(merchant.risk_profile or {})
        risk_profile["webhook_events"] = list(req.events)
        if req.secret is not None:
            risk_profile["secret_hash"] = _secret_hash(req.secret)

        challenge_id = f"ch_{uuid.uuid4()}"
        verified = await _run_challenge(req.url, challenge_id)
        if verified or not req.challenge_expected:
            merchant.status = "ACTIVE"
            risk_profile["webhook_status"] = "ACTIVE"
            risk_profile["challenge_verified_at"] = datetime.now(UTC).isoformat()
            risk_profile.pop("challenge_id", None)
        else:
            _set_pending(merchant, risk_profile, challenge_id)
        merchant.risk_profile = risk_profile
        return ApiResponse(data=_merchant_to_out(merchant))


@router.post("/{webhook_id}/challenge/verify", response_model=ApiResponse[WebhookOut])
async def verify_webhook_challenge(
    webhook_id: str,
    body: dict,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookOut]:
    """手工验证 challenge（目标未能在注册时回显时，由运维/合规补验证）。"""
    challenge_id = body.get("challenge_id")
    if not challenge_id:
        raise NotFoundError("challenge_id required")
    async with session_scope(tenant_id) as session:
        merchant = await _load_merchant(session, webhook_id, tenant_id)
        risk_profile = dict(merchant.risk_profile or {})
        if risk_profile.get("challenge_id") != challenge_id:
            raise NotFoundError("invalid challenge_id")
        merchant.status = "ACTIVE"
        risk_profile["webhook_status"] = "ACTIVE"
        risk_profile["challenge_verified_at"] = datetime.now(UTC).isoformat()
        risk_profile.pop("challenge_id", None)
        merchant.risk_profile = risk_profile
        return ApiResponse(data=_merchant_to_out(merchant))


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> None:
    """注销 Webhook（清空 webhook_url/secret，标记状态）。"""
    async with session_scope(tenant_id) as session:
        merchant = await _load_merchant(session, webhook_id, tenant_id)
        merchant.webhook_url = None
        merchant.webhook_secret = None
        merchant.status = "INACTIVE"
        risk_profile = dict(merchant.risk_profile or {})
        risk_profile["webhook_events"] = []
        risk_profile["webhook_status"] = "DELETED"
        risk_profile["webhook_deleted_at"] = datetime.now(UTC).isoformat()
        merchant.risk_profile = risk_profile
    return None


@router.post("/{webhook_id}/test", response_model=ApiResponse[WebhookTestResponse])
async def test_webhook(
    webhook_id: str,
    req: WebhookTestRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[WebhookTestResponse]:
    """手动触发测试事件投递（HMAC 签名 + httpx 投递，3s 超时）。"""
    async with session_scope(tenant_id) as session:
        merchant = await _load_merchant(session, webhook_id, tenant_id)
        if not merchant.webhook_url or not merchant.webhook_secret:
            raise NotFoundError(f"webhook not configured: {webhook_id}")
        webhook_url = merchant.webhook_url
        decrypted = decrypt_webhook_secret(merchant.webhook_secret)
        if decrypted is None:
            raise NotFoundError(f"webhook secret unavailable: {webhook_id}")
        webhook_secret = decrypted

    # 投递前 SSRF 校验（与 deliver() 对齐，防库中陈旧/被篡改 URL 打内网）
    try:
        webhook_url = validate_webhook_url(webhook_url)
    except ValueError as exc:
        return ApiResponse(
            data=WebhookTestResponse(
                delivery_id=f"dlv_{uuid.uuid4()}",
                webhook_id=webhook_id,
                event_type=req.event_type,
                status="FAILED",
                signature_header="",
            ),
            message=f"url validation failed: {exc}",
        )

    body = json.dumps(
        {
            "event_type": req.event_type,
            "test_payload": req.test_payload or {},
            "delivery_id": f"dlv_{uuid.uuid4()}",
            "is_test": True,
        }
    )
    timestamp = int(time.time())
    signature_header = webhook_service.sign(webhook_secret, body, timestamp)

    try:
        async with httpx.AsyncClient(timeout=_TEST_DELIVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                webhook_url,
                content=body,
                headers={
                    "X-FRD-Signature": signature_header,
                    "X-FRD-Timestamp": str(timestamp),
                    "Content-Type": "application/json",
                },
            )
        success = response.status_code < 400
        return ApiResponse(
            data=WebhookTestResponse(
                delivery_id=f"dlv_{uuid.uuid4()}",
                webhook_id=webhook_id,
                event_type=req.event_type,
                status="SUCCESS" if success else "FAILED",
                signature_header=signature_header,
            )
        )
    except httpx.HTTPError:
        return ApiResponse(
            data=WebhookTestResponse(
                delivery_id=f"dlv_{uuid.uuid4()}",
                webhook_id=webhook_id,
                event_type=req.event_type,
                status="FAILED",
                signature_header=signature_header,
            )
        )


@router.get("/{webhook_id}/deliveries", response_model=ApiResponse[PageResponse[WebhookDeliveryOut]])
async def list_deliveries(
    webhook_id: str,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("webhook:write")),
) -> ApiResponse[PageResponse[WebhookDeliveryOut]]:
    """查询 Webhook 投递记录（暂无投递表，返回空分页预留）。"""
    async with session_scope(tenant_id) as session:
        await _load_merchant(session, webhook_id, tenant_id)
        return ApiResponse(
            data=PageResponse(items=[], page=page, page_size=page_size, total=0)
        )
