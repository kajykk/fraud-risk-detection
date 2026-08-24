"""GNN 团伙检测路由（D05 §7）。

- POST /gnn/related：k-hop 邻居查询（实时同步，深度 1-5）
- POST /gnn/embedding：GraphSAGE 嵌入
- POST /gnn/community-detection：触发团伙检测（GNN 侧同步执行）
- GET /gnn/community-detection/{task_id}：查询任务状态（占位，GNN 侧同步）
- GET /gnn/community/{community_id}：查询团伙详情（占位，GNN 侧同步）
说明：无本地表，请求透传到 GNN 推理服务（settings.gnn_service_url）。
为对齐 GNN 服务契约（gnn/main.py POST + JSON body），一律使用 POST 且
透传 tenant_id；服务不可用或 4xx/5xx 时：
- related / embedding：返回空结构占位（查询类，允许降级）；
- community-detection：返回 503 + status=FAILED（不伪造 task_id，
  避免调用方基于假任务号轮询一个永不存在的任务）。
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import get_tenant_id, require_scope
from app.config import settings
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.schemas.common import ApiResponse

router = APIRouter()

_GNN_TIMEOUT_SECONDS = 10.0
_GNN_MAX_K_HOPS = 5


async def _call_gnn(
    path: str,
    *,
    json_body: dict | None = None,
) -> tuple[int, dict]:
    """POST 转发请求到 GNN 服务，网络异常时返回 (0, {})。

    示例：/v1/graph/related + {"node_id": .., "k_hops": .., "tenant_id": ..}
    """
    url = f"{settings.gnn_service_url}{path}"
    headers = {}
    if settings.gnn_api_key:
        headers["X-Api-Key"] = settings.gnn_api_key
    try:
        async with httpx.AsyncClient(timeout=_GNN_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=json_body or {}, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data
    except httpx.HTTPError:
        return 0, {}


@router.post("/related", response_model=ApiResponse[dict])
async def get_related(
    body: dict,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询关联节点（k-hop，深度 1-5），透传 tenant_id 保证图数据隔离。"""
    node_id = body.get("node_id")
    if not node_id:
        return ApiResponse(
            data={"nodes": [], "edges": [], "k_hops": body.get("k", 2)}
        )
    k = max(1, min(int(body.get("k", body.get("k_hops", 2)) or 2), _GNN_MAX_K_HOPS))
    payload = {
        "node_id": str(node_id),
        "k_hops": k,
        "tenant_id": tenant_id,
    }
    status, data = await _call_gnn("/v1/graph/related", json_body=payload)
    if status == 0 or status >= 400:
        return ApiResponse(
            data={
                "center_node_id": node_id,
                "nodes": [],
                "edges": [],
                "k_hops": k,
                "latency_ms": 0,
            }
        )
    return ApiResponse(data=data)


@router.post("/embedding", response_model=ApiResponse[dict])
async def compute_embedding(
    body: dict,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:write")),
) -> ApiResponse[dict]:
    """计算 GraphSAGE 嵌入向量（透传 tenant_id）。"""
    node_id = body.get("node_id")
    if not node_id:
        return ApiResponse(data={"node_id": None, "embedding": [], "dim": 0})
    payload = {"node_id": str(node_id), "tenant_id": tenant_id}
    status, data = await _call_gnn("/v1/graph/embedding", json_body=payload)
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
    """触发团伙检测（透传 tenant_id 与可选 node_amounts/node_fraud_labels）。"""
    node_id = body.get("node_id")
    k = max(1, min(int(body.get("k_hops", 3) or 3), _GNN_MAX_K_HOPS))
    payload: dict = {
        "node_id": str(node_id) if node_id else "",
        "k_hops": k,
        "tenant_id": tenant_id,
    }
    for key in ("node_amounts", "node_fraud_labels"):
        if body.get(key) is not None:
            payload[key] = body[key]
    status, data = await _call_gnn("/v1/graph/community", json_body=payload)
    if status == 0 or status >= 400:
        # GNN 故障：如实返回 503 + FAILED，不伪造 task_id/RUNNING
        raise ServiceUnavailableError(
            f"gnn community detection unavailable (upstream status={status or 'network_error'})",
            data={
                "status": "FAILED",
                "node_id": node_id,
                "callback_event": body.get("callback_event", "gang.detected"),
            },
        )
    return ApiResponse(data=data)


@router.get("/community-detection/{task_id}", response_model=ApiResponse[dict])
async def community_task_status(
    task_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙检测任务状态。

    占位：GNN 侧为同步执行，任务状态由 community 响应包返回。
    """
    return ApiResponse(data={"task_id": task_id, "status": "RUNNING", "progress": 0.0})


@router.get("/community/{community_id}", response_model=ApiResponse[dict])
async def get_community(
    community_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("graph:read")),
) -> ApiResponse[dict]:
    """查询团伙详情（占位：GNN 侧暂无按 ID 查询接口）。"""
    if not community_id:
        raise NotFoundError("community not found")
    return ApiResponse(data={"community_id": community_id, "nodes": [], "edges": []})
