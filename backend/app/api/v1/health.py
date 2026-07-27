"""健康检查路由（D05 §1 + D03 §7）。

- GET /health：liveness（进程存活）
- GET /live：liveness 别名
- GET /ready：readiness（检查 DB/Redis/Neo4j）
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.neo4j import check_neo4j_health
from app.db.redis import check_redis_health
from app.db.session import check_db_health

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str = "1.1.0"


class ReadyResponse(BaseModel):
    status: str
    version: str = "1.1.0"
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness 探针（进程存活）。"""
    return HealthResponse(status="ok")


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Liveness 别名。"""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness 探针（检查依赖服务）。"""
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    neo4j_ok = await check_neo4j_health()

    checks = {
        "postgres": "ok" if db_ok else "fail",
        "redis": "ok" if redis_ok else "fail",
        "neo4j": "ok" if neo4j_ok else "fail",
    }
    all_ok = all(checks.values())
    return ReadyResponse(status="ok" if all_ok else "degraded", checks=checks)
