"""API Key 认证服务（D05 §2.2 / D03 §4.7）。

- 存储仅保留 SHA-256 哈希（key_hash），不落明文
- 查表依赖 api_keys 表的 api_key_lookup RLS 策略
  （SET LOCAL app.api_key_lookup = hash 后仅返回哈希匹配行）
"""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.tenant import ApiKey

logger = get_logger(__name__)


@dataclass
class ApiKeyInfo:
    """API Key 查表结果。"""

    api_key_id: str
    tenant_id: str
    merchant_id: str | None
    name: str
    scopes: list[str] = field(default_factory=list)
    ip_whitelist: list[str] = field(default_factory=list)


def hash_api_key(raw_key: str) -> str:
    """计算 API Key 的 SHA-256 哈希。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKeyService:
    """API Key 查表与校验。"""

    async def lookup(self, raw_key: str) -> ApiKeyInfo | None:
        """按哈希查表，返回有效（ACTIVE / 未吊销 / 未过期）的 Key 信息。

        返回 None 表示 Key 无效或不存在。
        """
        key_hash = hash_api_key(raw_key)
        factory = get_session_factory()
        async with factory() as session:
            # api_key_lookup RLS 策略：仅返回哈希匹配行（无需知道租户）
            # 注：asyncpg 不支持 SET 绑定参数，key_hash 为十六进制，可安全内联
            await session.execute(
                text(f"SET LOCAL app.api_key_lookup = '{key_hash}'"),
            )
            result = await session.execute(
                select(ApiKey).where(ApiKey.key_hash == key_hash)
            )
            row = result.scalar_one_or_none()
        if row is None:
            logger.warning("api_key_not_found", key_hash_prefix=key_hash[:8])
            return None

        if row.status != "ACTIVE" or row.revoked_at is not None:
            logger.warning("api_key_inactive", api_key_id=str(row.id))
            return None
        if row.expires_at is not None and row.expires_at < datetime.now(UTC):
            logger.warning("api_key_expired", api_key_id=str(row.id))
            return None

        return ApiKeyInfo(
            api_key_id=str(row.id),
            tenant_id=str(row.tenant_id),
            merchant_id=str(row.merchant_id) if row.merchant_id else None,
            name=row.name,
            scopes=list(row.scopes or []),
            ip_whitelist=list(row.ip_whitelist or []),
        )

    @staticmethod
    def ip_allowed(client_ip: str, ip_whitelist: list[str]) -> bool:
        """校验客户端 IP 是否在白名单内（空白名单 = 不限制）。"""
        if not ip_whitelist:
            return True
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        return any(
            addr in ipaddress.ip_network(cidr, strict=False)
            for cidr in ip_whitelist
        )


api_key_service = ApiKeyService()


__all__ = ["ApiKeyInfo", "ApiKeyService", "api_key_service", "hash_api_key"]
