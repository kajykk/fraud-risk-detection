"""认证 schemas（D05 §3）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    """POST /auth/token 请求体。"""

    grant_type: str = Field(default="client_credentials")
    client_id: str
    client_secret: str
    scope: str | None = None


class Token(BaseModel):
    """Token 响应。"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 1800
    refresh_token: str | None = None
    scope: str | None = None


class RefreshTokenRequest(BaseModel):
    """POST /auth/refresh 请求体。"""

    refresh_token: str


class LoginRequest(BaseModel):
    """POST /auth/login 请求体（用户名密码登录）。"""

    username: str
    password: str
    scopes: list[str] | None = None


class UserInfo(BaseModel):
    """GET /auth/me 响应。"""

    sub: str
    tenant_id: str
    roles: list[str]
    scope: str | None = None


__all__ = ["LoginRequest", "RefreshTokenRequest", "Token", "TokenRequest", "UserInfo"]
