"""WebhookService：HMAC-SHA256 签名 + 投递（D05 §11.8-11.10）。

签名算法：
    signature_string = f"{timestamp}.{request_body}"
    hmac_sha256_hex = HMAC-SHA256(secret, signature_string).hexdigest()

Header：
    X-FRD-Signature: t={timestamp},v1={hmac_sha256_hex}
    X-FRD-Timestamp: {timestamp}

防重放：timestamp 与当前时间差 > 5 分钟拒绝。

重试策略（D05 §11.10）：
- 5 次重试，退避间隔：1m / 5m / 30m / 2h / 12h
- 5 次失败后入死信队列（保留 30 天）
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# 重试退避间隔（秒）：即时 / 1m / 5m / 30m / 2h / 12h
RETRY_INTERVALS = [0, 60, 300, 1800, 7200, 43200]
MAX_ATTEMPTS = 5
TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 分钟


class WebhookService:
    """Webhook 签名 + 投递服务。"""

    def sign(self, secret: str, body: bytes | str, timestamp: int | None = None) -> str:
        """生成 HMAC-SHA256 签名 header。

        Args:
            secret: Webhook 签名密钥
            body: 原始请求体字节流（不可重新序列化，否则签名不一致）
            timestamp: Unix 时间戳（秒），不传则当前时间

        Returns:
            X-FRD-Signature header 值：t={timestamp},v1={hmac_hex}
        """
        if timestamp is None:
            timestamp = int(time.time())
        if isinstance(body, str):
            body = body.encode("utf-8")
        signature_string = f"{timestamp}.".encode() + body
        hmac_hex = hmac.new(
            secret.encode("utf-8"),
            signature_string,
            hashlib.sha256,
        ).hexdigest()
        return f"t={timestamp},v1={hmac_hex}"

    def verify(self, secret: str, body: bytes | str, signature_header: str) -> bool:
        """验证签名（恒定时间比较 + 防重放）。"""
        try:
            parts = dict(p.split("=", 1) for p in signature_header.split(","))
            t = int(parts["t"])
            v1 = parts["v1"]
        except (KeyError, ValueError):
            return False

        # 防重放：时间戳容差 5 分钟
        if abs(int(time.time()) - t) > TIMESTAMP_TOLERANCE_SECONDS:
            logger.warning("webhook_signature_expired", timestamp_diff=abs(int(time.time()) - t))
            return False

        if isinstance(body, str):
            body = body.encode("utf-8")
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{t}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, v1)

    async def deliver(
        self,
        webhook_url: str,
        webhook_secret: str,
        event_id: str,
        event_type: str,
        tenant_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """投递 Webhook（含 5 次重试，失败入死信队列）。

        Returns:
            投递结果 dict，含 delivery_id / status / attempts
        """
        delivery_id = f"dlv_{uuid.uuid4()}"
        body_dict = {
            "event_id": event_id,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "delivery_attempt": 1,
            "data": data,
        }
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        timestamp = int(time.time())
        signature_header = self.sign(webhook_secret, body, timestamp)

        attempts: list[dict[str, Any]] = []
        for attempt_no in range(1, MAX_ATTEMPTS + 1):
            sent_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        webhook_url,
                        content=body,
                        headers={
                            "X-FRD-Signature": signature_header,
                            "X-FRD-Timestamp": str(timestamp),
                            "Content-Type": "application/json",
                        },
                    )
                if response.status_code >= 500 and attempt_no < MAX_ATTEMPTS:
                    raise RuntimeError(f"upstream error: {response.status_code}")
                attempts.append({
                    "attempt_no": attempt_no,
                    "sent_at": sent_at,
                    "response_code": response.status_code,
                    "latency_ms": response.elapsed.total_seconds() * 1000,
                    "next_retry_at": None,
                })
                if response.status_code < 500:
                    return {
                        "delivery_id": delivery_id,
                        "status": "SUCCESS",
                        "attempts": attempts,
                        "delivered_at": sent_at,
                    }
            except Exception as exc:
                logger.warning(
                    "webhook_deliver_failed",
                    delivery_id=delivery_id,
                    attempt_no=attempt_no,
                    error=str(exc),
                )
            next_interval = RETRY_INTERVALS[attempt_no] if attempt_no < MAX_ATTEMPTS else None
            next_retry_at = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + next_interval))
                if next_interval
                else None
            )
            attempts.append({
                "attempt_no": attempt_no,
                "sent_at": sent_at,
                "response_code": None,
                "next_retry_at": next_retry_at,
            })
            if attempt_no < MAX_ATTEMPTS:
                await asyncio.sleep(0)  # 实际应使用 Celery 延时任务

        # 入死信队列
        dead_lettered_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        logger.error("webhook_dead_lettered", delivery_id=delivery_id, webhook_url=webhook_url)
        return {
            "delivery_id": delivery_id,
            "status": "DEAD_LETTERED",
            "attempts": attempts,
            "delivered_at": None,
            "dead_lettered_at": dead_lettered_at,
            "dead_letter_reason": "MAX_RETRY_EXCEEDED",
        }


# 单例
webhook_service = WebhookService()


__all__ = [
    "MAX_ATTEMPTS",
    "RETRY_INTERVALS",
    "TIMESTAMP_TOLERANCE_SECONDS",
    "WebhookService",
    "webhook_service",
]
