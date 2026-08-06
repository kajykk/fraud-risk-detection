"""审计日志服务：哈希链落库（D04 §3.7）。

设计：
- sequence_no 基于 tenant_id 维度递增（Redis INCR audit_seq:{tenant_id}，
  Redis 不可用时降级为 DB 内 MAX(sequence_no)+1）
- 哈希链：current_hash = sha256(prev_hash || seq || canonical_json(payload))
- prev_hash 取该租户最新一条审计的 current_hash；无记录用 GENESIS_HASH
- 所有失败均吞掉并记日志，绝不阻塞业务主路径

配合 middleware/audit.py 使用；audit_logs 表受 RLS 隔离，写入走
session_scope(tenant_id)，天然限定本租户链。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.audit import AuditLog

logger = get_logger(__name__)

# sha256(空串) 作为链头（无历史记录时的 prev_hash）
GENESIS_HASH = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)

_AUDIT_SEQ_KEY = "audit_seq:{tenant_id}"


def _canonical_json(payload: dict[str, Any]) -> str:
    """Canonical JSON 序列化（键排序、无空格），保证同载荷哈希一致。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_chain(prev_hash: str, seq: int, payload: dict[str, Any]) -> str:
    """current_hash = sha256(prev_hash || seq || canonical_json(payload))。"""
    data = f"{prev_hash}|{seq}|{_canonical_json(payload)}".encode()
    return hashlib.sha256(data).hexdigest()


def _norm_user_id(value: Any) -> uuid.UUID | None:
    """user_id 可能是 sub（用户名）而非 UUID，规范化：仅接受合法 UUID。"""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _norm_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return None


async def record_audit_event(
    *,
    tenant_id: str,
    user_id: Any,
    ip: str | None,
    user_agent: str | None,
    action: str,
    resource_type: str,
    resource_id: Any,
    status_code: int,
    request_id: str,
    duration_ms: int,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
) -> str | None:
    """写入一条审计日志并返回 current_hash；失败返回 None（不抛错）。"""
    if not tenant_id:
        # 无租户上下文的请求（如登录）不落库，避免绕过 RLS
        return None

    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": str(_norm_user_id(user_id)) if user_id else None,
        "ip": _norm_ip(ip),
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "status_code": status_code,
        "request_id": request_id,
        "duration_ms": duration_ms,
        "ts": datetime.now(UTC).isoformat(),
    }

    try:
        from app.db.redis import get_redis

        redis = get_redis()
        seq = await redis.incr(_AUDIT_SEQ_KEY.format(tenant_id=tenant_id))
    except Exception as exc:
        logger.warning("audit_seq_redis_failed", error=str(exc))
        seq = None

    try:
        async with session_scope(tenant_id) as session:
            if seq is None:
                prev = await session.execute(
                    select(func.max(AuditLog.sequence_no)).where(
                        AuditLog.tenant_id == uuid.UUID(tenant_id)
                    )
                )
                seq = (prev.scalar() or 0) + 1

            if seq == 1:
                prev_hash = GENESIS_HASH
            else:
                last = await session.execute(
                    select(AuditLog)
                    .where(AuditLog.tenant_id == uuid.UUID(tenant_id))
                    .order_by(AuditLog.created_at.desc(), AuditLog.sequence_no.desc())
                    .limit(1)
                )
                last_row = last.scalar_one_or_none()
                prev_hash = last_row.current_hash if last_row else GENESIS_HASH

            current_hash = _hash_chain(prev_hash, seq, payload)
            session.add(
                AuditLog(
                    tenant_id=uuid.UUID(tenant_id),
                    sequence_no=seq,
                    user_id=_norm_user_id(user_id),
                    ip=_norm_ip(ip),
                    user_agent=user_agent,
                    action=action[:50],
                    resource_type=resource_type[:30],
                    resource_id=_norm_user_id(resource_id),
                    before_value=before_value,
                    after_value=after_value,
                    prev_hash=prev_hash,
                    current_hash=current_hash,
                    cde_zone=False,
                    created_at=datetime.now(UTC),
                )
            )
        return current_hash
    except Exception as exc:  # noqa: BLE001 - 审计失败不阻塞业务
        logger.error("audit_write_failed", error=str(exc), tenant_id=tenant_id, action=action)
        return None


def hash_chain(prev_hash: str, seq: int, payload: dict[str, Any]) -> str:
    """公开的哈希链计算（供工具/校验脚本使用）。"""
    return _hash_chain(prev_hash, seq, payload)


__all__ = ["GENESIS_HASH", "hash_chain", "record_audit_event"]
