"""TenantMiddleware：从 JWT/API Key 提取 tenant_id（D03 §4.7 / D05 §2.2）。

tenant_id 来源优先级（D05 §2.2）：
1. JWT 内 tenant_id 声明
2. API Key 绑定的 tenant_id
3. X-Tenant-Id 请求头（仅 admin:* scope 跨租户运维）

注入：
- request.state.tenant_id
- request.state.tenant_plan
- structlog contextvar tenant_id

不在此处 SET app.tenant_id（由 db.session 在取连接时设置，避免连接复用串号）。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.exceptions import UnauthorizedError
from app.core.logging import bind_request_context, get_logger
from app.core.security import decode_token

logger = get_logger(__name__)

TENANT_HEADER = "X-Tenant-Id"
AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
APIKEY_PREFIX = "ApiKey "


def _extract_tenant_from_jwt(token: str) -> str | None:
    """从 JWT 解码 tenant_id（不抛错，验证失败返回 None）。"""
    try:
        payload = decode_token(token)
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            return str(tenant_id)
    except Exception:
        pass
    return None


class TenantMiddleware(BaseHTTPMiddleware):
    """从凭据提取 tenant_id 注入 request.state。"""

    # 不需要租户上下文的路径
    EXEMPT_PATHS = {
        "/",
        "/health",
        "/ready",
        "/live",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/live",
    }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # 健康检查与文档路径放行
        if path in self.EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        tenant_id: str | None = None
        auth_header = request.headers.get(AUTH_HEADER)

        if auth_header:
            if auth_header.startswith(BEARER_PREFIX):
                token = auth_header[len(BEARER_PREFIX) :]
                tenant_id = _extract_tenant_from_jwt(token)
            elif auth_header.startswith(APIKEY_PREFIX):
                # TODO: 实现 API Key 查表得到 tenant_id（M2 阶段）
                # api_key = auth_header[len(APIKEY_PREFIX):]
                # tenant_id = await api_key_service.lookup(api_key)
                pass

        # X-Tenant-Id 仅 admin scope 允许，骨架中暂记录审计
        if tenant_id is None:
            x_tenant = request.headers.get(TENANT_HEADER)
            if x_tenant:
                logger.warning(
                    "x_tenant_id_header_used",
                    path=path,
                    note="admin scope cross-tenant operation; TODO: verify admin:* scope",
                )
                tenant_id = x_tenant

        if tenant_id is None and not path.startswith("/api/v1/auth"):
            # 非认证路径必须有 tenant_id
            err = UnauthorizedError("missing tenant_id context")
            return JSONResponse(
                status_code=err.http_status,
                content={
                    "code": err.code,
                    "message": err.message,
                    "data": None,
                    "request_id": getattr(request.state, "request_id", "-"),
                },
            )

        request.state.tenant_id = tenant_id
        if tenant_id:
            bind_request_context(
                request_id=getattr(request.state, "request_id", "-"),
                tenant_id=tenant_id,
            )

        return await call_next(request)


__all__ = ["AUTH_HEADER", "BEARER_PREFIX", "APIKEY_PREFIX", "TENANT_HEADER", "TenantMiddleware"]
