"""pytest 全局 fixtures（D07 测试设计）。

约定：
- 单元测试：不依赖外部服务（mock DB/Redis/Neo4j）
- 集成测试：使用 docker-compose 起的 PG/Redis/Neo4j，标记 @pytest.mark.integration
- E2E 测试：通过 httpx.AsyncClient 调用 FastAPI TestClient
- 默认 APP_ENV=test，避免污染开发环境
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 在导入 app 之前设置测试环境变量
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-pytest-only")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("PROMETHEUS_ENABLED", "false")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_global_resources():
    """每个测试后释放跨测试共享的异步全局资源（engine / Redis 客户端）。

    pytest-asyncio 每个测试使用独立事件循环，而 app.db.session / app.db.redis
    为模块级单例连接池。若池内连接跨循环复用，asyncpg 在旧循环的 socket 上
    ping 会抛 'Event loop is closed' / 'NoneType has no attribute send'。
    """
    yield
    from app.db.redis import close_redis
    from app.db.session import close_engine

    await close_redis()
    await close_engine()


@pytest.fixture
def app():
    """返回 FastAPI app 实例（不触发 lifespan，避免连接依赖服务）。"""
    from app.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """异步 HTTP 客户端（基于 ASGITransport，不走真实端口）。

    使用方法：
        async with client as c:
            response = await c.get("/health")
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_transaction() -> dict:
    """示例交易数据（D05 §4.1 请求体）。"""
    return {
        "external_tx_id": "TX20260727000001",
        "tx_type": "PURCHASE",
        "amount": 128800,
        "currency": "CNY",
        "occurred_at": "2026-07-27T08:00:00Z",
        "card_token": "tok_card_xxxxx",
        "card_bin": "622202",
        "card_last4": "1234",
        "merchant_id": "mch_001",
        "mcc": "5411",
        "acquirer_id": "acq_icbc",
        "device_fingerprint_hash": "fp_sha256_xxx",
        "ip_address": "1.2.3.4",
        "user_id": "user_999",
        "user_created_at": "2025-01-01T00:00:00Z",
        "channel": "WEB",
        "is_3ds_verified": True,
        "merchant_category": "grocery",
        "shipping_country": "CN",
        "billing_country": "CN",
        "note_text": "用户备注",
        "metadata": {},
    }


@pytest.fixture
def test_tenant_id() -> str:
    """测试用 tenant_id。"""
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def auth_headers(test_tenant_id: str) -> dict[str, str]:
    """构造测试用 Bearer token（绕过 TenantMiddleware）。

    生产环境不应使用此 fixture，应通过 POST /auth/token 获取真实 token。
    """
    from app.core.security import create_access_token

    token = create_access_token(
        subject="cli_frd_test",
        tenant_id=test_tenant_id,
        roles=["TENANT_ADMIN"],
        scopes=["transaction:score", "transaction:read", "rule:read", "case:read"],
    )
    return {"Authorization": f"Bearer {token}"}
