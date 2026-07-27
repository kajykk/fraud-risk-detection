"""Redis 异步客户端（D03 V1.1 §1.3 redis[asyncio]）。

用途：
- 评分缓存（score_cache:{tenant}:{tx_hash}，TTL 24h，D03 §4.1）
- 限流滑动窗口（rate_limit:{tenant}:{endpoint}）
- 模态历史分数滑动窗口（ml:{tenant}:{modality}:recent_scores，ADR-011）
- Kill Switch 状态热更新（pubsub，D03 §4.8）
- 审计 sequence_no 预分配（audit_seq:{tenant_id}，D04 §3.7）
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None


async def init_redis() -> Redis:
    """应用启动时初始化 Redis 连接池。"""
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
        logger.info("redis_initialized", host=settings.redis_host, port=settings.redis_port)
    return _redis


async def close_redis() -> None:
    """应用关闭时释放 Redis 连接池。"""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        logger.info("redis_closed")
    _redis = None


def get_redis() -> Redis:
    """返回 Redis 客户端单例（必须在 init_redis 之后调用）。"""
    if _redis is None:
        raise RuntimeError("Redis not initialized; call init_redis() first")
    return _redis


async def check_redis_health() -> bool:
    """健康检查：PING。"""
    try:
        from app.db.redis import get_redis

        return bool(await get_redis().ping())
    except Exception as exc:
        logger.error("redis_health_check_failed", error=str(exc))
        return False


__all__ = ["check_redis_health", "close_redis", "get_redis", "init_redis"]
