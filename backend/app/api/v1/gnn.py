"""GNN 团伙检测路由（D05 §7）。

- GET /gnn/related/{node_id}：k-hop 邻居查询（实时同步，深度 ≤ 3）
- POST /gnn/embedding/{node_id}：GraphSAGE 嵌入
- POST /gnn/community-detection：触发团伙检测异步任务
- GET /gnn/community-detection/{task_id}：查询任务状态
- GET /gnn/community/{community_id}：查询团伙详情

说明：无本地表，所有请求透传到 GNN 推理服务（settings.gnn_service_url），
服务不可用时返回空结构占位。
"""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import get_tenant_id, require_scope
from app.config import settings
from app.core.exceptions import NotFoundError
from app.schemas.common import ApiResponse

router = APIRouter()

_GNN_TIMEOUT_SECONDS = 10.0


async def _call_gnn(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, dict]:
    """转发请求到 GNN 服务，网络异常时返回 (0, {})。"""
    url = f"{settings.gnn_service_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=_GNN_TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, params=params, json=json_body)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data
    except httpx.HTTPError:
        return 0, {}


@router.get("/related/{node_id}", response_model=ApiResponse[dict])
async def get_related(
    node_id: str,
    k: int = 2,
    edge_types: str | None = None,
    time_window_hours: int = 168,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询关联节点（k-hop 邻居，实时同步路径，深度 ≤ 3）。"""
    params = {"k": k, "time_window_hours": time_window_hours, "limit": limit}
    if edge_types:
        params["edge_types"] = edge_types
    status, data = await _call_gnn("GET", f"/v1/graph/related/{node_id}", params=params)
    if status == 0 or status >= 400:
        return ApiResponse(
            data={
                "seed_node": {"id": node_id, "type": "Account"},
                "k": k,
                "nodes": [],
                "edges": [],
                "total_nodes": 0,
                "evaluated_at_ms": 0,
            }
        )
    return ApiResponse(data=data)


@router.post("/embedding/{node_id}", response_model=ApiResponse[dict])
async def compute_embedding(
    node_id: str,
    body: dict | None = None,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:write")),
) -> ApiResponse[dict]:
    """计算 GraphSAGE 嵌入向量。"""
    status, data = await _call_gnn(
        "POST", f"/v1/graph/embedding/{node_id}", json_body=body or {}
    )
    if status == 0 or status >= 400:
        return ApiResponse(
            data={
                "node_id": node_id,
                "model_id": "gnn_graphsage_v1.2.0",
                "embedding": [],
                "dimension": 128,
                "latency_ms": 0,
            }
        )
    return ApiResponse(data=data)


@router.post("/community-detection", response_model=ApiResponse[dict])
async def community_detection(
    body: dict,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:write")),
) -> ApiResponse[dict]:
    """触发团伙检测异步任务（深度 1-3 跳）。"""
    status, data = await _call_gnn("POST", "/v1/graph/community", json_body=body)
    if status == 0 or status >= 400:
        return ApiResponse(
            data={
                "task_id": f"gnn_task_{uuid.uuid4()}",
                "status": "RUNNING",
                "estimated_seconds": 60,
                "callback_event": body.get("callback_event", "gang.detected"),
            }
        )
    return ApiResponse(data=data)


@router.get("/community-detection/{task_id}", response_model=ApiResponse[dict])
async def community_task_status(
    task_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙检测任务状态。"""
    status, data = await _call_gnn("GET", f"/v1/graph/community/{task_id}")
    if status == 0 or status >= 400:
        return ApiResponse(
            data={"task_id": task_id, "status": "RUNNING", "progress": 0.0}
        )
    return ApiResponse(data=data)


@router.get("/community/{community_id}", response_model=ApiResponse[dict])
async def get_community(
    community_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙详情（节点 + 边）。"""
    status, data = await _call_gnn("GET", f"/v1/graph/community/{community_id}")
    if status == 404:
        raise NotFoundError(f"community not found: {community_id}")
    if status == 0 or status >= 400:
        return ApiResponse(data={"community_id": community_id, "nodes": [], "edges": []})
    return ApiResponse(data=data)
