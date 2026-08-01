"""依赖注入：get_db / get_current_user / get_tenant。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import ACCESS_TOKEN_TYPE, verify_token
from app.db.session import get_db


async def get_current_user(request: Request) -> dict[str, Any]:
    """从 Authorization header 解码 JWT，返回用户信息。

    仅接受 type=access 的 access token（refresh token 不可用于访问）。
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError("missing bearer token")
    token = auth_header[len("Bearer "):]
    try:
        payload = verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except Exception as exc:
        raise UnauthorizedError("invalid token") from exc

    # 注入 request.state
    request.state.user_id = payload.get("sub")
    return payload


async def get_tenant_id(request: Request) -> str:
    """从 request.state 获取 tenant_id（由 TenantMiddleware 注入）。"""
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise UnauthorizedError("missing tenant_id context")
    return tenant_id


def require_scope(scope: str):
    """依赖工厂：校验当前调用方是否具备指定 scope。

    支持两种凭据：
    - Bearer JWT：校验 scope / admin:* 声明
    - ApiKey：校验 api_keys.scopes（由 TenantMiddleware 注入 request.state）
    """

    async def _check(request: Request) -> dict[str, Any]:
        # API Key 认证路径
        api_key_scopes = getattr(request.state, "api_key_scopes", None)
        if api_key_scopes is not None:
            if scope in api_key_scopes or "admin:*" in api_key_scopes:
                return {
                    "sub": getattr(request.state, "api_key_id", "api_key"),
                    "tenant_id": request.state.tenant_id,
                    "scope": " ".join(api_key_scopes),
                }
            raise ForbiddenError(f"insufficient scope: required={scope}")

        # Bearer JWT 认证路径
        user = await get_current_user(request)
        user_scopes = (user.get("scope") or "").split()
        if scope in user_scopes or "admin:*" in user_scopes:
            return user
        raise ForbiddenError(f"insufficient scope: required={scope}")

    return _check


__all__ = ["get_current_user", "get_db", "get_tenant_id", "require_scope"]
