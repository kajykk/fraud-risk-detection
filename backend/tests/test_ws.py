"""WebSocket 实时推送端点测试（D05 §2.8）。

覆盖：
- JWT 缺失 / 无效 / refresh 类型 token → 握手拒绝（WebSocketDisconnect）
- 有效连接收到同租户事件（完整 WsMessage 结构）
- 跨租户事件不转发
- 心跳：{"type":"ping"} → {"type":"pong"}（与前端 websocket.ts 对齐）
- subscribe 事件类型过滤

使用 starlette TestClient 的 WebSocket 会话（不走 lifespan，不依赖
Redis/PG）；广播经会话 portal 调度到端点事件循环，线程安全。
"""

from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import (
    create_access_token,
    create_refresh_token,
)
from app.services.ws_events import manager

TENANT_A = "00000000-0000-0000-0000-00000000000a"
TENANT_B = "00000000-0000-0000-0000-00000000000b"


def _access_token(tenant_id: str) -> str:
    return create_access_token(
        subject="ws-user",
        tenant_id=tenant_id,
        roles=["RISK_ANALYST"],
        scopes=["transaction:read"],
    )


def _event(tenant_id: str, event_type: str = "transaction.shap_ready") -> dict:
    """构造完整 WsMessage 结构事件（对齐前端接口）。"""
    return {
        "event_id": f"evt_{uuid.uuid4()}",
        "event_type": event_type,
        "tenant_id": tenant_id,
        "occurred_at": "2026-08-24T00:00:00+00:00",
        "data": {"hello": "world"},
    }


def _connect(client: TestClient, tenant_id: str):
    token = _access_token(tenant_id)
    return client.websocket_connect(f"/api/v1/ws?access_token={token}")


# --------------------------------------------------------------------------- #
# 握手鉴权
# --------------------------------------------------------------------------- #
def test_ws_missing_token_rejected(app) -> None:
    """缺失 access_token 应拒绝握手。"""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws"):
            pass


def test_ws_invalid_token_rejected(app) -> None:
    """无效 JWT 应拒绝握手。"""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws?access_token=not-a-jwt"):
            pass


def test_ws_refresh_token_rejected(app) -> None:
    """refresh 类型 token 不可用于 WS 接入（仅接受 access）。"""
    refresh = create_refresh_token(
        subject="ws-user",
        tenant_id=TENANT_A,
        roles=["RISK_ANALYST"],
        scopes=["transaction:read"],
    )
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/ws?access_token={refresh}"):
            pass


# --------------------------------------------------------------------------- #
# 事件转发
# --------------------------------------------------------------------------- #
def test_ws_same_tenant_event_forwarded(app) -> None:
    """有效连接应收到同租户事件（完整 WsMessage 结构原样转发）。"""
    client = TestClient(app)
    event = _event(TENANT_A)
    with _connect(client, TENANT_A) as ws:
        ws.portal.call(manager.broadcast, TENANT_A, event)
        received = ws.receive_json()
    assert received == event
    assert set(received.keys()) == {
        "event_id",
        "event_type",
        "tenant_id",
        "occurred_at",
        "data",
    }


def test_ws_cross_tenant_not_forwarded(app) -> None:
    """跨租户事件不转发：先广播他租户事件再广播本租户标记事件，
    首帧必须是标记事件（FIFO 队列保证跨租户消息未入队）。"""
    client = TestClient(app)
    other_tenant_event = _event(TENANT_B, "case.created")
    marker = _event(TENANT_A, "case.created")
    with _connect(client, TENANT_A) as ws:
        ws.portal.call(manager.broadcast, TENANT_B, other_tenant_event)
        ws.portal.call(manager.broadcast, TENANT_A, marker)
        received = ws.receive_json()
    assert received == marker


# --------------------------------------------------------------------------- #
# 心跳与订阅过滤
# --------------------------------------------------------------------------- #
def test_ws_ping_pong(app) -> None:
    """心跳对齐前端：客户端发 {"type":"ping"}，服务端回 {"type":"pong"}。"""
    client = TestClient(app)
    with _connect(client, TENANT_A) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_subscribe_filter(app) -> None:
    """subscribe 声明的事件类型之外的消息不转发。"""
    client = TestClient(app)
    unwanted = _event(TENANT_A, "report.ready")
    wanted = _event(TENANT_A, "gang.detected")
    with _connect(client, TENANT_A) as ws:
        # 前端 onopen 发送订阅声明：只关心 gang.detected
        ws.send_json({"type": "subscribe", "event_types": ["gang.detected"]})
        ws.portal.call(manager.broadcast, TENANT_A, unwanted)
        ws.portal.call(manager.broadcast, TENANT_A, wanted)
        received = ws.receive_json()
    assert received["event_id"] == wanted["event_id"]
