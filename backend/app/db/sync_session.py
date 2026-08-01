"""同步 SQLAlchemy engine + session（Celery Worker 用）。

异步 FastAPI 侧使用 app.db.session（asyncpg）；Celery 任务为同步模型，
需要独立的同步 engine（psycopg2）。
"""

from __future__ import annotations

import uuid as uuidlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_sync_engine() -> Engine:
    """返回全局同步 engine（懒初始化）。"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.sync_dsn,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_sync_factory() -> sessionmaker[Session]:
    """返回全局同步 session factory（懒初始化）。"""
    global _factory
    if _factory is None:
        _factory = sessionmaker(
            bind=get_sync_engine(),
            expire_on_commit=False,
        )
    return _factory


@contextmanager
def sync_session_scope(tenant_id: str | None = None) -> Iterator[Session]:
    """提供同步事务范围的 session 上下文管理器（RLS 隔离）。

    Args:
        tenant_id: 租户 ID；提供则 SET LOCAL app.tenant_id 启用 RLS。
    """
    factory = get_sync_factory()
    session = factory()
    try:
        if tenant_id is not None:
            uuidlib.UUID(str(tenant_id))  # 校验格式，防止 SQL 注入
            session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["get_sync_engine", "get_sync_factory", "sync_session_scope"]
