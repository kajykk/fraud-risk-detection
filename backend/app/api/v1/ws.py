"""WebSocket 实时推送端点（D05 §2.8）。

路径：GET /api/v1/ws?ticket={一次性票据}（推荐）
      GET /api/v1/ws?access_token={jwt}（兼容）

握手鉴权：
- ticket：先 POST /auth/ws-ticket 换取 30s 一次性票据，GETDEL 单次消费；
  避免长期 JWT 泄漏到访问日志/代理日志
- access_token：直接校验 JWT（仅接受 access 类型）
失败以 1008 关闭连接。校验通过后注册到 ConnectionManager，由 lifespan 中的
frd:ws_events 订阅者按事件内 tenant_id 过滤转发。

心跳：与前端对齐 —— 客户端每 30s 发 {"type":"ping"}，服务端回
{"type":"pong"}；客户端 onopen 发送的 {"type":"subscribe",
event_types:[...]} 用于按事件类型过滤（缺省接收全部）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.core.security import ACCESS_TOKEN_TYPE, verify_token
from app.services.ws_events import WsConnection, manager

logger = get_logger(__name__)

router = APIRouter()

# 握手拒绝（策略违规：未认证/令牌无效）
WS_CLOSE_UNAUTHORIZED = 1008


def _authenticate(token: str | None) -> dict[str, Any] | None:
    """校验 query token，返回 JWT payload；无效返回 None。"""
    if not token:
        return None
    try:
        return verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except Exception:
        return None


async def _consume_ws_ticket(ticket: str) -> dict[str, Any] | None:
    """消费一次性 WS 连接票据（GETDEL 原子单次消费）。

    返回 {"tenant_id": ..., "sub": ...}；无效/过期/已消费返回 None。
    """
    if not ticket or not ticket.startswith("wst_") or len(ticket) > 128:
        return None
    try:
        from app.db.redis import get_redis

        raw = await get_redis().getdel(f"ws_ticket:{ticket}")
        if not raw:
            return None
        import json

        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - Redis 故障按未授权处理（fail-closed）
        logger.warning("ws_ticket_consume_failed", error=str(exc))
        return None
    tenant_id = data.get("tenant_id")
    sub = data.get("sub")
    if not tenant_id or not sub:
        return None
    return {"sub": str(sub), "tenant_id": str(tenant_id), "type": "access"}


async def _authenticate_connection(
    token: str | None,
    ticket: str | None,
) -> dict[str, Any] | None:
    """连接鉴权入口：优先 ticket（推荐），回退 access_token JWT。"""
    if ticket:
        return await _consume_ws_ticket(ticket)
    return _authenticate(token)


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
    """实时事件推送 WebSocket 端点（多租户隔离 + 心跳 + 类型订阅）。

    鉴权：优先 `?ticket=`（一次性票据，推荐），兼容 `?access_token={jwt}`。
    """
    payload = await _authenticate_connection(
        websocket.query_params.get("access_token"),
        websocket.query_params.get("ticket"),
    )
    if payload is None or not payload.get("tenant_id"):
        # accept 前关闭 → 握手直接被拒（403）
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return

    tenant_id = str(payload["tenant_id"])
    # 先注册再 accept：注册与 accept 之间到达的广播也能入队不丢。
    # accept 抛异常（客户端已断开等）时必须注销，否则连接永久泄漏，
    # broadcast 持续向死队列投递。
    connection = manager.connect(tenant_id, websocket)
    try:
        await websocket.accept()
    except Exception:
        manager.disconnect(connection)
        raise
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
