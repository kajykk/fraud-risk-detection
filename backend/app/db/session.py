"""异步 SQLAlchemy engine + session factory（D03 V1.1 §4.7 多租户 RLS）。

- 连接池配置：pool_size + max_overflow 从环境变量读取
- 每次请求通过 set_tenant_id 在连接上 SET LOCAL app.tenant_id（ADR-015）
- 连接归还前 RESET app.tenant_id
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 全局 async engine（应用启动时创建）
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回全局 async engine（懒初始化）。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.async_dsn,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回全局 session factory（懒初始化）。"""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


async def init_engine() -> None:
    """应用启动时初始化 engine + session factory。"""
    get_engine()
    get_session_factory()
    logger.info("db_engine_initialized", dsn_host=settings.postgres_host)


async def close_engine() -> None:
    """应用关闭时释放 engine。"""
    global _engine, _async_session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("db_engine_closed")
    _engine = None
    _async_session_factory = None


async def set_tenant_id(session: AsyncSession, tenant_id: str) -> None:
    """在当前连接上 SET LOCAL app.tenant_id（ADR-015 RLS 强制隔离）。"""
    await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})


async def reset_tenant_id(session: AsyncSession) -> None:
    """连接归还前 RESET app.tenant_id，避免跨租户串号（D04 §9.4）。"""
    await session.execute(text("RESET app.tenant_id"))


@asynccontextmanager
async def session_scope(tenant_id: str | None = None) -> AsyncIterator[AsyncSession]:
    """提供事务范围的 session 上下文管理器。

    Args:
        tenant_id: 租户 ID；若提供则 SET LOCAL app.tenant_id 启用 RLS。
    """
    factory = get_session_factory()
    async with factory() as session:
        if tenant_id is not None:
            await set_tenant_id(session, tenant_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if tenant_id is not None:
                await reset_tenant_id(session)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供 session（不带 tenant_id，由中间件设置）。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_health() -> bool:
    """健康检查：SELECT 1。"""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as exc:
        logger.error("db_health_check_failed", error=str(exc))
        return False


__all__ = [
    "check_db_health",
    "close_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
    "init_engine",
    "reset_tenant_id",
    "session_scope",
    "set_tenant_id",
]
