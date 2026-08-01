"""TenantMiddleware：从 JWT/API Key 提取 tenant_id（D03 §4.7 / D05 §2.2）。

tenant_id 来源优先级（D05 §2.2）：
1. JWT 内 tenant_id 声明
2. API Key 绑定的 tenant_id
3. X-Tenant-Id 请求头（仅 admin:* scope 跨租户运维）

注入：
- request.state.tenant_id
- request.state.tenant_plan
- request.state.api_key_scopes（API Key 认证时）
- structlog contextvar tenant_id

不在此处 SET app.tenant_id（由 db.session 在取连接时设置，避免连接复用串号）。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.exceptions import ForbiddenError, FRDError, UnauthorizedError
from app.core.logging import bind_request_context, get_logger
from app.core.security import decode_token
from app.services.api_key_service import api_key_service

logger = get_logger(__name__)

TENANT_HEADER = "X-Tenant-Id"
AUTH_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
APIKEY_PREFIX = "ApiKey "

ADMIN_SCOPE = "admin:*"


def _extract_jwt_payload(token: str) -> dict | None:
    """解码 JWT（不抛错，验证失败返回 None）。"""
    try:
        return decode_token(token)
    except Exception:
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
        api_key_scopes: list[str] = []
        jwt_has_admin = False
        auth_header = request.headers.get(AUTH_HEADER)

        if auth_header:
            if auth_header.startswith(BEARER_PREFIX):
                token = auth_header[len(BEARER_PREFIX) :]
                payload = _extract_jwt_payload(token)
                if payload:
                    tenant_id = payload.get("tenant_id")
                    scopes = (payload.get("scope") or "").split()
                    jwt_has_admin = ADMIN_SCOPE in scopes
            elif auth_header.startswith(APIKEY_PREFIX):
                raw_key = auth_header[len(APIKEY_PREFIX) :].strip()
                key_info = await api_key_service.lookup(raw_key)
                if key_info is None:
                    err = UnauthorizedError("invalid api key")
                    return self._error_response(request, err)
                if not api_key_service.ip_allowed(
                    request.client.host if request.client else "", key_info.ip_whitelist
                ):
                    err = ForbiddenError("client ip not allowed")
                    return self._error_response(request, err)
                tenant_id = key_info.tenant_id
                api_key_scopes = key_info.scopes
                request.state.api_key_id = key_info.api_key_id

        # X-Tenant-Id 仅 admin scope 允许（跨租户运维）
        x_tenant = request.headers.get(TENANT_HEADER)
        if x_tenant:
            if tenant_id is None:
                # 无凭据场景：要求 JWT 携带 admin:* scope
                if jwt_has_admin:
                    tenant_id = x_tenant
                else:
                    err = ForbiddenError("X-Tenant-Id requires admin:* scope")
                    return self._error_response(request, err)
            elif x_tenant != tenant_id:
                # 跨租户覆盖：要求 admin:* scope
                if not jwt_has_admin:
                    err = ForbiddenError("cross-tenant X-Tenant-Id requires admin:* scope")
                    return self._error_response(request, err)
                tenant_id = x_tenant

        if tenant_id is None and not path.startswith("/api/v1/auth"):
            # 非认证路径必须有 tenant_id
            err = UnauthorizedError("missing tenant_id context")
            return self._error_response(request, err)

        request.state.tenant_id = tenant_id
        if api_key_scopes:
            request.state.api_key_scopes = api_key_scopes
        if tenant_id:
            bind_request_context(
                request_id=getattr(request.state, "request_id", "-"),
                tenant_id=tenant_id,
            )

        return await call_next(request)

    def _error_response(self, request: Request, err: FRDError) -> JSONResponse:
        return JSONResponse(
            status_code=err.http_status,
            content={
                "code": err.code,
                "message": err.message,
                "data": None,
                "request_id": getattr(request.state, "request_id", "-"),
            },
        )


__all__ = ["AUTH_HEADER", "BEARER_PREFIX", "APIKEY_PREFIX", "TENANT_HEADER", "TenantMiddleware"]
