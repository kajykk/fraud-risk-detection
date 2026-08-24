"""webhook.deliver 投递任务单元测试（D05 §11.10）。

覆盖：
- 成功 → 事件标记 DELIVERED
- 瞬时失败 → 按 RETRY_COUNTDOWNS 指数退避调度下一次重试
- 重试耗尽 / 永久失败（4xx）→ dead_letter=True + 审计日志 + ws 事件
- 事件记录缺失 → SKIPPED

通过打桩模块级依赖（Redis 事件存取 / 投递 / 审计 / 发布）实现，
不依赖真实 Redis/PG/broker。
"""

from __future__ import annotations

import uuid

import pytest

from app.workers import tasks_webhooks
from app.workers.tasks_webhooks import RETRY_COUNTDOWNS, _handle_failure, deliver_webhook_event

TENANT = "00000000-0000-0000-0000-000000000001"
WEBHOOK_ID = str(uuid.uuid4())


class _RetrySentinelError(Exception):
    """task.retry 在桩中抛出的哨兵异常。"""


class _StubRequest:
    def __init__(self, retries: int) -> None:
        self.retries = retries


class _StubTask:
    """模拟 Celery Task：仅提供 _handle_failure 所需的 request.retries 与 retry。"""

    def __init__(self, retries: int) -> None:
        self.request = _StubRequest(retries)
        self.retry_calls: list[dict] = []

    def retry(self, *, exc=None, countdown=None):  # noqa: ANN001, ARG002 - 测试桩
        self.retry_calls.append({"countdown": countdown})
        raise _RetrySentinelError()


def _failed_result(*, permanent: bool = False) -> dict:
    return {
        "delivery_id": "dlv_test",
        "status": "FAILED",
        "permanent": permanent,
        "response_code": 404 if permanent else None,
        "latency_ms": None,
        "sent_at": None,
        "error": "upstream error: 404" if permanent else "connection timeout",
    }


@pytest.fixture
def event() -> dict:
    return {
        "event_id": "evt_test_1",
        "tenant_id": TENANT,
        "event_type": "transaction.rejected",
        "data": {"amount": 100},
        "webhook_id": WEBHOOK_ID,
    }


# --------------------------------------------------------------------------- #
# 重试调度
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("retries_done", range(len(RETRY_COUNTDOWNS)))
def test_transient_failure_schedules_exponential_retry(
    monkeypatch, event: dict, retries_done: int
) -> None:
    """第 n 次失败应以 RETRY_COUNTDOWNS[n] 的 countdown 调度重试。"""
    task = _StubTask(retries=retries_done)
    with pytest.raises(_RetrySentinelError):
        _handle_failure(
            task, "evt_test_1", WEBHOOK_ID, event, TENANT,
            _failed_result(), attempt_no=retries_done + 1,
        )
    assert task.retry_calls == [{"countdown": RETRY_COUNTDOWNS[retries_done]}]


def test_retry_countdowns_match_design_spec() -> None:
    """退避序列对齐 D05 §11.10：1m / 5m / 30m / 2h / 12h 共 5 次。"""
    assert RETRY_COUNTDOWNS == [60, 300, 1800, 7200, 43200]
    assert len(RETRY_COUNTDOWNS) == 5


