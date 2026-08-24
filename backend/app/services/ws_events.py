"""WebSocket 实时事件：frd:ws_events 发布/订阅 + 连接管理（D05 §2.8）。

职责：
- publish_ws_event：发布完整 WsMessage 结构（event_id/event_type/tenant_id/
  occurred_at/data）到 Redis 频道 frd:ws_events，供多副本间广播
- ConnectionManager：进程内连接注册表，按 tenant_id 维护连接并投递消息
- listen_ws_events：lifespan 后台协程（与 rule_engine.listen_reload 同款模式），
  订阅 frd:ws_events 并按事件内 tenant_id 过滤转发给对应租户的 WebSocket 连接；
  断线自动重连（5s），应用关闭时静默退出

消息格式对齐 frontend/src/utils/websocket.ts 的 WsMessage 接口。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

WS_EVENTS_CHANNEL = "frd:ws_events"


@dataclass(eq=False)
class WsConnection:
    """单条 WebSocket 连接上下文（按对象标识哈希，便于放入 set）。"""

    websocket: Any
    tenant_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # None = 订阅全部事件类型；set 为空表示不接收任何事件
    event_types: set[str] | None = None


class ConnectionManager:
    """进程内 WebSocket 连接注册表（按租户分组）。"""

    def __init__(self) -> None:
        self._by_tenant: dict[str, set[WsConnection]] = {}

    def connect(self, tenant_id: str, websocket: Any) -> WsConnection:
        """注册连接（accept 前调用，保证早到的广播也能入队）。"""
        connection = WsConnection(websocket=websocket, tenant_id=str(tenant_id))
        self._by_tenant.setdefault(str(tenant_id), set()).add(connection)
        return connection

    def disconnect(self, connection: WsConnection) -> None:
        """注销连接（幂等）。"""
        conns = self._by_tenant.get(connection.tenant_id)
        if conns is not None:
            conns.discard(connection)
            if not conns:
                self._by_tenant.pop(connection.tenant_id, None)

    def set_event_filter(self, connection: WsConnection, event_types: set[str] | None) -> None:
        """设置该连接的事件类型过滤（subscribe 消息触发）。"""
        connection.event_types = event_types

    def broadcast(self, tenant_id: str, payload: dict[str, Any]) -> int:
        """将事件入队到目标租户的所有匹配连接；返回实际投递的连接数。

        仅入队不直接发送（发送由各连接的 sender 协程串行完成），
        避免慢连接阻塞其他订阅者。
        """
        connections = self._by_tenant.get(str(tenant_id), set())
        delivered = 0
        for connection in connections:
            if (
                connection.event_types is not None
                and payload.get("event_type") not in connection.event_types
            ):
                continue
            connection.queue.put_nowait(payload)
            delivered += 1
        return delivered

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self._by_tenant.values())


# 进程级单例（ws 端点与 lifespan 监听协程共享）
manager = ConnectionManager()


async def publish_ws_event(
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    *,
    event_id: str | None = None,
) -> bool:
    """发布一条实时事件到 frd:ws_events（fire-and-forget，失败仅告警）。

    消息结构对齐前端 WsMessage：event_id / event_type / tenant_id /
    occurred_at / data。
    """
    payload = {
        "event_id": event_id or f"evt_{uuid.uuid4()}",
        "event_type": event_type,
        "tenant_id": str(tenant_id),
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    try:
        from app.db.redis import get_redis

        await get_redis().publish(
            WS_EVENTS_CHANNEL,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        return True
    except Exception as exc:
        logger.warning("ws_event_publish_failed", error=str(exc), event_type=event_type)
        return False


def parse_ws_event(data: Any) -> dict[str, Any] | None:
    """解析 pubsub 消息为合法 WsMessage dict；非法返回 None。

    兼容历史发布格式（仅含 event_type/tenant_id/data）：缺省字段补全，
    保证转发给前端的每条消息都满足 WsMessage 结构。
    """
    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("tenant_id") or not payload.get("event_type"):
        return None
    payload.setdefault("event_id", f"evt_{uuid.uuid4()}")
    payload.setdefault("occurred_at", datetime.now(UTC).isoformat())
    payload.setdefault("data", {})
    return payload


async def listen_ws_events() -> None:
    """订阅 frd:ws_events 并按 tenant_id 转发（lifespan 后台协程）。

    断线后 5s 重连；取消（应用关闭）时静默退出。
    """
    while True:
        pubsub = None
        try:
            from app.db.redis import get_redis

            pubsub = get_redis().pubsub()
            await pubsub.subscribe(WS_EVENTS_CHANNEL)
            logger.info("ws_events_subscribed", channel=WS_EVENTS_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = parse_ws_event(message.get("data"))
                if payload is None:
                    continue
                delivered = manager.broadcast(str(payload["tenant_id"]), payload)
                logger.info(
                    "ws_event_forwarded",
                    event_type=payload.get("event_type"),
                    tenant_id=payload.get("tenant_id"),
                    delivered=delivered,
                )
        except asyncio.CancelledError:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
            raise
        except Exception as exc:
            logger.warning("ws_events_listener_retry", error=str(exc))
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()
            await asyncio.sleep(5)


__all__ = [
    "WS_EVENTS_CHANNEL",
    "ConnectionManager",
    "WsConnection",
    "listen_ws_events",
    "manager",
    "parse_ws_event",
    "publish_ws_event",
]
