"""Webhook 事件投递任务（D05 §11.8-11.10）。

任务清单：
- deliver_webhook_event: 单次尝试投递 webhook 事件，失败由 Celery countdown
  按指数退避调度重试（60s / 5m / 30m / 2h / 12h 共 5 次）

闭环设计：
- 事件记录（Redis frd:webhook_event:{event_id}）由 scoring/case 节点构造，
  本任务按 (event_id, webhook_id) 取回并投递
- 瞬时失败（网络/5xx/超时）→ self.retry(countdown=RETRY_COUNTDOWNS[n])
- 永久失败（4xx/URL 校验不过）→ 跳过重试直接死信
- 重试耗尽 → 事件标记 dead_letter=True、写审计日志、发布 frd:ws_events
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task

from app.core.logging import configure_logging, get_logger
from app.services.webhook import (
    decrypt_webhook_secret,
    get_webhook_event,
    update_webhook_event,
    webhook_service,
)
from app.workers.celery_app import celery_app

# 注意：使用 structlog logger（支持关键字上下文）；celery.get_task_logger
# 的 stdlib logger 仅在 info 级别容忍 kwargs，warning/error 会 TypeError。
logger = get_logger(__name__)

# 重试退避（秒）：第 n 次失败后下一次执行的延迟；共 5 次重试（D05 §11.10）
RETRY_COUNTDOWNS = [60, 300, 1800, 7200, 43200]


class WebhookTask(Task):
    """Webhook 任务基类：worker 进程启动时配置 structlog。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        configure_logging()
        return super().__call__(*args, **kwargs)


@celery_app.task(
    name="webhook.deliver",
    bind=True,
    base=WebhookTask,
    max_retries=len(RETRY_COUNTDOWNS),
)
def deliver_webhook_event(
    self: WebhookTask,
    event_id: str,
    webhook_id: str,
) -> dict[str, Any]:
    """投递 Webhook 事件（单次尝试 + countdown 指数退避重试 + 死信兜底）。"""
    logger.info(
        "webhook_deliver_begin",
        event_id=event_id,
        webhook_id=webhook_id,
        retries=self.request.retries,
    )
    event = asyncio.run(get_webhook_event(event_id))
    if event is None:
        # 记录过期（TTL 30 天）或不存在：无法投递，直接放弃
        logger.warning("webhook_event_not_found", event_id=event_id)
        return {"status": "SKIPPED", "reason": "event_not_found"}

    attempt_no = int(event.get("attempts", 0)) + 1
    tenant_id = str(event.get("tenant_id", ""))
    result = asyncio.run(
        _attempt_delivery(tenant_id, webhook_id, event, attempt_no)
    )

    if result["status"] == "SUCCESS":
        asyncio.run(
            update_webhook_event(
                event_id,
                status="DELIVERED",
                attempts=attempt_no,
                last_response_code=result.get("response_code"),
                last_delivery_at=result.get("sent_at"),
                dead_letter=False,
            )
        )
        asyncio.run(_publish_delivery_event(tenant_id, event, delivered=True))
        logger.info(
            "webhook_deliver_complete",
            event_id=event_id,
            delivery_id=result["delivery_id"],
            attempt_no=attempt_no,
            response_code=result.get("response_code"),
        )
        return {
            "status": "DELIVERED",
            "delivery_id": result["delivery_id"],
            "attempt_no": attempt_no,
        }

    return _handle_failure(self, event_id, webhook_id, event, tenant_id, result, attempt_no)


