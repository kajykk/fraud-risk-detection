"""Webhook API 配置语义测试（D05 §11）。

覆盖（create/update 显式 merchant_id 语义）：
- create 缺失 merchant_id → 400；格式非法 → 400
- create 商户不存在 → 404（不再隐式覆写最早商户行/自动建商户）
- create 只写入请求体指定的商户行，其他商户不受影响
- update 缺失 merchant_id → 400；与路径 id 不一致 → 400
- update secret 省略时保留原签名密钥

DB 通过 FakeSession 打桩（不依赖真实 PostgreSQL）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.tenant import Merchant
from app.services.webhook import decrypt_webhook_secret, encrypt_webhook_secret

TEST_TENANT = "00000000-0000-0000-0000-000000000001"

VALID_BODY = {
    # 公网 IP 字面量：跳过 DNS 解析，单测不依赖外网
    "url": "https://8.8.8.8/frd-hook",
    "events": ["transaction.rejected", "case.created"],
    "secret": "super-secret-webhook-key-0123456789",
    "challenge_expected": False,
}


@pytest.fixture
def webhook_headers() -> dict[str, str]:
    """持有 webhook:write scope 的测试令牌。"""
    token = create_access_token(
        subject="cli_frd_test",
        tenant_id=TEST_TENANT,
        roles=["TENANT_ADMIN"],
        scopes=["webhook:write"],
    )
    return {"Authorization": f"Bearer {token}"}


def _make_merchant(name: str, **kwargs) -> Merchant:
    """构造脱离 DB 的 Merchant ORM 实例。

    注：PK/Timestamp 的 default 是 INSERT 时才生效的列默认值，
    纯实例化不触发，这里显式赋值。
    """
    merchant = Merchant(
        tenant_id=uuid.UUID(TEST_TENANT),
        merchant_no=f"M-{name}",
        name=name,
        status="ACTIVE",
        risk_profile=dict(kwargs.pop("risk_profile", {})),
        **kwargs,
    )
    merchant.id = uuid.uuid4()
    merchant.created_at = datetime.now(UTC)
    return merchant


class _FakeResult:
    def __init__(self, merchant: Merchant | None) -> None:
        self._merchant = merchant

    def scalar_one_or_none(self) -> Merchant | None:
        return self._merchant


class _FakeSession:
    def __init__(self, merchant: Merchant | None) -> None:
        self.merchant = merchant
        self.committed = False

    async def execute(self, query) -> _FakeResult:  # noqa: ANN001 - 测试桩
        return _FakeResult(self.merchant)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj) -> None:  # noqa: ANN001 - 测试桩
        return None


def _patch_session(monkeypatch, merchant: Merchant | None) -> None:
    @asynccontextmanager
    async def fake_session_scope(_tenant_id: str | None = None) -> AsyncIterator[_FakeSession]:
        yield _FakeSession(merchant)

    monkeypatch.setattr(
        "app.api.v1.webhooks.session_scope", fake_session_scope, raising=True
    )


# --------------------------------------------------------------------------- #
# create：显式 merchant_id 语义
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_missing_merchant_id_returns_400(
    client: AsyncClient, webhook_headers: dict[str, str]
) -> None:
    """create 缺失 merchant_id 应返回 400 INVALID_PARAMS。"""
    response = await client.post(
        "/api/v1/webhooks", json={**VALID_BODY}, headers=webhook_headers
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_create_invalid_merchant_id_format_returns_400(
    client: AsyncClient, webhook_headers: dict[str, str]
) -> None:
    """create merchant_id 非 UUID 应返回 400。"""
    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "merchant_id": "not-a-uuid"},
        headers=webhook_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_create_merchant_not_found_returns_404(
    client: AsyncClient, webhook_headers: dict[str, str], monkeypatch
) -> None:
    """指定商户不存在时应返回 404，而不是自动创建/覆写其他行。"""
    _patch_session(monkeypatch, None)
    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "merchant_id": str(uuid.uuid4())},
        headers=webhook_headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_targets_requested_merchant_only(
    client: AsyncClient, webhook_headers: dict[str, str], monkeypatch
) -> None:
    """create 只写请求体指定的商户 B，租户内更早的商户 A 配置不受影响。"""
    merchant_a = _make_merchant("earliest")
    merchant_b = _make_merchant("target")
    _patch_session(monkeypatch, merchant_b)

    response = await client.post(
        "/api/v1/webhooks",
        json={**VALID_BODY, "merchant_id": str(merchant_b.id)},
        headers=webhook_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "OK"
    data = body["data"]
    assert data["id"] == str(merchant_b.id)
    assert data["url"] == VALID_BODY["url"]
    assert data["status"] == "ACTIVE"
    assert data["events"] == VALID_BODY["events"]

    # 目标商户已写入配置
    assert merchant_b.webhook_url == VALID_BODY["url"]
    assert decrypt_webhook_secret(merchant_b.webhook_secret) == VALID_BODY["secret"]
    # 其他商户未被触碰
    assert merchant_a.webhook_url is None
    assert merchant_a.risk_profile == {}


# --------------------------------------------------------------------------- #
# update：显式 merchant_id 语义
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_missing_merchant_id_returns_400(
    client: AsyncClient, webhook_headers: dict[str, str]
) -> None:
    """update 缺失 merchant_id 应返回 400。"""
    response = await client.put(
        f"/api/v1/webhooks/{uuid.uuid4()}",
        json={**VALID_BODY},
        headers=webhook_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_update_merchant_id_mismatch_returns_400(
    client: AsyncClient, webhook_headers: dict[str, str], monkeypatch
) -> None:
    """update 请求体 merchant_id 与路径 {id} 不一致应返回 400。"""
    merchant = _make_merchant("target")
    _patch_session(monkeypatch, merchant)
    response = await client.put(
        f"/api/v1/webhooks/{uuid.uuid4()}",
        json={**VALID_BODY, "merchant_id": str(merchant.id)},
        headers=webhook_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_update_keeps_secret_when_omitted(
    client: AsyncClient, webhook_headers: dict[str, str], monkeypatch
) -> None:
    """update 省略 secret 时保留原签名密钥，仅更新 URL/events。"""
    original_secret = "original-secret-key-0123456789"
    merchant = _make_merchant(
        "target",
        webhook_url="https://old.example.com/hook",
        webhook_secret=encrypt_webhook_secret(original_secret),
        risk_profile={"webhook_status": "ACTIVE"},
    )
    _patch_session(monkeypatch, merchant)

    new_url = "https://1.0.1.10/hook"
    response = await client.put(
        f"/api/v1/webhooks/{merchant.id}",
        json={
            "merchant_id": str(merchant.id),
            "url": new_url,
            "events": ["case.created"],
            "challenge_expected": False,
        },
        headers=webhook_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["url"] == new_url
    assert data["status"] == "ACTIVE"
    assert merchant.webhook_url == new_url
    assert decrypt_webhook_secret(merchant.webhook_secret) == original_secret
