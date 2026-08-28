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

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from app.api.deps import get_tenant_id, require_scope
from app.config import settings
from app.core.exceptions import FRDError, NotFoundError, ServiceUnavailableError
from app.schemas.common import ApiResponse

router = APIRouter()

_GNN_TIMEOUT_SECONDS = 10.0
_GNN_MAX_K_HOPS = 5

# 共享 HTTP 客户端（按事件循环缓存）：图查询为热路径，避免每请求 TCP 握手
_gnn_clients: dict[int, httpx.AsyncClient] = {}


def _build_gnn_client() -> httpx.AsyncClient:
    """返回共享 GNN HTTP 客户端（复用连接池，勿在调用方关闭）。"""
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        return httpx.AsyncClient(timeout=_GNN_TIMEOUT_SECONDS)
    client = _gnn_clients.get(loop_key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=_GNN_TIMEOUT_SECONDS)
        _gnn_clients[loop_key] = client
    return client


async def _parse_k_hops(value: Any, default: int) -> int:
    """解析并钳制 k_hops；非数字输入返回 400 而非 500。"""
    if value is None:
        return default
    try:
        return max(1, min(int(value), _GNN_MAX_K_HOPS))
    except (TypeError, ValueError) as exc:
        raise FRDError(
            f"invalid k_hops: {value!r}", code="INVALID_PARAMS", http_status=400
        ) from exc


async def close_shared_gnn_client() -> None:
    """关闭共享 GNN 客户端（应用关闭时调用）。"""
    while _gnn_clients:
        _, client = _gnn_clients.popitem()
        try:
            await client.aclose()
        except Exception:
            pass


async def _call_gnn(
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST 转发请求到 GNN 服务，网络异常时返回 (0, {})。

    示例：/v1/graph/related + {"node_id": .., "k_hops": .., "tenant_id": ..}
    """
    url = f"{settings.gnn_service_url}{path}"
    headers = {}
    if settings.gnn_api_key:
        headers["X-Api-Key"] = settings.gnn_api_key
    try:
        client = _build_gnn_client()
        response = await client.post(url, json=json_body or {}, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data
    except httpx.HTTPError:
        return 0, {}


@router.post("/related", response_model=ApiResponse[dict[str, Any]])
async def get_related(
    body: dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("graph:read")),
) -> ApiResponse[dict[str, Any]]:
    """查询关联节点（k-hop，深度 1-5），透传 tenant_id 保证图数据隔离。"""
    node_id = body.get("node_id")
    if not node_id:
        return ApiResponse(
            data={"nodes": [], "edges": [], "k_hops": body.get("k", 2)}
        )
    k = await _parse_k_hops(body.get("k", body.get("k_hops", 2)), default=2)
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


@router.post("/embedding", response_model=ApiResponse[dict[str, Any]])
async def compute_embedding(
    body: dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("graph:write")),
) -> ApiResponse[dict[str, Any]]:
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


@router.post("/community-detection", response_model=ApiResponse[dict[str, Any]])
async def community_detection(
    body: dict[str, Any],
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("graph:write")),
) -> ApiResponse[dict[str, Any]]:
    """触发团伙检测（透传 tenant_id 与可选 node_amounts/node_fraud_labels）。"""
    node_id = body.get("node_id")
    k = await _parse_k_hops(body.get("k_hops", 3), default=3)
    payload: dict[str, Any] = {
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


@router.get("/community-detection/{task_id}", response_model=ApiResponse[dict[str, Any]])
async def community_task_status(
    task_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("graph:read")),
) -> ApiResponse[dict[str, Any]]:
    """查询团伙检测任务状态。

    GNN 服务为同步执行：完整结果已在 POST /gnn/community-detection 的
    响应中直接返回，不存在独立任务队列。此端点如实返回 501——
    此前恒报 RUNNING 占位，会诱导调用方轮询一个永不变化的状态。
    """
    raise FRDError(
        "community detection is synchronous; "
        "use POST /api/v1/gnn/community-detection response directly",
        code="NOT_IMPLEMENTED",
        http_status=501,
        data={"task_id": task_id},
    )


@router.get("/community/{community_id}", response_model=ApiResponse[dict[str, Any]])
async def get_community(
    community_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("graph:read")),
) -> ApiResponse[dict[str, Any]]:
    """查询团伙详情（占位：GNN 侧暂无按 ID 查询接口）。"""
    if not community_id:
        raise NotFoundError("community not found")
    return ApiResponse(data={"community_id": community_id, "nodes": [], "edges": []})