# --------------------------------------------------------------------------- #
# 死信闭环
# --------------------------------------------------------------------------- #
def test_dead_letter_after_retries_exhausted(monkeypatch, event: dict) -> None:
    """重试耗尽（retries >= 5）→ 标记 dead_letter=True + 审计 + ws 事件。"""
    updates: list[dict] = []
    audits: list[dict] = []
    published: list[dict] = []

    async def fake_update(event_id, **fields):
        updates.append({"event_id": event_id, **fields})

    async def fake_audit(tenant_id, event_id, webhook_id, reason):
        audits.append({"tenant_id": tenant_id, "event_id": event_id, "reason": reason})

    async def fake_publish(tenant_id, payload, *, delivered, reason=None):
        published.append({"delivered": delivered})

    monkeypatch.setattr(tasks_webhooks, "update_webhook_event", fake_update)
    monkeypatch.setattr(tasks_webhooks, "_record_dead_letter_audit", fake_audit)
    monkeypatch.setattr(tasks_webhooks, "_publish_delivery_event", fake_publish)

    task = _StubTask(retries=len(RETRY_COUNTDOWNS))
    result = _handle_failure(
        task, "evt_test_1", WEBHOOK_ID, event, TENANT,
        _failed_result(), attempt_no=6,
    )

    assert result["status"] == "DEAD_LETTERED"
    assert result["dead_letter_reason"] == "MAX_RETRY_EXCEEDED"
    assert task.retry_calls == []
    assert updates and updates[0]["dead_letter"] is True
    assert updates[0]["dead_letter_reason"] == "MAX_RETRY_EXCEEDED"
    assert audits and audits[0]["event_id"] == "evt_test_1"
    assert published and published[0]["delivered"] is False


def test_permanent_failure_skips_retry_and_dead_letters(monkeypatch, event: dict) -> None:
    """4xx 永久失败不应浪费重试次数，直接死信。"""
    updates: list[dict] = []

    async def fake_update(event_id, **fields):
        updates.append({"event_id": event_id, **fields})

    async def fake_audit(tenant_id, event_id, webhook_id, reason):
        return None

    async def fake_publish(tenant_id, payload, *, delivered, reason=None):
        return None

    monkeypatch.setattr(tasks_webhooks, "update_webhook_event", fake_update)
    monkeypatch.setattr(tasks_webhooks, "_record_dead_letter_audit", fake_audit)
    monkeypatch.setattr(tasks_webhooks, "_publish_delivery_event", fake_publish)

    task = _StubTask(retries=0)
    result = _handle_failure(
        task, "evt_test_1", WEBHOOK_ID, event, TENANT,
        _failed_result(permanent=True), attempt_no=1,
    )
    assert result["status"] == "DEAD_LETTERED"
    assert result["dead_letter_reason"].startswith("PERMANENT_FAILURE")
    assert updates[0]["dead_letter"] is True


# --------------------------------------------------------------------------- #
# 任务主流程
# --------------------------------------------------------------------------- #
def test_deliver_success_marks_delivered(monkeypatch, event: dict) -> None:
    """投递成功 → 更新 DELIVERED 并返回成功结果。"""
    loaded: list[str] = []
    updates: list[dict] = []
    published: list[bool] = []

    async def fake_get(event_id):
        loaded.append(event_id)
        return event

    async def fake_attempt(tenant_id, webhook_id, ev, attempt_no):
        return {
            "delivery_id": "dlv_ok",
            "status": "SUCCESS",
            "permanent": False,
            "response_code": 200,
            "latency_ms": 12,
            "sent_at": "2026-08-24T00:00:00Z",
            "error": None,
        }

    async def fake_update(event_id, **fields):
        updates.append({"event_id": event_id, **fields})

    async def fake_publish(tenant_id, ev, *, delivered, reason=None):
        published.append(delivered)

    monkeypatch.setattr(tasks_webhooks, "get_webhook_event", fake_get)
    monkeypatch.setattr(tasks_webhooks, "_attempt_delivery", fake_attempt)
    monkeypatch.setattr(tasks_webhooks, "update_webhook_event", fake_update)
    monkeypatch.setattr(tasks_webhooks, "_publish_delivery_event", fake_publish)

    result = deliver_webhook_event("evt_test_1", WEBHOOK_ID)
    assert result["status"] == "DELIVERED"
    assert result["attempt_no"] == 1
    assert loaded == ["evt_test_1"]
    assert updates[0]["status"] == "DELIVERED"
    assert published == [True]


def test_deliver_missing_event_skipped(monkeypatch) -> None:
    """事件记录不存在（过期/丢失）应 SKIPPED，而非报错重试。"""

    async def fake_get(event_id):
        return None

    monkeypatch.setattr(tasks_webhooks, "get_webhook_event", fake_get)
    result = deliver_webhook_event("evt_gone", WEBHOOK_ID)
    assert result["status"] == "SKIPPED"
