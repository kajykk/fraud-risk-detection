"""认证路由（D05 §3）。

- POST /auth/login：用户名密码登录（users 表校验）
- POST /auth/token：OAuth2 client_credentials（api_keys 表校验）
- POST /auth/refresh：刷新 token
- GET /auth/me：当前用户信息
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text

from app.api.deps import get_current_user
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
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
logger = get_logger(__name__)


@router.post("/login", response_model=ApiResponse[Token])
async def login(req: LoginRequest) -> ApiResponse[Token]:
    """用户名密码登录。"""
    factory = get_session_factory()
    async with factory() as session:
        # users 表 RLS FORCE：登录处于未知租户上下文，需通过 login_lookup 策略
        # （0003 migration）按用户名查表。set_config 使用绑定参数，无注入风险。
        await session.execute(
            text("SELECT set_config('app.user_login', :username, true)"),
            {"username": req.username},
        )
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
        roles=list(user.roles),
        scopes=scopes,
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
    """刷新 access token（从旧 refresh token 恢复权限声明）。

    加固项：
    - token 旋转：每次刷新签发新 refresh token（新建 jti），旧 token 立即失效；
    - 重放检测：jti 首次消费通过 Redis `SET NX` 占用，重复提交旧 token 视为已泄露并拒绝；
    - 用户状态复核：实时校验账号仍存在且 ACTIVE（离职/禁用后旧 refresh token 即刻失效）。
    """
    payload = verify_token(req.refresh_token, expected_type="refresh")
    jti = payload.get("jti")
    if jti and not _consume_refresh_jti(str(jti)):
        raise UnauthorizedError("refresh token already used")
    roles = payload.get("roles") or []
    scopes = (payload.get("scope") or "").split()
    if not scopes:
        # 兼容旧 refresh token（未携带 scope）：按主账号角色派生默认 scope
        scopes = _default_scopes(roles)

    # 用户仍存在且 ACTIVE 才允许刷新（login_lookup 策略无需租户上下文）
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.user_login', :username, true)"),
            {"username": payload["sub"]},
        )
        user = (await session.execute(select(User).where(User.username == payload["sub"]))).scalar_one_or_none()
        if user is None or user.status != "ACTIVE":
            raise UnauthorizedError("user account is disabled or does not exist")

    tenant_id = payload["tenant_id"]
    access_token = create_access_token(
        subject=payload["sub"],
        tenant_id=tenant_id,
        roles=roles,
        scopes=scopes,
    )
    new_refresh = create_refresh_token(
        subject=payload["sub"],
        tenant_id=tenant_id,
        roles=roles,
        scopes=scopes,
    )
    return ApiResponse(data=Token(access_token=access_token, refresh_token=new_refresh, expires_in=1800))


def _consume_refresh_jti(jti: str) -> bool | None:
    """单次消费 refresh jti（原子 SET NX 占位）。

    True = 首次消费成功（允许续签）；False = 已被消费过（重放）；None = Redis 不可用（fail-open）。
    """
    from app.db.redis import get_redis

    try:
        ok = get_redis().set(f"refresh:jti:{jti}", "1", nx=True, ex=604800)
        return bool(ok)
    except Exception as exc:  # fail-open：Redis 故障不阻断登录续签
        logger.warning("refresh_jti_check_skipped", error=str(exc))
        return True


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
