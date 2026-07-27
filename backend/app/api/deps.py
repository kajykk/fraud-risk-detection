"""依赖注入：get_db / get_current_user / get_tenant。"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db


async def get_current_user(request: Request) -> dict[str, Any]:
    """从 Authorization header 解码 JWT，返回用户信息。

    Returns:
        {"sub": ..., "tenant_id": ..., "roles": [...], "scope": "..."}
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError("missing bearer token")
    token = auth_header[len("Bearer "):]
    try:
        payload = decode_token(token)
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
    """依赖工厂：校验当前用户是否具备指定 scope。"""

    async def _check(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_scopes = (user.get("scope") or "").split()
        if scope not in user_scopes and "admin:*" not in user_scopes:
            from app.core.exceptions import ForbiddenError

            raise ForbiddenError(f"insufficient scope: required={scope}")
        return user

    return _check


__all__ = ["get_current_user", "get_db", "get_tenant_id", "require_scope"]
