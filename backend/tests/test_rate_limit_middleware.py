"""RateLimitMiddleware 单元测试（D05 §2.7）。

覆盖：
- 豁免路径（/health 等）不经过限流器
- 租户维度限流响应头（STANDARD 100 QPS）
- 窗口超限返回 429 + Retry-After
- 无租户上下文按来源 IP 限流：认证端点更严（20/s），普通端点 120/s
- Redis ZSET 滑动窗口计数判定与故障 fail-open

Redis 通过 monkeypatch app.db.redis.get_redis 打桩，不依赖真实实例。
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware.rate_limit import IP_AUTH_LIMIT, IP_DEFAULT_LIMIT, RateLimitMiddleware

TENANT = "00000000-0000-0000-0000-000000000001"


def _request(path: str = "/api/v1/rules", ip: str = "203.0.113.9") -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "client": (ip, 55555),
    }
    request = Request(scope)
    request.state.tenant_id = TENANT
    request.state.request_id = "req-test"
    return request


async def _call_next(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _middleware() -> RateLimitMiddleware:
    return RateLimitMiddleware(app=None)


class _FakePipeline:
    """模拟 redis.pipeline() 的 ZSET 滑动窗口四连命令，execute 返回固定计数。"""

    def __init__(self, count: int) -> None:
        self._count = count

    def zremrangebyscore(self, *args: Any) -> None:
        return None

    def zadd(self, *args: Any) -> None:
        return None

    def zcard(self, *args: Any) -> None:
        return None

    def expire(self, *args: Any) -> None:
        return None

    async def execute(self) -> list[int]:
        return [0, 1, self._count, True]


async def test_exempt_path_bypasses_limiter(monkeypatch) -> None:
    """豁免路径直接放行，不触发滑动窗口检查。"""
    checked: list[str] = []

    async def fake_check(tenant_id: str, endpoint: str, qps_limit: int):
        checked.append(endpoint)
        return True, 1, 0

    monkeypatch.setattr(RateLimitMiddleware, "_check_rate_limit", staticmethod(fake_check))
    response = await _middleware().dispatch(_request("/health"), _call_next)
    assert checked == []
    assert response.status_code == 200


async def test_tenant_request_gets_standard_plan_headers(monkeypatch) -> None:
    """带租户上下文的请求按 STANDARD 套餐 100 QPS 检查并回写三个限流头。"""
    seen: dict[str, Any] = {}

    async def fake_check(tenant_id: str, endpoint: str, qps_limit: int):
        seen.update({"tenant_id": tenant_id, "endpoint": endpoint, "qps_limit": qps_limit})
        return True, 97, 1756000000

    monkeypatch.setattr(RateLimitMiddleware, "_check_rate_limit", staticmethod(fake_check))
    response = await _middleware().dispatch(_request(), _call_next)
    assert seen == {
        "tenant_id": TENANT,
        "endpoint": "/api/v1/rules",
        "qps_limit": 100,
    }
    assert response.headers["X-RateLimit-Limit"] == "100"
    assert response.headers["X-RateLimit-Remaining"] == "97"
    assert response.headers["X-RateLimit-Reset"] == "1756000000"


async def test_over_limit_returns_429_with_retry_after(monkeypatch) -> None:
    """窗口超限：429 + RATE_LIMITED 错误码 + Retry-After 头 + remaining=0。"""

    async def fake_check(tenant_id: str, endpoint: str, qps_limit: int):
        return False, 0, 1756000000

    monkeypatch.setattr(RateLimitMiddleware, "_check_rate_limit", staticmethod(fake_check))
    response = await _middleware().dispatch(_request(), _call_next)
    assert response.status_code == 429
    body = json.loads(response.body)
    assert body["code"] == "RATE_LIMITED"
    assert body["request_id"] == "req-test"
    assert response.headers["Retry-After"] == "1"
    assert response.headers["X-RateLimit-Limit"] == "100"
    assert response.headers["X-RateLimit-Remaining"] == "0"


async def test_missing_tenant_applies_strict_ip_limit_on_auth_path(monkeypatch) -> None:
    """无租户上下文 + 认证端点：按来源 IP 哈希限流，阈值 20/s。"""
    seen: dict[str, Any] = {}

    async def fake_check(tenant_id: str, endpoint: str, qps_limit: int):
        seen.update({"bucket": tenant_id, "qps_limit": qps_limit})
        return True, 19, 1756000000

    monkeypatch.setattr(RateLimitMiddleware, "_check_rate_limit", staticmethod(fake_check))
    request = _request("/auth/login")
    request.state.tenant_id = None
    response = await _middleware().dispatch(request, _call_next)
    assert seen["qps_limit"] == IP_AUTH_LIMIT
    assert seen["bucket"].startswith("ip:")
    assert len(seen["bucket"]) < 40  # 仅哈希前缀，不含原始 IP
    assert response.headers["X-RateLimit-Limit"] == str(IP_AUTH_LIMIT)


async def test_missing_tenant_uses_default_ip_limit_on_regular_path(monkeypatch) -> None:
    """无租户上下文的普通端点按宽松默认阈值 120/s。"""
    seen: dict[str, int] = {}

    async def fake_check(tenant_id: str, endpoint: str, qps_limit: int):
        seen["qps_limit"] = qps_limit
        return True, 1, 1756000000

    monkeypatch.setattr(RateLimitMiddleware, "_check_rate_limit", staticmethod(fake_check))
    request = _request("/api/v1/cases")
    request.state.tenant_id = None
    await _middleware().dispatch(request, _call_next)
    assert seen["qps_limit"] == IP_DEFAULT_LIMIT


async def test_check_rate_limit_denies_when_window_count_exceeded(monkeypatch) -> None:
    """ZCARD 计数 > 阈值 → 拒绝，reset 时间在 1 秒内到期。"""
    monkeypatch.setattr(
        "app.db.redis.get_redis",
        lambda: SimpleNamespace(pipeline=lambda: _FakePipeline(count=101)),
    )
    allowed, remaining, reset_at = await RateLimitMiddleware._check_rate_limit(
        tenant_id=TENANT, endpoint="/x", qps_limit=100
    )
    assert allowed is False
    assert remaining == 0
    assert reset_at >= int(time.time())


async def test_check_rate_limit_allows_under_window_count(monkeypatch) -> None:
    """计数未超阈值 → 放行并返回剩余配额。"""
    monkeypatch.setattr(
        "app.db.redis.get_redis",
        lambda: SimpleNamespace(pipeline=lambda: _FakePipeline(count=50)),
    )
    allowed, remaining, reset_at = await RateLimitMiddleware._check_rate_limit(
        tenant_id=TENANT, endpoint="/x", qps_limit=100
    )
    assert allowed is True
    assert remaining == 50


async def test_check_rate_limit_fails_open_on_redis_error(monkeypatch) -> None:
    """Redis 故障降级 fail-open：放行且剩余配额为完整额度。"""

    def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.db.redis.get_redis", boom)
    allowed, remaining, reset_at = await RateLimitMiddleware._check_rate_limit(
        tenant_id=TENANT, endpoint="/x", qps_limit=42
    )
    assert allowed is True
    assert remaining == 42
    assert reset_at >= int(time.time())
