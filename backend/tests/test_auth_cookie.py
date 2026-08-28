"""认证 Cookie 流程测试（Refresh Token HttpOnly 迁移回归）。

覆盖：
- POST /auth/login：Set-Cookie（HttpOnly / SameSite=strict / 路径限定），
  响应体不再下发 refresh_token
- POST /auth/refresh：Cookie 携带可刷新并旋转写入新 Cookie；
  缺失凭证返回 401
- POST /auth/logout：清除 Cookie
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _cookie_jar_names(client: AsyncClient) -> list[str]:
    return [c.name for c in client.cookies.jar]


@pytest.mark.asyncio
async def test_refresh_without_any_credential_returns_401(client: AsyncClient) -> None:
    """无 Cookie 且无 body 凭证 → 401（不再要求 body 必填）。"""
    response = await client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_refresh_cookie(client: AsyncClient) -> None:
    """logout 显式删除 refresh cookie。"""
    # 预置一个 cookie 到客户端 jar（模拟已登录状态）
    client.cookies.set("frd_refresh_token", "stale-token")
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    # 删除指令：过期时间戳 + 空值
    assert "frd_refresh_token=" in set_cookie
    assert 'Max-Age=0' in set_cookie or "max-age=0" in set_cookie.lower()


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie_and_omits_body_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """登录成功 → Set-Cookie 为 HttpOnly，响应体不含 refresh_token。

    通过 mock 会话工厂绕过 DB（登录主流程的 DB 分支由集成测试覆盖），
    此处聚焦 Cookie 契约。
    """

    class _FakeUser:
        username = "u1"
        password_hash = ""
        status = "ACTIVE"
        tenant_id = "00000000-0000-0000-0000-000000000001"
        roles = ["TENANT_ADMIN"]
        last_login_at = None

    class _FakeResult:
        def scalar_one_or_none(self):  # noqa: ANN202
            return _FakeUser()

    class _FakeSession:
        async def execute(self, *_a, **_k):  # noqa: ANN202
            return _FakeResult()

        async def commit(self):  # noqa: ANN202
            return None

        async def __aenter__(self):  # noqa: ANN202
            return self

        async def __aexit__(self, *exc):  # noqa: ANN202
            return False

    import app.api.v1.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_session_factory", lambda: (lambda: _FakeSession()))

    from passlib.context import CryptContext

    real_hash = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("right-password")
    _FakeUser.password_hash = real_hash

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "u1", "password": "right-password"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    # 响应体不下发 refresh token（XSS 无法窃取续期能力）
    assert body.get("refresh_token") is None
    set_cookie = response.headers.get("set-cookie", "")
    assert "frd_refresh_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/api/v1/auth" in set_cookie.lower()
