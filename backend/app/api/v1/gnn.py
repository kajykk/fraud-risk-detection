"""GNN 团伙检测路由（D05 §7）。

- GET /gnn/related/{node_id}：k-hop 邻居查询（实时同步，深度 ≤ 3）
- POST /gnn/embedding/{node_id}：GraphSAGE 嵌入
- POST /gnn/community-detection：触发团伙检测异步任务
- GET /gnn/community-detection/{task_id}：查询任务状态
- GET /gnn/community/{community_id}：查询团伙详情
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("/related/{node_id}", response_model=ApiResponse[dict])
async def get_related(
    node_id: str,
    k: int = 2,
    edge_types: str | None = None,
    time_window_hours: int = 168,
    limit: int = 100,
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询关联节点（k-hop 邻居，实时同步路径，深度 ≤ 3）。"""
    # TODO: 调用 Neo4j Cypher 查询
    return ApiResponse(data={
        "seed_node": {"id": node_id, "type": "Account"},
        "k": k,
        "nodes": [],
        "edges": [],
        "total_nodes": 0,
        "evaluated_at_ms": 0,
    })


@router.post("/embedding/{node_id}", response_model=ApiResponse[dict])
async def compute_embedding(
    node_id: str,
    body: dict | None = None,
    _user: dict = Depends(require_scope("graph:write")),
) -> ApiResponse[dict]:
    """计算 GraphSAGE 嵌入向量。"""
    # TODO: 调用 GNN 模型推理
    return ApiResponse(data={
        "node_id": node_id,
        "model_id": "gnn_graphsage_v1.2.0",
        "embedding": [],
        "dimension": 128,
        "latency_ms": 0,
    })


@router.post("/community-detection", response_model=ApiResponse[dict])
async def community_detection(
    body: dict,
    _user: dict = Depends(require_scope("graph:write")),
) -> ApiResponse[dict]:
    """触发团伙检测异步任务（深度 1-3 跳）。"""
    task_id = f"gnn_task_{uuid.uuid4()}"
    # TODO: 投递 Celery 任务
    return ApiResponse(data={
        "task_id": task_id,
        "status": "RUNNING",
        "estimated_seconds": 60,
        "callback_event": body.get("callback_event", "gang.detected"),
    })


@router.get("/community-detection/{task_id}", response_model=ApiResponse[dict])
async def community_task_status(
    task_id: str,
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙检测任务状态。"""
    # TODO: 查 Celery result backend
    return ApiResponse(data={"task_id": task_id, "status": "RUNNING", "progress": 0.0})


@router.get("/community/{community_id}", response_model=ApiResponse[dict])
async def get_community(
    community_id: str,
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙详情（节点 + 边）。"""
    # TODO: 查 Neo4j
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"community not found: {community_id}")
