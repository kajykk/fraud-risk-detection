"""ws_events 服务层单元测试（D05 §2.8）。

覆盖：
- ConnectionManager：连接注册/幂等注销、事件类型过滤广播、未知租户零投递
- publish_ws_event：发布完整 WsMessage 结构；Redis 故障返回 False
- parse_ws_event：非法载荷拒绝、历史格式缺省字段补全
- listen_ws_events：订阅转发合法消息、跳过非法消息、取消时关闭 pubsub

Redis 依赖通过 monkeypatch app.db.redis.get_redis 打桩。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.ws_events import (
    WS_EVENTS_CHANNEL,
    ConnectionManager,
    listen_ws_events,
    manager,
    parse_ws_event,
    publish_ws_event,
)


def _payload(event_type: str = "transaction.analysis_completed") -> dict:
    return {
        "event_id": "evt_1",
        "event_type": event_type,
        "tenant_id": "T1",
        "occurred_at": "2026-08-25T00:00:00+00:00",
        "data": {},
    }


# --------------------------------------------------------------------------- #
# ConnectionManager
# --------------------------------------------------------------------------- #
def test_connect_broadcast_disconnect_roundtrip() -> None:
    """注册后同租户广播入队，注销（含重复注销）后不再投递。"""
    cm = ConnectionManager()
    conn = cm.connect("T1", websocket=object())
    assert cm.connection_count == 1
    assert cm.broadcast("T1", _payload()) == 1
    assert conn.queue.qsize() == 1
    cm.disconnect(conn)
    assert cm.connection_count == 0
    assert cm.broadcast("T1", _payload()) == 0
    cm.disconnect(conn)  # 幂等，不抛异常


def test_broadcast_unknown_tenant_returns_zero() -> None:
    cm = ConnectionManager()
    assert cm.broadcast("ghost-tenant", _payload()) == 0


def test_broadcast_respects_event_type_filter() -> None:
    """None 订阅全部；空集合不接收任何事件；声明集合仅收匹配类型。"""
    cm = ConnectionManager()
    all_conn = cm.connect("T1", object())
    filtered_conn = cm.connect("T1", object())
    muted_conn = cm.connect("T1", object())
    cm.set_event_filter(all_conn, None)
    cm.set_event_filter(filtered_conn, {"case.created"})
    cm.set_event_filter(muted_conn, set())

    assert cm.broadcast("T1", _payload("case.created")) == 2
    assert muted_conn.queue.empty()
    assert not filtered_conn.queue.empty()

    assert cm.broadcast("T1", _payload("other.event")) == 1  # 仅全量订阅者收到


# --------------------------------------------------------------------------- #
# publish_ws_event
# --------------------------------------------------------------------------- #
class _PublishingRedis:
    def __init__(self, sink: list[tuple[str, str]]) -> None:
        self._sink = sink

    async def publish(self, channel: str, body: str) -> int:
        self._sink.append((channel, body))
        return 1


async def test_publish_ws_event_sends_full_ws_message(monkeypatch) -> None:
    """发布到 frd:ws_events 频道，载荷满足前端 WsMessage 五字段结构。"""
    sink: list[tuple[str, str]] = []
    monkeypatch.setattr("app.db.redis.get_redis", lambda: _PublishingRedis(sink))

    assert await publish_ws_event("T1", "gang.detected", {"k": "v"}) is True

    channel, body = sink[0]
    assert channel == WS_EVENTS_CHANNEL
    message = json.loads(body)
    assert set(message) == {"event_id", "event_type", "tenant_id", "occurred_at", "data"}
    assert message["event_type"] == "gang.detected"
    assert message["tenant_id"] == "T1"
    assert message["data"] == {"k": "v"}
    assert message["event_id"].startswith("evt_")
    datetime.fromisoformat(message["occurred_at"])  # ISO 可解析


async def test_publish_ws_event_redis_failure_returns_false(monkeypatch) -> None:
    """Redis 故障时 fire-and-forget：返回 False 而非向上抛异常。"""

    def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.db.redis.get_redis", boom)
    assert await publish_ws_event("T1", "gang.detected", {}) is False


# --------------------------------------------------------------------------- #
# parse_ws_event
# --------------------------------------------------------------------------- #
def test_parse_ws_event_rejects_invalid_json() -> None:
    assert parse_ws_event("{not-json") is None
    assert parse_ws_event(b"\xff\xfe") is None


def test_parse_ws_event_rejects_non_dict_and_missing_fields() -> None:
    assert parse_ws_event("[1,2,3]") is None
    assert parse_ws_event(json.dumps({"event_type": "t"})) is None  # 缺 tenant_id
    assert parse_ws_event(json.dumps({"tenant_id": "T1"})) is None  # 缺 event_type


def test_parse_ws_event_backfills_legacy_message_defaults() -> None:
    """历史格式（仅 event_type/tenant_id/data）补全 event_id/occurred_at。"""
    parsed = parse_ws_event(json.dumps({"event_type": "t", "tenant_id": "T1"}))
    assert parsed is not None
    assert parsed["event_id"].startswith("evt_")
    assert parsed["data"] == {}
    datetime.fromisoformat(parsed["occurred_at"])


# --------------------------------------------------------------------------- #
# listen_ws_events 转发循环
# --------------------------------------------------------------------------- #
async def test_listen_forwards_valid_and_skips_invalid_messages(monkeypatch) -> None:
    """订阅消息类型被忽略、非法 JSON 被跳过、合法消息按租户转发；取消时关闭 pubsub。"""
    closed = {"value": False}

    class _Pubsub:
        async def subscribe(self, channel: str) -> None:
            assert channel == WS_EVENTS_CHANNEL

        async def listen(self) -> Any:
            yield {"type": "subscribe"}
            yield {"type": "message", "data": "{bad json"}
            yield {
                "type": "message",
                "data": json.dumps({"event_type": "e1", "tenant_id": "T-listen"}),
            }
            yield {
                "type": "message",
                "data": json.dumps({"event_type": "e2", "tenant_id": "T-other", "event_id": "evt_fixed"}),
            }
            await asyncio.Event().wait()  # 挂起直到任务取消

        async def aclose(self) -> None:
            closed["value"] = True

    monkeypatch.setattr(
        "app.db.redis.get_redis",
        lambda: SimpleNamespace(pubsub=lambda: _Pubsub()),
    )

    conn = manager.connect("T-listen", object())
    task = asyncio.create_task(listen_ws_events())
    try:
        for _ in range(200):
            if not conn.queue.empty():
                break
            await asyncio.sleep(0.01)
        received = conn.queue.get_nowait()
        assert received["event_type"] == "e1"
        assert received["event_id"].startswith("evt_")
        assert received["data"] == {}
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        manager.disconnect(conn)

    assert closed["value"] is True
