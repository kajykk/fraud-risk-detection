"""认证路由（D05 §3）。

- POST /auth/login：用户名密码登录
- POST /auth/token：OAuth2 client_credentials
- POST /auth/refresh：刷新 token
- GET /auth/me：当前用户信息
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.security import create_access_token, create_refresh_token, verify_token
from app.schemas.auth import LoginRequest, RefreshTokenRequest, Token, TokenRequest, UserInfo
from app.schemas.common import ApiResponse

router = APIRouter()


@router.post("/login", response_model=ApiResponse[Token])
async def login(req: LoginRequest) -> ApiResponse[Token]:
    """用户名密码登录。"""
    # TODO: 查 users 表验证密码（M2 实现）
    # 骨架：返回 mock token
    access_token = create_access_token(
        subject=req.username,
        tenant_id="00000000-0000-0000-0000-000000000000",
        roles=["RISK_ANALYST"],
        scopes=req.scopes or ["transaction:score", "transaction:read"],
    )
    refresh = create_refresh_token(
        subject=req.username,
        tenant_id="00000000-0000-0000-0000-000000000000",
    )
    return ApiResponse(data=Token(access_token=access_token, refresh_token=refresh, expires_in=1800))


@router.post("/token", response_model=ApiResponse[Token])
async def token_endpoint(req: TokenRequest) -> ApiResponse[Token]:
    """OAuth2 client_credentials 模式。"""
    # TODO: 校验 client_id + client_secret（M2 实现）
    access_token = create_access_token(
        subject=req.client_id,
        tenant_id="00000000-0000-0000-0000-000000000000",
        roles=["TENANT_ADMIN"],
        scopes=(req.scope or "").split(),
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
