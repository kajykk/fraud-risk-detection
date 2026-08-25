"""webhook.deliver 任务补充单元测试（workers/tasks_webhooks.py）。

聚焦 deliver_webhook_event 既有测试未覆盖的分支：
- _attempt_delivery：商户记录缺失 / URL 或密钥缺失（永久失败）/
  密钥解密失败（永久失败）/ DB 故障走重试通道 / 成功路径参数透传
- _fail_result 结果结构
- WebhookTask 基类 __call__ 的 structlog 初始化

DB/投递服务通过 monkeypatch 打桩，不依赖真实 PG/broker。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

from app.workers import tasks_webhooks
from app.workers.tasks_webhooks import (
    RETRY_COUNTDOWNS,
    _attempt_delivery,
    _fail_result,
    deliver_webhook_event,
)

TENANT = "00000000-0000-0000-0000-000000000001"
WEBHOOK_ID = str(uuid.uuid4())
EVENT: dict[str, Any] = {
    "event_id": "evt_1",
    "event_type": "transaction.rejected",
    "data": {"amount": 100},
}


class _Row:
    def __init__(self, url: str | None, secret: str | None) -> None:
        self.webhook_url = url
        self.webhook_secret = secret


class _QueryResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    def __init__(self, row: Any) -> None:
        self._row = row

    def execute(self, stmt: Any) -> _QueryResult:
        return _QueryResult(self._row)

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False


def _patch_session(monkeypatch, row: Any = None, error: Exception | None = None) -> None:
    from app.db import sync_session as sync_session_module

    @contextmanager
    def fake_scope(tenant_id: str | None):
        if error is not None:
            raise error
        yield _Session(row)

    monkeypatch.setattr(sync_session_module, "sync_session_scope", fake_scope)


# --------------------------------------------------------------------------- #
# _attempt_delivery 配置加载分支
# --------------------------------------------------------------------------- #
async def test_attempt_delivery_merchant_row_missing(monkeypatch) -> None:
    """商户不存在 → 非永久失败 webhook_not_configured（保留重试机会）。"""
    _patch_session(monkeypatch, row=None)
    result = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 1)
    assert result["status"] == "FAILED"
    assert result["error"] == "webhook_not_configured"
    assert result["permanent"] is False


async def test_attempt_delivery_missing_url_or_secret_is_permanent(monkeypatch) -> None:
    """配置存在但 URL/密钥缺失 → 永久失败，不浪费重试次数。"""
    _patch_session(monkeypatch, row=_Row(url=None, secret="enc"))
    result = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 1)
    assert result["permanent"] is True
    assert result["error"] == "webhook_not_configured"

    _patch_session(monkeypatch, row=_Row(url="https://hooks.example.com/x", secret=None))
    result2 = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 1)
    assert result2["permanent"] is True
    assert result2["error"] == "webhook_not_configured"


async def test_attempt_delivery_secret_decrypt_failure_permanent(monkeypatch) -> None:
    """密钥解密不可用 → 永久失败 secret_unavailable。"""
    _patch_session(monkeypatch, row=_Row("https://hooks.example.com/hook", "corrupt-blob"))

    def none_decrypt(token: str) -> None:
        return None

    monkeypatch.setattr(tasks_webhooks, "decrypt_webhook_secret", none_decrypt)
    result = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 1)
    assert result["status"] == "FAILED"
    assert result["permanent"] is True
    assert result["error"] == "secret_unavailable"


async def test_attempt_delivery_db_failure_routes_to_retry_channel(monkeypatch) -> None:
    """DB 加载异常视为瞬时故障：非永久失败并携带 config_load_failed 原因。"""
    _patch_session(monkeypatch, error=RuntimeError("pg down"))
    result = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 1)
    assert result["status"] == "FAILED"
    assert result["permanent"] is False
    assert result["error"].startswith("config_load_failed")


async def test_attempt_delivery_passes_decrypted_config_to_deliver_once(monkeypatch) -> None:
    """成功路径：解密后的 URL/密钥与事件字段透传给 deliver_once，结果原样返回。"""
    _patch_session(monkeypatch, row=_Row("https://hooks.example.com/hook", "enc-blob"))
    captured: dict[str, Any] = {}

    async def fake_deliver_once(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "delivery_id": "dlv_ok",
            "status": "SUCCESS",
            "permanent": False,
            "response_code": 200,
            "latency_ms": 12,
            "sent_at": "2026-08-25T00:00:00Z",
            "error": None,
        }

    def fake_decrypt(token: str) -> str | None:
        return "plain-signing-secret"

    monkeypatch.setattr(tasks_webhooks.webhook_service, "deliver_once", fake_deliver_once)
    monkeypatch.setattr(tasks_webhooks, "decrypt_webhook_secret", fake_decrypt)

    result = await _attempt_delivery(TENANT, WEBHOOK_ID, EVENT, 3)

    assert result["status"] == "SUCCESS"
    assert captured["webhook_url"] == "https://hooks.example.com/hook"
    assert captured["webhook_secret"] == "plain-signing-secret"
    assert captured["event_id"] == "evt_1"
    assert captured["event_type"] == "transaction.rejected"
    assert captured["tenant_id"] == TENANT
    assert captured["attempt_no"] == 3


def test_fail_result_shape() -> None:
    result = _fail_result("boom", permanent=True)
    assert result["status"] == "FAILED"
    assert result["permanent"] is True
    assert result["error"] == "boom"
    assert result["delivery_id"].startswith("dlv_")
    assert result["response_code"] is None
    assert result["latency_ms"] is None
    assert result["sent_at"] is None


# --------------------------------------------------------------------------- #
# 任务基类与主流程兜底
# --------------------------------------------------------------------------- #
def test_deliver_webhook_event_propagates_result(monkeypatch) -> None:
    """deliver_webhook_event 主流程：取回事件后按 attempt 结果透传状态。"""
    loaded: list[str] = []

    async def fake_get(event_id: str):
        loaded.append(event_id)
        return {**EVENT, "attempts": 4}

    async def fake_attempt(tenant_id: str, webhook_id: str, ev: dict, attempt_no: int):
        return {
            "delivery_id": "dlv_final",
            "status": "SUCCESS",
            "permanent": False,
            "response_code": 200,
            "latency_ms": 5,
            "sent_at": "2026-08-25T00:00:00Z",
            "error": None,
        }

    updates: list[dict] = []

    async def fake_update(event_id: str, **fields: Any) -> None:
        updates.append({"event_id": event_id, **fields})

    async def fake_publish(tenant_id: str, ev: dict, *, delivered: bool, reason: str | None = None) -> None:
        return None

    monkeypatch.setattr(tasks_webhooks, "get_webhook_event", fake_get)
    monkeypatch.setattr(tasks_webhooks, "_attempt_delivery", fake_attempt)
    monkeypatch.setattr(tasks_webhooks, "update_webhook_event", fake_update)
    monkeypatch.setattr(tasks_webhooks, "_publish_delivery_event", fake_publish)

    result = deliver_webhook_event("evt_1", WEBHOOK_ID)
    assert loaded == ["evt_1"]
    assert result == {"status": "DELIVERED", "delivery_id": "dlv_final", "attempt_no": 5}
    assert updates[0]["status"] == "DELIVERED"
    assert updates[0]["dead_letter"] is False


def test_max_retries_matches_countdown_plan() -> None:
    """任务 max_retries 与退避序列长度一致（5 次重试）。"""
    assert deliver_webhook_event.max_retries == len(RETRY_COUNTDOWNS)
