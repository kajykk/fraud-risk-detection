"""FastAPI GNN 服务入口（端口 8502，D03 §2.2）。

端点：
- /health: 健康检查
- /v1/graph/related: k 跳关联节点查询
- /v1/graph/embedding: 节点 GraphSAGE embedding
- /v1/graph/community: 团伙检测
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .community.detector import Community
from .config import settings
from .graph_service import GNNGraphService, Graph
from .models.graphsage import GraphSAGE

logger = structlog.get_logger(__name__)


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """服务间鉴权：X-Api-Key 须与 GNN_API_KEY 一致（恒定时间比较）。

    未配置 GNN_API_KEY 时鉴权关闭（仅开发/本地；生产必须配置）。
    """
    expected = settings.server.api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid_api_key")


_service: GNNGraphService | None = None
_graphsage: GraphSAGE | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：连接 Neo4j + Redis + 加载 GraphSAGE。"""
    global _service, _graphsage
    _graphsage = GraphSAGE(
        in_channels=settings.graphsage.in_channels,
        hidden_channels=list(settings.graphsage.hidden_channels),
        out_channels=settings.graphsage.out_channels,
        dropout=settings.graphsage.dropout,
    )
    try:
        _graphsage.build()
        if os.path.exists(settings.model_path):
            _graphsage.load(settings.model_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gnn.main.graphsage.load_failed", error=str(exc))

    redis_client = None
    try:
        if os.getenv("REDIS_URL"):
            import redis.asyncio as aioredis  # type: ignore

            redis_client = aioredis.from_url(settings.redis.url, decode_responses=True)
            await redis_client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("gnn.main.redis.unavailable", error=str(exc))
        redis_client = None

    neo4j_driver = None
    try:
        from neo4j import GraphDatabase  # type: ignore

        neo4j_driver = GraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password),
            max_connection_pool_size=settings.neo4j.max_connection_pool_size,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("gnn.main.neo4j.unavailable", error=str(exc))
        neo4j_driver = None

    _service = GNNGraphService(
        neo4j_driver=neo4j_driver,
        redis_client=redis_client,
        graphsage=_graphsage if _graphsage._model is not None else None,
    )
    logger.info("gnn.main.started", port=settings.server.port)
    yield

    if neo4j_driver is not None:
        neo4j_driver.close()
    if redis_client is not None:
        await redis_client.close()
    logger.info("gnn.main.stopped")


class RelatedRequest(BaseModel):
    node_id: str = Field(..., description="中心节点 ID")
    k_hops: int = Field(default=2, ge=1, le=5)
    tenant_id: str = Field(default="")


class EmbeddingRequest(BaseModel):
    node_id: str = Field(...)
    tenant_id: str = Field(default="")


class CommunityRequest(BaseModel):
    node_id: str = Field(...)
    k_hops: int = Field(default=3, ge=1, le=5)
    tenant_id: str = Field(default="")
    node_amounts: dict[str, float] | None = None
    node_fraud_labels: dict[str, bool] | None = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="FRD GNN Service",
        description="图查询 + GraphSAGE + 团伙检测（D03 §4.4）",
        version="1.1.0",
        lifespan=lifespan,
    )

    if settings.server.enable_prometheus:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore

            Instrumentator().instrument(app).expose(app, include_in_schema=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gnn.main.prometheus.disabled", error=str(exc))

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "gnn",
            "version": "1.1.0",
            "graphsage_loaded": _graphsage is not None and _graphsage._model is not None,
            "service_ready": _service is not None,
        }

    @app.post("/v1/graph/related", dependencies=[Depends(require_api_key)])
    async def query_related(req: RelatedRequest) -> dict[str, Any]:
        if _service is None:
            raise HTTPException(status_code=503, detail="service_not_ready")
        graph: Graph = await _service.query_related(
            node_id=req.node_id, k_hops=req.k_hops, tenant_id=req.tenant_id
        )
        return {
            "center_node_id": graph.center_node_id,
            "nodes": graph.nodes,
            "edges": graph.edges,
            "k_hops": graph.k_hops,
            "latency_ms": graph.latency_ms,
        }

    @app.post("/v1/graph/embedding", dependencies=[Depends(require_api_key)])
    async def compute_embedding(req: EmbeddingRequest) -> dict[str, Any]:
        if _service is None:
            raise HTTPException(status_code=503, detail="service_not_ready")
        embedding: list[float] = await _service.compute_embedding(
            node_id=req.node_id, tenant_id=req.tenant_id
        )
        return {"node_id": req.node_id, "embedding": embedding, "dim": len(embedding)}

    @app.post("/v1/graph/community", dependencies=[Depends(require_api_key)])
    async def detect_community(req: CommunityRequest) -> dict[str, Any]:
        if _service is None:
            raise HTTPException(status_code=503, detail="service_not_ready")
        community: Community | None = await _service.detect_community(
            node_id=req.node_id,
            k_hops=req.k_hops,
            tenant_id=req.tenant_id,
            node_amounts=req.node_amounts,
            node_fraud_labels=req.node_fraud_labels,
        )
        if community is None:
            return {"found": False, "community": None}
        return {
            "found": True,
            "community": {
                "community_id": community.community_id,
                "members": community.members,
                "stats": {
                    "member_count": community.stats.member_count,
                    "total_amount": community.stats.total_amount,
                    "fraud_count": community.stats.fraud_count,
                    "fraud_rate": community.stats.fraud_rate,
                    "risk_score": community.stats.risk_score,
                    "is_fraud_gang": community.stats.is_fraud_gang,
                },
            },
        }

    return app


app = create_app()


def main() -> None:
    """uvicorn 入口（端口 8502）。"""
    import uvicorn  # type: ignore

    uvicorn.run(
        "gnn.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        log_config=None,
    )


if __name__ == "__main__":
    main()
