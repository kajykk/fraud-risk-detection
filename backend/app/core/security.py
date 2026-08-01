"""安全模块：JWT 生成/验证 + 密码哈希。

依据：
- D03 V1.1 §1.3 技术栈：python-jose[cryptography] + passlib[bcrypt]
- D05 V1.1 §3.2 JWT 结构：sub/tenant_id/roles/scope/iat/exp/jti
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# 密码哈希上下文（bcrypt）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token 类型
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(raw_password: str) -> str:
    """对明文密码做 bcrypt 哈希。"""
    return pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed: str) -> bool:
    """校验明文密码与 bcrypt 哈希是否匹配。"""
    return pwd_context.verify(raw_password, hashed)


def create_access_token(
    subject: str,
    tenant_id: str,
    roles: list[str],
    scopes: list[str],
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """生成 access token（短期，默认 30 分钟）。"""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": " ".join(scopes),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, tenant_id: str) -> str:
    """生成 refresh token（长期，默认 7 天）。"""
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "type": REFRESH_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """解码并验证 JWT。验证失败抛 JWTError。"""
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    return payload


def verify_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """解码 + 校验 token 类型。失败抛 JWTError。"""
    payload = decode_token(token)
    if expected_type and payload.get("type") != expected_type:
        raise JWTError(f"unexpected token type: expected={expected_type}, got={payload.get('type')}")
    return payload


__all__ = [
    "ACCESS_TOKEN_TYPE",
    "REFRESH_TOKEN_TYPE",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
    "verify_token",
]
