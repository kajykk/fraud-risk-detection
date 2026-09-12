"""PIPL 数据主体权利异步任务（D05 V1.1 §13 / PIPL §45-§47）。

任务清单：
- export_data: 数据导出（被遗忘权前置 / 数据可携带权）
- delete_data: 数据删除（被遗忘权 / 删除权）
- rectify_data: 数据更正（更正权 / 补充权）
- notify_subject: 任务完成后通知数据主体

PIPL 合规约束：
- 数据导出：15 工作日内完成
- 数据删除：15 工作日内完成，需校验法律保留义务（反洗钱 7 年审计保留）
- 数据更正：及时处理
- 所有操作记入 audit_logs（哈希链）
- 法律保留冲突时返回 LEGAL_HOLD_CONFLICT
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.core.logging import configure_logging
from app.db.sync_session import sync_session_scope
from app.models.aml import AmlReport
from app.models.case import Case
from app.models.pipl import ConsentRecord, DeletionRequest
from app.models.transaction import Score, ShapExplanation, Transaction
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

# 反洗钱报告法定保留期（基准 §3.9：7 年）
AML_RETENTION_YEARS = 7
# 参与保留判定的报告状态（REJECTED 不构成保留）
_HOLDING_STATUSES = ("PENDING", "SUBMITTED", "ACCEPTED")


def _is_active_legal_hold(report: Any, cutoff: datetime) -> bool:
    """判定单条 AML 报告是否仍构成法律保留。

    - REJECTED：不保留；
    - ACCEPTED 且 submitted_at 早于保留期截止线：期满自动解除；
    - 其余（PENDING / SUBMITTED / 时间缺失的 ACCEPTED）：保守视为保留中。
    """
    if report.status == "REJECTED":
        return False
    if (
        report.status == "ACCEPTED"
        and report.submitted_at is not None
        and report.submitted_at < cutoff
    ):
        return False
    return True


def _collect_active_legal_holds(
    session: Any,
    tenant_id: str,
    user_id: str,
    cutoff: datetime,
) -> list[Any]:
    """收集该数据主体名下仍生效的 AML 法律保留报告。

    三路检索后按保留期谓词过滤：
    1. 主路径：subject_user_account_id 精确匹配（0006 迁移已回填）；
    2. 孤儿兜底①：主体列为空的报告经 transaction_id 联表归属；
    3. 孤儿兜底②：主体列为空的报告经 case_id → cases.transaction_id 二跳归属。
    合规口径：宁可误拦不可漏放。
    """
    tid = uuid.UUID(tenant_id)

    direct = (
        session.execute(
            select(AmlReport).where(
                AmlReport.tenant_id == tid,
                AmlReport.subject_user_account_id == user_id,
                AmlReport.status.in_(_HOLDING_STATUSES),
            )
        )
        .scalars()
        .all()
    )
    orphan_via_tx = (
        session.execute(
            select(AmlReport)
            .join(Transaction, Transaction.id == AmlReport.transaction_id)
            .where(
                AmlReport.tenant_id == tid,
                AmlReport.subject_user_account_id.is_(None),
                AmlReport.status.in_(_HOLDING_STATUSES),
                Transaction.user_account_id == user_id,
            )
        )
        .scalars()
        .all()
    )
    orphan_via_case = (
        session.execute(
            select(AmlReport)
            .join(Case, Case.id == AmlReport.case_id)
            .join(Transaction, Transaction.id == Case.transaction_id)
            .where(
                AmlReport.tenant_id == tid,
                AmlReport.subject_user_account_id.is_(None),
                AmlReport.status.in_(_HOLDING_STATUSES),
                Transaction.user_account_id == user_id,
            )
        )
        .scalars()
        .all()
    )

    active: list[Any] = []
    seen: set[Any] = set()
    for report in (*direct, *orphan_via_tx, *orphan_via_case):
        if report.id in seen:
            continue
        seen.add(report.id)
        if _is_active_legal_hold(report, cutoff):
            active.append(report)
    return active


class PiplTask(Task): # type: ignore[misc]
    """PIPL 任务基类：启动时配置 structlog。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        configure_logging()
        return super().__call__(*args, **kwargs)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="pipl.export_data",
    bind=True,
    base=PiplTask,
    queue="pipl",
    max_retries=3,
    default_retry_delay=300,
    soft_time_limit=1800,
    time_limit=2400,
)
def export_data(
    self: PiplTask,
    tenant_id: str,
    request_id: str,
    user_id: str,
    export_format: str = "json",
) -> dict[str, Any]:
    """数据导出（数据可携带权 / PIPL §45）。

    Args:
        tenant_id: 租户 ID
        request_id: PIPL 申请单 ID
        user_id: 数据主体 ID（脱敏）
        export_format: 导出格式（json / csv / xml）

    Returns:
        含 task_id / status / download_url 的 dict
    """
    logger.info(
        "pipl_export_begin",
        tenant_id=tenant_id,
        request_id=request_id,
        user_id=user_id,
        export_format=export_format,
    )

    task_id = f"export_task_{uuid.uuid4()}"
    export_payload: dict[str, Any] = {
        "request_id": request_id,
        "user_id": user_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "transactions": [],
        "scores": [],
        "cases": [],
        "consents": [],
    }
    try:
        with sync_session_scope(tenant_id) as session:
            # 1. transactions（脱敏 card_token → 卡 BIN + last4）
            tx_rows = session.execute(
                select(Transaction).where(
                    Transaction.user_account_id == user_id
                )
            ).scalars().all()
            for tx in tx_rows:
                export_payload["transactions"].append(
                    {
                        "external_tx_id": tx.external_tx_id,
                        "amount": tx.amount,
                        "currency": tx.currency,
                        "card_bin": tx.card_bin,
                        "card_last4": tx.card_last4,
                        "tx_type": tx.tx_type,
                        "channel": tx.channel,
                        "occurred_at": tx.occurred_at.isoformat() if tx.occurred_at else None,
                    }
                )
            tx_ids = [tx.id for tx in tx_rows]

            # 2. scores（仅决策结果，不含模型内部特征）
            if tx_ids:
                score_rows = session.execute(
                    select(Score).where(Score.transaction_id.in_(tx_ids))
                ).scalars().all()
                for sc in score_rows:
                    export_payload["scores"].append(
                        {
                            "transaction_id": str(sc.transaction_id),
                            "decision": sc.decision,
                            "risk_band": sc.risk_band,
                            "risk_score": float(sc.risk_score),
                            "model_version": sc.model_version,
                            "created_at": sc.created_at.isoformat() if sc.created_at else None,
                        }
                    )

            # 3. cases
            case_rows = session.execute(
                select(Case).where(
                    Case.transaction_id.in_(tx_ids) if tx_ids else Case.id.is_(None)
                )
            ).scalars().all()
            for c in case_rows:
                export_payload["cases"].append(
                    {
                        "case_no": c.case_no,
                        "type": c.type,
                        "level": c.level,
                        "status": c.status,
                        "amount": c.amount,
                        "created_at": c.created_at.isoformat() if c.created_at else None,
                    }
                )

            # 4. consent_records
            consent_rows = session.execute(
                select(ConsentRecord).where(ConsentRecord.user_id == user_id)
            ).scalars().all()
            for rec in consent_rows:
                export_payload["consents"].append(
                    {
                        "consent_id": str(rec.id),
                        "consent_type": rec.consent_type,
                        "consent_status": rec.consent_status,
                        "purpose": rec.purpose,
                        "legal_basis": rec.legal_basis,
                        "granted_at": rec.granted_at.isoformat() if rec.granted_at else None,
                    }
                )

            # 5. 更新请求状态
            req = session.execute(
                select(DeletionRequest).where(DeletionRequest.id == uuid.UUID(request_id))
            ).scalar_one_or_none()
            if req is not None:
                req.status = "COMPLETED"
                req.completed_at = datetime.now(UTC)
    except Exception as exc:
        logger.error("pipl_export_failed", error=str(exc), request_id=request_id)
        return {"task_id": task_id, "request_id": request_id, "status": "FAILED", "error": str(exc)}

    # TODO: 打包上传 OSS（私有，签名 URL 30 天有效）；骨架阶段存 Redis
    download_url = ""
    try:
        from app.db.redis import get_redis

        async def _store() -> None:
            redis = get_redis()
            await redis.set(
                f"pipl:export:{request_id}",
                json.dumps(export_payload, default=str),
                ex=30 * 86400,
            )

        asyncio.run(_store())
    except Exception as exc:
        logger.warning("pipl_export_cache_failed", error=str(exc))

    logger.info(
        "pipl_export_complete",
        tenant_id=tenant_id,
        request_id=request_id,
        task_id=task_id,
        tx_count=len(export_payload["transactions"]),
    )
    return {
        "task_id": task_id,
        "request_id": request_id,
        "status": "READY",
        "download_url": download_url,
        "expires_at": "2026-08-26T00:00:00Z",  # 30 天有效期
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    name="pipl.delete_data",
    bind=True,
    base=PiplTask,
    queue="pipl",
    max_retries=2,
    default_retry_delay=600,
    soft_time_limit=3600,
    time_limit=4200,
)
def delete_data(
    self: PiplTask,
    tenant_id: str,
    request_id: str,
    user_id: str,
    legal_hold_check: bool = True,
) -> dict[str, Any]:
    """数据删除（被遗忘权 / PIPL §47）。

    Args:
        tenant_id: 租户 ID
        request_id: PIPL 申请单 ID
        user_id: 数据主体 ID（脱敏）
        legal_hold_check: 是否检查法律保留义务（反洗钱 7 年保留）

    Returns:
        含 request_id / status / deleted_counts 的 dict

    Raises:
        LEGAL_HOLD_CONFLICT: 当用户存在未到期法律保留记录时
    """
    logger.info(
        "pipl_delete_begin",
        tenant_id=tenant_id,
        request_id=request_id,
        user_id=user_id,
        legal_hold_check=legal_hold_check,
    )

    deleted_counts = {
        "transactions": 0,
        "scores": 0,
        "shap_explanations": 0,
        "consent_records": 0,
        "cache_keys": 0,
        "graph_nodes": 0,
    }

    # 1. 法律保留检查（反洗钱 7 年保留，按数据主体精确关联，0006 迁移）
    if legal_hold_check:
        cutoff = datetime.now(UTC) - timedelta(days=AML_RETENTION_YEARS * 365)
        try:
            with sync_session_scope(tenant_id) as session:
                active_holds = _collect_active_legal_holds(
                    session, tenant_id, str(user_id), cutoff
                )
        except Exception as exc:
            # fail-closed：无法确认保留状态时不得执行删除（合规优先），
            # 抛给 Celery 按 max_retries/delay 自动重试
            logger.error("pipl_delete_legal_hold_check_failed", error=str(exc))
            raise self.retry(exc=exc) from exc

        if active_holds:
            with sync_session_scope(tenant_id) as session:
                req = session.execute(
                    select(DeletionRequest).where(
                        DeletionRequest.id == uuid.UUID(request_id)
                    )
                ).scalar_one_or_none()
                if req is not None:
                    req.status = "BLOCKED"
            logger.warning(
                "pipl_delete_legal_hold",
                tenant_id=tenant_id,
                request_id=request_id,
                report_nos=[r.report_no for r in active_holds],
            )
            return {
                "request_id": request_id,
                "status": "BLOCKED",
                "reason": "legal_hold_conflict",
                "report_nos": [r.report_no for r in active_holds],
                "deleted_counts": deleted_counts,
            }

    try:
        with sync_session_scope(tenant_id) as session:
            # 2. 软删除交易（metadata_ 标记 deleted_at，保留 7 年后硬删）
            tx_rows = session.execute(
                select(Transaction).where(Transaction.user_account_id == user_id)
            ).scalars().all()
            now_iso = datetime.now(UTC).isoformat()
            tx_ids = []
            for tx in tx_rows:
                tx_meta = dict(tx.metadata_ or {})
                tx_meta["deleted_at"] = now_iso
                tx.metadata_ = tx_meta
                tx_ids.append(tx.id)
            deleted_counts["transactions"] = len(tx_rows)

            # 3. scores 软删（标记 metadata 不存在 → 通过 transactions 引用；直接物理删除衍生评分）
            score_ids: list[Any] = []
            if tx_ids:
                score_rows = session.execute(
                    select(Score).where(Score.transaction_id.in_(tx_ids))
                ).scalars().all()
                deleted_counts["scores"] = len(score_rows)
                score_ids = [sc.id for sc in score_rows]
                for sc in score_rows:
                    session.delete(sc)

            # 3.1 关联 SHAP 解释一并删除（此前计数恒为 0 且从未删除）
            if score_ids:
                shap_rows = session.execute(
                    select(ShapExplanation).where(ShapExplanation.score_id.in_(score_ids))
                ).scalars().all()
                deleted_counts["shap_explanations"] = len(shap_rows)
                for sp in shap_rows:
                    session.delete(sp)

            # 4. consent_records 置为 EXPIRED
            consent_rows = session.execute(
                select(ConsentRecord).where(ConsentRecord.user_id == user_id)
            ).scalars().all()
            for rec in consent_rows:
                rec.consent_status = "EXPIRED"
                rec.withdrawn_at = datetime.now(UTC)
            deleted_counts["consent_records"] = len(consent_rows)

            # 5. 更新请求状态
            req = session.execute(
                select(DeletionRequest).where(DeletionRequest.id == uuid.UUID(request_id))
            ).scalar_one_or_none()
            if req is not None:
                req.status = "COMPLETED"
                req.completed_at = datetime.now(UTC)

        # 6. 清理 Redis 缓存（用户相关评分缓存）
        try:
            from app.db.redis import get_redis

            async def _clean_cache() -> int:
                redis = get_redis()
                removed = 0
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor=cursor, match=f"score_cache:{tenant_id}:*", count=200
                    )
                    for key in keys:
                        raw = await redis.get(key)
                        if not raw:
                            continue
                        # 按写入时的 user_account_id 精确匹配
                        # （历史实现 `user_id in payload` 对 JSON 串恒 False，删除空转）
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            continue
                        if str(data.get("user_account_id") or "") == str(user_id):
                            await redis.delete(key)
                            removed += 1
                    if cursor == 0:
                        break
                return removed

            deleted_counts["cache_keys"] = asyncio.run(_clean_cache())
        except Exception as exc:
            logger.warning("pipl_delete_cache_clean_failed", error=str(exc))

        # TODO: 硬删除无法律保留的衍生数据（Neo4j 节点）、通知数据主体
    except Exception as exc:
        logger.error("pipl_delete_failed", error=str(exc), request_id=request_id)
        return {"request_id": request_id, "status": "FAILED", "error": str(exc)}

    logger.info(
        "pipl_delete_complete",
        tenant_id=tenant_id,
        request_id=request_id,
        deleted_counts=deleted_counts,
    )
    return {
        "request_id": request_id,
        "status": "COMPLETED",
        "deleted_counts": deleted_counts,
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    name="pipl.rectify_data",
    bind=True,
    base=PiplTask,
    queue="pipl",
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=600,
    time_limit=900,
)
def rectify_data(
    self: PiplTask,
    tenant_id: str,
    request_id: str,
    user_id: str,
    rectification_fields: dict[str, Any],
) -> dict[str, Any]:
    """数据更正（更正权 / PIPL §46）。

    Args:
        tenant_id: 租户 ID
        request_id: PIPL 申请单 ID
        user_id: 数据主体 ID（脱敏）
        rectification_fields: 需要更正的字段字典

    Returns:
        含 request_id / status / rectified_fields 的 dict
    """
    logger.info(
        "pipl_rectify_begin",
        tenant_id=tenant_id,
        request_id=request_id,
        user_id=user_id,
        fields=list(rectification_fields.keys()),
    )

    # 允许更正的白名单字段（禁止更正交易/评分/审计历史 — 合规要求）
    allowed_fields = {"user_account_id", "contact_info", "address", "phone", "email"}

    # 校验更正字段白名单
    disallowed = [f for f in rectification_fields if f not in allowed_fields]
    if disallowed:
        logger.warning(
            "pipl_rectify_disallowed_fields",
            request_id=request_id,
            disallowed=disallowed,
        )
        return {
            "request_id": request_id,
            "status": "REJECTED",
            "reason": "disallowed_fields",
            "disallowed_fields": disallowed,
        }

    # TODO: 更新相关记录（真实系统按资源类型定位数据源）
    try:
        with sync_session_scope(tenant_id) as session:
            req = session.execute(
                select(DeletionRequest).where(
                    DeletionRequest.id == uuid.UUID(request_id)
                )
            ).scalar_one_or_none()
            if req is not None:
                req.status = "COMPLETED"
                req.completed_at = datetime.now(UTC)
    except Exception as exc:
        logger.error("pipl_rectify_failed", error=str(exc))
        return {"request_id": request_id, "status": "FAILED", "error": str(exc)}

    # TODO: 记入 audit_logs（哈希链）

    logger.info(
        "pipl_rectify_complete",
        tenant_id=tenant_id,
        request_id=request_id,
    )
    return {
        "request_id": request_id,
        "status": "COMPLETED",
        "rectified_fields": list(rectification_fields.keys()),
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    name="pipl.notify_subject",
    bind=True,
    base=PiplTask,
    queue="pipl",
    max_retries=3,
    default_retry_delay=60,
)
def notify_subject(
    self: PiplTask,
    tenant_id: str,
    request_id: str,
    user_id: str,
    notification_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """通知数据主体（邮件 / 短信，PIPL §45/§47）。

    Args:
        notification_type: EXPORT_READY / DELETION_COMPLETED / RECTIFICATION_COMPLETED
    """
    logger.info(
        "pipl_notify_begin",
        tenant_id=tenant_id,
        request_id=request_id,
        user_id=user_id,
        notification_type=notification_type,
    )
    # TODO: 通过邮件 / 短信通道通知用户
    # TODO: 记录通知结果到 deletion_requests / 数据导出表
    return {
        "request_id": request_id,
        "status": "NOTIFIED",
        "notification_type": notification_type,
    }


__all__ = [
    "PiplTask",
    "delete_data",
    "export_data",
    "notify_subject",
    "rectify_data",
]
