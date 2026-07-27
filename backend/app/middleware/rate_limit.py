"""RateLimitMiddleware：基于 Redis 滑动窗口限流（D05 §2.7）。

按 tenant_id + endpoint 维度限流。
租户级别限流配置（D05 §2.7）：
- STANDARD: 100 QPS / 突发 200
- PRO: 500 QPS / 突发 1000
- ENTERPRISE: 2000 QPS / 突发 5000

实现：Redis ZSET 滑动窗口（ZADD + ZREMRANGEBYSCORE + ZCARD）。
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger

logger = get_logger(__name__)

# 租户套餐 -> QPS 上限
PLAN_QPS = {
    "STANDARD": 100,
    "PRO": 500,
    "ENTERPRISE": 2000,
}
DEFAULT_QPS = 1000  # 未指定 plan 时默认


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 滑动窗口的限流中间件。"""

    EXEMPT_PATHS = {"/health", "/ready", "/live", "/metrics", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in self.EXEMPT_PATHS or path.startswith(("/docs", "/redoc")):
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return await call_next(request)

        # TODO: 从 tenants 表读取 plan（M2 阶段实现，骨架用 DEFAULT_QPS）
        plan = "STANDARD"
        qps_limit = PLAN_QPS.get(plan, DEFAULT_QPS)

        allowed, remaining, reset_at = await self._check_rate_limit(
            tenant_id=tenant_id,
            endpoint=path,
            qps_limit=qps_limit,
        )

        if not allowed:
            logger.warning("rate_limited", tenant_id=tenant_id, path=path, qps_limit=qps_limit)
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": "rate limit exceeded",
                    "data": None,
                    "request_id": getattr(request.state, "request_id", "-"),
                },
                headers={
                    "X-RateLimit-Limit": str(qps_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                    "Retry-After": "1",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(qps_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response

    async def _check_rate_limit(
        self,
        tenant_id: str,
        endpoint: str,
        qps_limit: int,
    ) -> tuple[bool, int, int]:
        """Redis ZSET 滑动窗口：1 秒窗口内请求数 <= qps_limit。

        Returns:
            (allowed, remaining, reset_at_unix_timestamp)
        """
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            key = f"rate_limit:{tenant_id}:{endpoint}"
            now = time.time()
            window_start = now - 1.0  # 1 秒窗口

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)  # 移除窗口外
            pipe.zadd(key, {str(now): now})  # 加入当前请求
            pipe.zcard(key)  # 计数
            pipe.expire(key, 2)  # TTL 2 秒
            results = await pipe.execute()
            count = results[2]

            if count > qps_limit:
                return False, 0, int(now + 1)
            return True, max(0, qps_limit - count), int(now + 1)
        except Exception as exc:
            # Redis 故障时降级为不限流（fail-open），避免主路径阻塞
            logger.warning("rate_limit_redis_failed", error=str(exc))
            return True, qps_limit, int(time.time() + 1)


__all__ = ["DEFAULT_QPS", "PLAN_QPS", "RateLimitMiddleware"]
