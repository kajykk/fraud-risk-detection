"""认证路由（D05 §3）。

- POST /auth/login：用户名密码登录（users 表校验）
- POST /auth/token：OAuth2 client_credentials（api_keys 表校验）
- POST /auth/refresh：刷新 token
- GET /auth/me：当前用户信息
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, text

from app.api.deps import get_current_user
from app.config import settings
from app.core.exceptions import FRDError, UnauthorizedError
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

# 预生成 dummy bcrypt 哈希（对应随机口令，永不匹配）：用户不存在时仍执行
# 一次等价校验，抹平响应时间差（防用户名枚举侧信道）
_DUMMY_PASSWORD_HASH = "$2b$12$lD/coWfODt19r//JfYRbLO58kvw8pcdHr/52vdY2GP9ojVzNr4gHG"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Refresh Token 下发为 HttpOnly Cookie（XSS 不可读）。

    - HttpOnly：脚本无法读取，XSS 只能盗用短期 access token；
    - SameSite=Strict：跨站请求不携带，配合 POST 刷新端点防 CSRF；
    - Secure：prod 环境强制 HTTPS-only；
    - Path 限定认证路径，其他 API 请求不携带。
    """
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.is_prod,
        samesite="strict",
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """登出/吊销时删除 Refresh Cookie。"""
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
    )


@router.post("/login", response_model=ApiResponse[Token])
async def login(req: LoginRequest, response: Response) -> ApiResponse[Token]:
    """用户名密码登录。

    Refresh Token 仅通过 HttpOnly Cookie 下发（响应体不再携带，
    XSS 即使得手 access token 也无法续期）。
    """
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
        if user is None:
            # 用户不存在：仍执行一次 bcrypt 校验，避免响应时间差暴露用户名
            verify_password(req.password, _DUMMY_PASSWORD_HASH)
            raise UnauthorizedError("invalid username or password")
        if not verify_password(req.password, user.password_hash):
            raise UnauthorizedError("invalid username or password")
        if user.status != "ACTIVE":
            raise UnauthorizedError(f"user account {user.status.lower()}")
        user.last_login_at = datetime.now(UTC)
        await session.commit()

    # 安全：scope 一律按角色派生，不接受客户端声明（防越权提升）
    scopes = _default_scopes(user.roles)
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
    _set_refresh_cookie(response, refresh)
    return ApiResponse(data=Token(access_token=access_token, expires_in=1800))


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
async def refresh_token(
    req: RefreshTokenRequest,
    request: Request,
    response: Response,
) -> ApiResponse[Token]:
    """刷新 access token（旋转 + 重放检测）。

    Refresh token 来源优先级：
    1. HttpOnly Cookie（推荐，前端标准路径）；
    2. 请求体 refresh_token（兼容 API 直连客户端 / 旧版本前端）。

    加固项：
    - token 旋转：每次刷新签发新 refresh token（新建 jti），旧 token 立即失效，
      新 token 同步写入 Cookie；
    - 重放检测：jti 首次消费通过 Redis `SET NX` 占用，重复提交旧 token 视为已泄露并拒绝；
    - 用户状态复核：实时校验账号仍存在且 ACTIVE（离职/禁用后旧 refresh token 即刻失效）。
    """
    raw_refresh = req.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not raw_refresh:
        raise UnauthorizedError("refresh token missing")
    payload = verify_token(raw_refresh, expected_type="refresh")
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
    # 旋转后的新 refresh token 同步写入 Cookie（旧的随响应失效）
    _set_refresh_cookie(response, new_refresh)
    return ApiResponse(data=Token(access_token=access_token, expires_in=1800))


@router.post("/logout", response_model=ApiResponse[dict[str, Any]])
async def logout(response: Response) -> ApiResponse[dict[str, Any]]:
    """登出：清除 Refresh Cookie（access token 由客户端自行丢弃，短期自然过期）。"""
    _clear_refresh_cookie(response)
    return ApiResponse(data={"status": "ok"})


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
async def me(user: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[UserInfo]:
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
async def profile(user: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[UserInfo]:
    """当前用户信息（/auth/profile 别名，兼容前端调用）。"""
    return ApiResponse(
        data=UserInfo(
            sub=user["sub"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", []),
            scope=user.get("scope"),
        )
    )


_WS_TICKET_TTL_SECONDS = 30


@router.post("/ws-ticket", response_model=ApiResponse[dict[str, Any]])
async def create_ws_ticket(user: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[dict[str, Any]]:
    """签发一次性 WebSocket 连接票据（30s 有效，GETDEL 单次消费）。

    安全动机：JWT 拼在 WS URL query 中会泄漏到访问日志/代理日志/浏览器历史；
    改为先 POST 换取短时效一次性 ticket，再用 ticket 建立连接。
    """
    from app.db.redis import get_redis

    ticket = f"wst_{secrets.token_urlsafe(32)}"
    try:
        await get_redis().set(
            f"ws_ticket:{ticket}",
            json.dumps({"tenant_id": str(user["tenant_id"]), "sub": str(user["sub"])}),
            ex=_WS_TICKET_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning("ws_ticket_issue_failed", error=str(exc))
        raise FRDError(
            "ticket service unavailable",
            code="SERVICE_UNAVAILABLE",
            http_status=503,
        ) from exc
    return ApiResponse(data={"ticket": ticket, "expires_in": _WS_TICKET_TTL_SECONDS})


def _default_scopes(roles: list[str]) -> list[str]:
    """按角色返回默认 scope（D05 §3.2 角色矩阵）。"""
    role_scopes = {
        "TENANT_ADMIN": ["admin:*"],
        "MERCHANT_ADMIN": ["transaction:score", "transaction:read", "webhook:read", "webhook:write"],
        "RISK_ANALYST": [
            "transaction:score",
            "transaction:read",
            "case:read",
            "case:write",
            "graph:read",
            "graph:write",
        ],
        "RISK_MANAGER": [
            "transaction:score",
            "transaction:read",
            "case:read",
            "case:write",
            "rule:read",
            "rule:write",
            "graph:read",
            "graph:write",
        ],
        "AUDITOR": ["audit:read", "webhook:read"],
        "COMPLIANCE_OFFICER": ["pipl:read", "pipl:write", "case:read"],
        "DEVOPS_OPS": ["model:read", "model:write", "kill_switch:write"],
    }
    scopes: list[str] = []
    for role in roles:
        scopes.extend(role_scopes.get(role, []))
    return list(dict.fromkeys(scopes))


__all__ = ["_default_scopes", "router"]
