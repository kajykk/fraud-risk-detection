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
from typing import Any

from sqlalchemy import select, text

from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.models.tenant import ApiKey

logger = get_logger(__name__)

# 缓存未命中哨兵（区分"查过但无效"与"没查过"）
_MISS = object()


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
    """API Key 查表与校验。

    认证位于每请求热路径（含 ApiKey 的所有请求），
    查表结果缓存 Redis（TTL 60s，负结果 10s），DB 仅回源；
    吊销/更新的陈旧窗口上限即 TTL。
    """

    POSITIVE_TTL_SECONDS = 60
    NEGATIVE_TTL_SECONDS = 10

    def __init__(self) -> None:
        from app.core.logging import get_logger

        self._logger = get_logger(__name__)

    async def _cache_get(self, cache_key: str) -> Any:
        """读取缓存：dict（有效 Key）/ None（负缓存：无效 Key）/ _MISS（未命中）。"""
        try:
            from app.db.redis import get_redis

            raw = await get_redis().get(cache_key)
        except Exception as exc:  # fail-open：Redis 故障直接回源 DB
            self._logger.warning("api_key_cache_read_failed", error=str(exc))
            return _MISS
        if raw is None:
            return _MISS
        if raw == "":
            return None  # 负缓存：Key 无效
        import json

        try:
            return json.loads(raw)
        except ValueError:
            return _MISS

    async def _cache_set(self, cache_key: str, info: ApiKeyInfo | None) -> None:
        try:
            import json

            from app.db.redis import get_redis

            redis = get_redis()
            if info is None:
                await redis.set(cache_key, "", ex=self.NEGATIVE_TTL_SECONDS)
            else:
                payload = json.dumps(
                    {
                        "api_key_id": info.api_key_id,
                        "tenant_id": info.tenant_id,
                        "merchant_id": info.merchant_id,
                        "name": info.name,
                        "scopes": info.scopes,
                        "ip_whitelist": info.ip_whitelist,
                    }
                )
                await redis.set(cache_key, payload, ex=self.POSITIVE_TTL_SECONDS)
        except Exception as exc:
            self._logger.warning("api_key_cache_write_failed", error=str(exc))

    async def lookup(self, raw_key: str) -> ApiKeyInfo | None:
        """按哈希查表，返回有效（ACTIVE / 未吊销 / 未过期）的 Key 信息。

        返回 None 表示 Key 无效或不存在。
        """
        key_hash = hash_api_key(raw_key)
        cache_key = f"apikey:{key_hash}"

        cached = await self._cache_get(cache_key)
        if cached is not _MISS:
            if cached is None:
                self._logger.warning("api_key_not_found_cached", key_hash_prefix=key_hash[:8])
                return None
            return ApiKeyInfo(**cached)

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
            await self._cache_set(cache_key, None)
            return None

        info: ApiKeyInfo | None = None
        if row.status != "ACTIVE" or row.revoked_at is not None:
            logger.warning("api_key_inactive", api_key_id=str(row.id))
        elif row.expires_at is not None and row.expires_at < datetime.now(UTC):
            logger.warning("api_key_expired", api_key_id=str(row.id))
        else:
            info = ApiKeyInfo(
                api_key_id=str(row.id),
                tenant_id=str(row.tenant_id),
                merchant_id=str(row.merchant_id) if row.merchant_id else None,
                name=row.name,
                scopes=list(row.scopes or []),
                ip_whitelist=list(row.ip_whitelist or []),
            )

        await self._cache_set(cache_key, info)
        return info

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
