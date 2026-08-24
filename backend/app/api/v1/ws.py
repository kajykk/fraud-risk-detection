"""WebSocket 实时推送端点（D05 §2.8）。

路径：GET /api/v1/ws?access_token={jwt}

握手鉴权：从 query token 校验 JWT（仅接受 access 类型），失败以 1008
关闭连接。校验通过后注册到 ConnectionManager，由 lifespan 中的
frd:ws_events 订阅者按事件内 tenant_id 过滤转发。

心跳：与前端对齐 —— 客户端每 30s 发 {"type":"ping"}，服务端回
{"type":"pong"}；客户端 onopen 发送的 {"type":"subscribe",
event_types:[...]} 用于按事件类型过滤（缺省接收全部）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.core.security import ACCESS_TOKEN_TYPE, verify_token
from app.services.ws_events import WsConnection, manager

logger = get_logger(__name__)

router = APIRouter()

# 握手拒绝（策略违规：未认证/令牌无效）
WS_CLOSE_UNAUTHORIZED = 1008


def _authenticate(token: str | None) -> dict | None:
    """校验 query token，返回 JWT payload；无效返回 None。"""
    if not token:
        return None
    try:
        return verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except Exception:
        return None


async def _sender_loop(connection: WsConnection) -> None:
    """串行发送协程：从队列取事件推送给客户端。

    发送失败（客户端已断开/网络异常）时主动关闭连接，
    让 receive 循环退出并统一走清理逻辑。
    """
    while True:
        payload = await connection.queue.get()
        try:
            await connection.websocket.send_json(payload)
        except Exception as exc:  # noqa: BLE001 - 发送异常即断开清理
            logger.info("ws_sender_failed", error=str(exc), tenant_id=connection.tenant_id)
            with contextlib.suppress(Exception):
                await connection.websocket.close()
            return


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """实时事件推送 WebSocket 端点（多租户隔离 + 心跳 + 类型订阅）。"""
    payload = _authenticate(websocket.query_params.get("access_token"))
    if payload is None or not payload.get("tenant_id"):
        # accept 前关闭 → 握手直接被拒（403）
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return

    tenant_id = str(payload["tenant_id"])
    # 先注册再 accept：注册与 accept 之间到达的广播也能入队不丢
    connection = manager.connect(tenant_id, websocket)
    await websocket.accept()
    sender = asyncio.create_task(_sender_loop(connection))
    logger.info("ws_connected", tenant_id=tenant_id, connections=manager.connection_count)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue  # 非 JSON 帧忽略
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                event_types = message.get("event_types")
                manager.set_event_filter(
                    connection,
                    {str(t) for t in event_types} if isinstance(event_types, list) else None,
                )
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        manager.disconnect(connection)
        logger.info("ws_disconnected", tenant_id=tenant_id, connections=manager.connection_count)


__all__ = ["router", "websocket_endpoint"]
