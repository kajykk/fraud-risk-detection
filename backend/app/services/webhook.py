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
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 重试退避间隔（秒）：即时 / 1m / 5m / 30m / 2h / 12h
RETRY_INTERVALS = [0, 60, 300, 1800, 7200, 43200]
MAX_ATTEMPTS = 5
TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 分钟

# Webhook 目标校验（SSRF 防护）
WEBHOOK_MIN_SECRET_LENGTH = 16
WEBHOOK_ALLOWED_SCHEMES = {"https"}
_HTTP_PORT_STR = {"80", "443", "8080", "8443", "8000"}


def _fernet_key() -> bytes:
    """从 app_secret_key 派生 Fernet 密钥（避免新增环境变量；prod 守卫保证其强度）。"""
    material = f"frd-webhook-secret-v1:{settings.app_secret_key}".encode()
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def encrypt_webhook_secret(secret: str) -> str:
    """Webhook 签名密钥加密落库（Fernet 对称加密，静态不可读）。"""
    from cryptography.fernet import Fernet

    return Fernet(_fernet_key()).encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_webhook_secret(token: str) -> str | None:
    """解密 Webhook 签名密钥；兼容历史明文数据（无法解密时按原值返回）。"""
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(_fernet_key()).decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("webhook_secret_decrypt_failed_fallback_plaintext")
        return token


def _is_private_ip(ip_str: str) -> bool:
    """判断 IP 是否为内网/保留地址（SSRF 防护）。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 非法 IP 视为不安全
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_public_hostname(host: str) -> bool:
    """hostname 检查：以 IP 字面量出现时必须为公网 IP。"""
    try:
        ipaddress.ip_address(host)  # 校验为合法 IP 字面量（非法抛 ValueError）
        return not _is_private_ip(host)
    except ValueError:
        return True  # 域名（DNS 解析在 resolve 层校验）


def validate_webhook_url(url: str) -> str:
    """校验 Webhook URL（SSRF 防护）：

    1. 仅允许 https
    2. 无用户名/密码/端口重定向等可疑成分
    3. host 为 IP 字面量时必须是公网 IP
    4. 解析 DNS 后所有 A 记录必须是公网 IP（拒绝 DNS rebinding 面）

    返回规范化 URL；非法时抛 ValueError。
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in WEBHOOK_ALLOWED_SCHEMES:
        raise ValueError("webhook url must use https")
    if parsed.username or parsed.password:
        raise ValueError("webhook url must not contain credentials")
    if not parsed.hostname:
        raise ValueError("webhook url missing host")
    if parsed.port not in (None, 443) and str(parsed.port) not in _HTTP_PORT_STR:
        raise ValueError(f"webhook url port not allowed: {parsed.port}")

    host = parsed.hostname
    if not _is_public_hostname(host):
        raise ValueError(f"webhook url host is private/reserved: {host}")

    # 域名：解析并校验所有 A 记录
    if not re.fullmatch(r"[0-9a-fA-F:.]+", host):
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(f"webhook url host not resolvable: {host}") from exc
        resolved = {info[4][0] for info in infos}
        if not resolved:
            raise ValueError(f"webhook url host not resolvable: {host}")
        for ip_str in resolved:
            if _is_private_ip(ip_str.split("%")[0]):
                raise ValueError(f"webhook url resolves to private address: {ip_str}")

    return parsed.geturl()


def validate_webhook_secret(secret: str) -> str:
    """校验 Webhook 签名密钥强度（最小 16 字符，避免弱密钥可预测签名）。"""
    if not secret or len(secret) < WEBHOOK_MIN_SECRET_LENGTH:
        raise ValueError(
            f"webhook secret must be at least {WEBHOOK_MIN_SECRET_LENGTH} characters"
        )
    return secret


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
        # 投递前再做一次 URL 校验（纵深防御：抵御创建后 URL 被篡改/陈旧数据）
        try:
            webhook_url = validate_webhook_url(webhook_url)
        except ValueError as exc:
            logger.error("webhook_url_invalid_on_delivery", delivery_id=delivery_id, error=str(exc))
            return {
                "delivery_id": delivery_id,
                "status": "DEAD_LETTERED",
                "attempts": [{
                    "attempt_no": 1,
                    "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "response_code": None,
                    "next_retry_at": None,
                }],
                "delivered_at": None,
                "dead_lettered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dead_letter_reason": f"URL_VALIDATION_FAILED: {exc}",
            }
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
    "decrypt_webhook_secret",
    "encrypt_webhook_secret",
    "validate_webhook_secret",
    "validate_webhook_url",
    "webhook_service",
]