def _handle_failure(
    task: WebhookTask,
    event_id: str,
    webhook_id: str,
    event: dict[str, Any],
    tenant_id: str,
    result: dict[str, Any],
    attempt_no: int,
) -> dict[str, Any]:
    """失败处理：可重试 → countdown 调度下一次；否则（永久失败/重试耗尽）→ 死信。

    注意：task.retry 抛出 Retry 异常向上传播（Celery 接管调度），本函数不捕获。
    """
    reason = result.get("error") or "delivery failed"
    permanent = bool(result.get("permanent"))
    retries_done = task.request.retries
    retryable = not permanent and retries_done < len(RETRY_COUNTDOWNS)

    if retryable:
        countdown = RETRY_COUNTDOWNS[retries_done]
        logger.warning(
            "webhook_deliver_retry_scheduled",
            event_id=event_id,
            attempt_no=attempt_no,
            next_countdown_seconds=countdown,
            error=str(reason),
        )
        raise task.retry(
            exc=RuntimeError(str(reason)),
            countdown=countdown,
        ) from RuntimeError(str(reason))

    # ---- 死信：永久失败或重试次数耗尽 ----
    dead_letter_reason = (
        f"PERMANENT_FAILURE: {reason}" if permanent else "MAX_RETRY_EXCEEDED"
    )
    asyncio.run(
        update_webhook_event(
            event_id,
            status="DEAD_LETTERED",
            attempts=attempt_no,
            last_response_code=result.get("response_code"),
            last_delivery_at=result.get("sent_at"),
            dead_letter=True,
            dead_letter_reason=dead_letter_reason,
        )
    )
    asyncio.run(_record_dead_letter_audit(tenant_id, event_id, webhook_id, dead_letter_reason))
    asyncio.run(_publish_delivery_event(tenant_id, event, delivered=False, reason=dead_letter_reason))
    logger.error(
        "webhook_dead_lettered",
        event_id=event_id,
        webhook_id=webhook_id,
        attempts=attempt_no,
        reason=dead_letter_reason,
    )
    return {
        "status": "DEAD_LETTERED",
        "attempt_no": attempt_no,
        "dead_letter_reason": dead_letter_reason,
    }


async def _attempt_delivery(
    tenant_id: str,
    webhook_id: str,
    event: dict[str, Any],
    attempt_no: int,
) -> dict[str, Any]:
    """加载商户 webhook 配置并执行一次投递。"""
    from sqlalchemy import select

    from app.db.sync_session import sync_session_scope
    from app.models.tenant import Merchant

    try:
        with sync_session_scope(tenant_id or None) as session:
            row = session.execute(
                select(Merchant).where(Merchant.id == uuid.UUID(webhook_id))
            ).scalar_one_or_none()
            if row is None:
                return _fail_result("webhook_not_configured")
            url = row.webhook_url
            secret_encrypted = row.webhook_secret
    except Exception as exc:
        # DB 不可用视为瞬时故障，走重试通道
        logger.warning("webhook_config_load_failed", error=str(exc), webhook_id=webhook_id)
        return _fail_result(f"config_load_failed: {exc}")

    if not url or not secret_encrypted:
        return _fail_result("webhook_not_configured", permanent=True)
    secret = decrypt_webhook_secret(secret_encrypted)
    if secret is None:
        return _fail_result("secret_unavailable", permanent=True)

    return await webhook_service.deliver_once(
        webhook_url=url,
        webhook_secret=secret,
        event_id=str(event.get("event_id", "")),
        event_type=str(event.get("event_type", "")),
        tenant_id=tenant_id,
        data=dict(event.get("data") or {}),
        attempt_no=attempt_no,
    )


def _fail_result(reason: str, *, permanent: bool = False) -> dict[str, Any]:
    return {
        "delivery_id": f"dlv_{uuid.uuid4()}",
        "status": "FAILED",
        "permanent": permanent,
        "response_code": None,
        "latency_ms": None,
        "sent_at": None,
        "error": reason,
    }


async def _record_dead_letter_audit(
    tenant_id: str,
    event_id: str,
    webhook_id: str,
    reason: str,
) -> None:
    """死信写审计日志（哈希链落库；失败不阻塞）。"""
    try:
        from app.services.audit import record_audit_event

        await record_audit_event(
            tenant_id=tenant_id,
            user_id=None,
            ip=None,
            user_agent=None,
            action="webhook.dead_letter",
            resource_type="webhook_event",
            resource_id=event_id,
            status_code=502,
            request_id=f"webhook_{event_id}",
            duration_ms=0,
            after_value={
                "webhook_id": webhook_id,
                "dead_letter_reason": reason,
            },
        )
    except Exception as exc:
        logger.warning("webhook_dead_letter_audit_failed", event_id=event_id, error=str(exc))


async def _publish_delivery_event(
    tenant_id: str,
    event: dict[str, Any],
    *,
    delivered: bool,
    reason: str | None = None,
) -> None:
    """投递终态发布 frd:ws_events（前端实时可见）。"""
    from app.services.ws_events import publish_ws_event

    await publish_ws_event(
        tenant_id,
        "webhook.delivered" if delivered else "webhook.dead_letter",
        {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "webhook_id": event.get("webhook_id"),
            "delivered": delivered,
            "reason": reason,
        },
    )


__all__ = ["RETRY_COUNTDOWNS", "WebhookTask", "deliver_webhook_event"]
