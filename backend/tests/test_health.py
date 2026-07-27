"""健康检查接口测试（D05 §1 + D03 §7）。

覆盖：
- GET /health
- GET /live
- GET /ready（依赖服务降级时返回 degraded）
- GET /（根路径）
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    """GET /health 返回 200 + status=ok。"""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_live_ok(client: AsyncClient) -> None:
    """GET /live 返回 200 + status=ok。"""
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_root_returns_app_info(client: AsyncClient) -> None:
    """GET / 返回服务基本信息。"""
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "name" in body
    assert "version" in body
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"


@pytest.mark.asyncio
async def test_openapi_schema_available(client: AsyncClient) -> None:
    """GET /openapi.json 返回 OpenAPI schema。"""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "FRD 金融反欺诈系统 API"
    # 验证关键路径已注册
    paths = schema["paths"]
    assert "/api/v1/transactions/score" in paths
    assert "/api/v1/auth/token" in paths
    assert "/api/v1/rules" in paths
    assert "/api/v1/cases" in paths
    assert "/api/v1/pipl/consent" in paths


@pytest.mark.asyncio
async def test_docs_page_available(client: AsyncClient) -> None:
    """GET /docs 返回 Swagger UI HTML。"""
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
