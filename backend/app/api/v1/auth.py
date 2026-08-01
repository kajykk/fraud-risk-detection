"""认证路由（D05 §3）。

- POST /auth/login：用户名密码登录（users 表校验）
- POST /auth/token：OAuth2 client_credentials（api_keys 表校验）
- POST /auth/refresh：刷新 token
- GET /auth/me：当前用户信息
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.deps import get_current_user
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_token,
)
from app.db.session import get_session_factory
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, Token, TokenRequest, UserInfo
from app.schemas.common import ApiResponse
from app.services.api_key_service import api_key_service

router = APIRouter()


@router.post("/login", response_model=ApiResponse[Token])
async def login(req: LoginRequest) -> ApiResponse[Token]:
    """用户名密码登录。"""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(req.password, user.password_hash):
            raise UnauthorizedError("invalid username or password")
        if user.status != "ACTIVE":
            raise UnauthorizedError(f"user account {user.status.lower()}")
        user.last_login_at = datetime.now(UTC)
        await session.commit()

    scopes = req.scopes or _default_scopes(user.roles)
    access_token = create_access_token(
        subject=user.username,
        tenant_id=str(user.tenant_id),
        roles=list(user.roles),
        scopes=scopes,
    )
    refresh = create_refresh_token(
        subject=user.username,
        tenant_id=str(user.tenant_id),
    )
    return ApiResponse(data=Token(access_token=access_token, refresh_token=refresh, expires_in=1800))


@router.post("/token", response_model=ApiResponse[Token])
async def token_endpoint(req: TokenRequest, request: Request) -> ApiResponse[Token]:
    """OAuth2 client_credentials 模式（API Key 校验）。"""
    key = await api_key_service.lookup(req.client_secret)
    if key is None:
        raise UnauthorizedError("invalid client credentials")

    requested = (req.scope or "").split()
    allowed = [s for s in requested if s in key.scopes]
    if set(requested) != set(allowed):
        raise UnauthorizedError("requested scope not allowed for this client")

    access_token = create_access_token(
        subject=key.name,
        tenant_id=key.tenant_id,
        roles=[],
        scopes=allowed,
        extra_claims={"client_id": key.api_key_id, "merchant_id": key.merchant_id},
    )
    return ApiResponse(data=Token(access_token=access_token, expires_in=1800, scope=req.scope))


@router.post("/refresh", response_model=ApiResponse[Token])
async def refresh_token(req: RefreshTokenRequest) -> ApiResponse[Token]:
    """刷新 access token。"""
    payload = verify_token(req.refresh_token, expected_type="refresh")
    access_token = create_access_token(
        subject=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=[],
        scopes=[],
    )
    return ApiResponse(data=Token(access_token=access_token, expires_in=1800))


@router.get("/me", response_model=ApiResponse[UserInfo])
async def me(user: dict = Depends(get_current_user)) -> ApiResponse[UserInfo]:
    """当前用户信息。"""
    return ApiResponse(
        data=UserInfo(
            sub=user["sub"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", []),
            scope=user.get("scope"),
        )
    )


@router.get("/profile", response_model=ApiResponse[UserInfo])
async def profile(user: dict = Depends(get_current_user)) -> ApiResponse[UserInfo]:
    """当前用户信息（/auth/profile 别名，兼容前端调用）。"""
    return ApiResponse(
        data=UserInfo(
            sub=user["sub"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", []),
            scope=user.get("scope"),
        )
    )


def _default_scopes(roles: list[str]) -> list[str]:
    """按角色返回默认 scope（D05 §3.2 角色矩阵）。"""
    role_scopes = {
        "TENANT_ADMIN": ["admin:*"],
        "MERCHANT_ADMIN": ["transaction:score", "transaction:read", "webhook:write"],
        "RISK_ANALYST": ["transaction:score", "transaction:read", "case:read", "case:write"],
        "RISK_MANAGER": [
            "transaction:score",
            "transaction:read",
            "case:read",
            "case:write",
            "rule:read",
            "rule:write",
        ],
        "AUDITOR": ["audit:read"],
        "COMPLIANCE_OFFICER": ["pipl:read", "pipl:write", "case:read"],
        "DEVOPS_OPS": ["model:read", "model:write", "kill_switch:write"],
    }
    scopes: list[str] = []
    for role in roles:
        scopes.extend(role_scopes.get(role, []))
    return list(dict.fromkeys(scopes))


__all__ = ["_default_scopes", "router"]
