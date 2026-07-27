"""Neo4j driver（D03 V1.1 §1.3 neo4j 5.x）。

用于：
- GNN k-hop 邻居查询（实时评分主路径，P99 < 2s）
- GraphSAGE 嵌入计算
- 团伙检测（Louvain/Leiden 社区发现）
"""

from __future__ import annotations

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_driver: AsyncDriver | None = None


async def init_neo4j() -> AsyncDriver:
    """应用启动时初始化 Neo4j driver。"""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        # 验证连接
        try:
            await _driver.verify_connectivity()
            logger.info("neo4j_initialized", uri=settings.neo4j_uri)
        except Exception as exc:
            logger.error("neo4j_connect_failed", error=str(exc))
            raise
    return _driver


async def close_neo4j() -> None:
    """应用关闭时释放 Neo4j driver。"""
    global _driver
    if _driver is not None:
        await _driver.close()
        logger.info("neo4j_closed")
    _driver = None


def get_neo4j() -> AsyncDriver:
    """返回 Neo4j driver 单例（必须在 init_neo4j 之后调用）。"""
    if _driver is None:
        raise RuntimeError("Neo4j not initialized; call init_neo4j() first")
    return _driver


async def check_neo4j_health() -> bool:
    """健康检查：RETURN 1。"""
    try:
        driver = get_neo4j()
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run("RETURN 1 AS n")
            record = await result.single()
            return record is not None and record["n"] == 1
    except Exception as exc:
        logger.error("neo4j_health_check_failed", error=str(exc))
        return False


__all__ = ["check_neo4j_health", "close_neo4j", "get_neo4j", "init_neo4j"]
