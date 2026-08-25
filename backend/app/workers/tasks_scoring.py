"""评分相关异步任务（D03 V1.1 §4.1 / ADR-014）。

任务清单：
- persist_score: 异步持久化评分到 scores 表（备用任务；主路径已同步落库，ADR-016）
- persist_transaction: 异步持久化交易到 transactions 表
- generate_case: 高风险交易自动生成案件（risk_band=HIGH/CRITICAL）
- drift_check: 模型漂移检测（每小时定时）
- psi_report: PSI 7d 报告生成（每天定时）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.core.logging import configure_logging
from app.db.sync_session import sync_session_scope
from app.models.case import Case, CaseEvent
from app.models.model_version import DriftAlert, ModelVersion
from app.models.transaction import Score, Transaction
from app.services.drift import classify_severity, compute_psi
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


class LoggedTask(Task):
    """自定义 Task 基类：在 worker 进程启动时配置 structlog。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        configure_logging()
        return super().__call__(*args, **kwargs)


@celery_app.task(
    name="scoring.score_async",
    bind=True,
    base=LoggedTask,
    queue="scoring",
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=120,
    time_limit=180,
)
def score_async(
    self: LoggedTask,
    tenant_id: str,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    """异步深度评分（在 worker 中运行完整评分主路径）。"""
    logger.info(
        "score_async_begin",
        tenant_id=tenant_id,
        external_tx_id=transaction.get("external_tx_id"),
    )
    try:
        import asyncio
        import threading

        from app.services.scoring import scoring_orchestrator

        async def _run() -> Any:
            return await scoring_orchestrator.score_sync(transaction, tenant_id)

        # Celery 同步任务上下文通常无事件循环；eager 模式（测试）可能已处于
        # 运行中的 loop（asyncio.run 会抛 RuntimeError 且丢弃协程），
        # 此时在独立线程中启动专属 loop 执行。
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if in_loop:
            box: dict[str, Any] = {}

            def _runner() -> None:
                box["result"] = asyncio.run(_run())

            worker_thread = threading.Thread(target=_runner, name="score_async_runner")
            worker_thread.start()
            worker_thread.join()
            result = box["result"]
        else:
            result = asyncio.run(_run())
        logger.info(
            "score_async_complete",
            tenant_id=tenant_id,
            decision=result.decision.value,
            risk_score=result.risk_score,
        )
        return {
            "status": "COMPLETED",
            "decision_id": result.decision_id,
            "decision": result.decision.value,
            "risk_score": result.risk_score,
            "risk_band": result.risk_band.value,
            "latency_ms": result.latency_ms,
        }
    except Exception as exc:
        logger.error("score_async_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1)) from exc


@celery_app.task(
    name="scoring.persist_score",
    bind=True,
    base=LoggedTask,
    queue="scoring",
    max_retries=5,
    default_retry_delay=30,
)
def persist_score(
    self: LoggedTask,
    tenant_id: str,
    transaction_id: str,
    score_data: dict[str, Any],
) -> dict[str, Any]:
    """异步持久化评分到 scores 表（备用任务；主路径已同步落库，ADR-016）。"""
    logger.info(
        "persist_score_begin",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        decision=score_data.get("decision"),
    )
    try:
        with sync_session_scope(tenant_id) as session:
            score = Score(
                tenant_id=uuid.UUID(tenant_id),
                transaction_id=uuid.UUID(transaction_id),
                model_version=score_data.get("model_version", "unknown"),
                rule_version=score_data.get("rule_version", "rule_v1"),
                risk_score=Decimal(str(score_data.get("risk_score", 0.0))),
                risk_band=score_data.get("risk_band", "LOW"),
                decision=score_data.get("decision", "ALLOW"),
                rule_hits=score_data.get("rule_hits", []),
                modality_scores=score_data.get("modality_scores", {}),
                feature_values=score_data.get("feature_values", {}),
                cached=score_data.get("cached", False),
                latency_ms=score_data.get("latency_ms", 0),
            )
            session.add(score)
    except Exception as exc:
        logger.error("persist_score_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1)) from exc

    logger.info(
        "persist_score_complete",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
    )
    return {"status": "PERSISTED", "transaction_id": transaction_id}


@celery_app.task(
    name="scoring.persist_transaction",
    bind=True,
    base=LoggedTask,
    queue="scoring",
    max_retries=5,
    default_retry_delay=30,
)
def persist_transaction(
    self: LoggedTask,
    tenant_id: str,
    transaction_data: dict[str, Any],
) -> dict[str, Any]:
    """异步持久化交易到 transactions 表（备用任务；主路径已同步落库）。"""
    logger.info(
        "persist_transaction_begin",
        tenant_id=tenant_id,
        external_tx_id=transaction_data.get("external_tx_id"),
    )
    try:
        occurred_at_str = transaction_data.get("occurred_at", "")
        if occurred_at_str:
            occurred_at = datetime.fromisoformat(str(occurred_at_str).replace("Z", "+00:00"))
        else:
            occurred_at = datetime.now(UTC)

        with sync_session_scope(tenant_id) as session:
            tx = Transaction(
                tenant_id=uuid.UUID(tenant_id),
                external_tx_id=transaction_data.get(
                    "external_tx_id", str(uuid.uuid4())
                ),
                card_token=transaction_data.get("card_token", "tok_unknown"),
                card_bin=transaction_data.get("card_bin", "000000"),
                card_last4=transaction_data.get("card_last4", "0000"),
                amount=int(transaction_data.get("amount", 0)),
                currency=transaction_data.get("currency", "CNY"),
                tx_type=transaction_data.get("tx_type"),
                channel=transaction_data.get("channel"),
                is_3ds_verified=transaction_data.get("is_3ds_verified", False),
                merchant_category=transaction_data.get("merchant_category"),
                user_account_id=transaction_data.get("user_id"),
                note_text=transaction_data.get("note_text"),
                risk_features=transaction_data.get("risk_features", {}),
                occurred_at=occurred_at,
                received_at=datetime.now(UTC),
                metadata_={
                    "amount": transaction_data.get("amount", 0),
                    "currency": transaction_data.get("currency", "CNY"),
                    "merchant_id": transaction_data.get("merchant_id"),
                },
            )
            session.add(tx)
    except Exception as exc:
        logger.error("persist_transaction_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1)) from exc

    logger.info(
        "persist_transaction_complete",
        tenant_id=tenant_id,
        external_tx_id=transaction_data.get("external_tx_id"),
    )
    return {"status": "PERSISTED", "external_tx_id": transaction_data.get("external_tx_id")}


@celery_app.task(
    name="scoring.generate_case",
    bind=True,
    base=LoggedTask,
    queue="scoring",
    max_retries=3,
    default_retry_delay=60,
)
def generate_case(
    self: LoggedTask,
    tenant_id: str,
    transaction_id: str,
    score_data: dict[str, Any],
) -> dict[str, Any]:
    """高风险交易自动生成案件（risk_band in [HIGH, CRITICAL]）。

    案件等级（基准 §3.7）：
    - CRITICAL → P0
    - HIGH → P1
    """
    risk_band = score_data.get("risk_band", "LOW")
    if risk_band not in ("HIGH", "CRITICAL"):
        return {"status": "SKIPPED", "reason": f"risk_band={risk_band}"}

    case_level = "P0" if risk_band == "CRITICAL" else "P1"
    case_no = f"CS{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"

    logger.info(
        "generate_case_begin",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        risk_band=risk_band,
        case_level=case_level,
    )
    try:
        with sync_session_scope(tenant_id) as session:
            existing = session.execute(
                select(Case).where(
                    Case.transaction_id == uuid.UUID(transaction_id),
                    Case.status.in_(["OPEN", "IN_REVIEW", "CONFIRMED"]),
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {"status": "SKIPPED", "reason": "case_already_exists", "case_id": str(existing.id)}

            case = Case(
                tenant_id=uuid.UUID(tenant_id),
                transaction_id=uuid.UUID(transaction_id),
                score_id=uuid.UUID(score_data["score_id"]) if score_data.get("score_id") else None,
                case_no=case_no,
                type="FRAUD",
                level=case_level,
                status="OPEN",
                amount=int(score_data.get("amount", 0)),
                description=score_data.get("description"),
                graph_summary={},
            )
            session.add(case)
            session.flush()
            session.add(
                CaseEvent(
                    tenant_id=uuid.UUID(tenant_id),
                    case_id=case.id,
                    action="CREATED",
                    from_status=None,
                    to_status="OPEN",
                    operator_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                    comment=f"auto-generated from {risk_band} score",
                )
            )
    except Exception as exc:
        logger.error("generate_case_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1)) from exc

    logger.info(
        "generate_case_complete",
        tenant_id=tenant_id,
        case_no=case_no,
        case_level=case_level,
        transaction_id=transaction_id,
    )
    _notify_case_created(
        tenant_id=tenant_id,
        case_id=str(case.id),
        case_no=case_no,
        case_level=case_level,
        transaction_id=transaction_id,
        amount=int(score_data.get("amount", 0)),
    )
    return {
        "status": "CREATED",
        "case_id": str(case.id),
        "case_level": case_level,
        "transaction_id": transaction_id,
    }


def _notify_case_created(
    *,
    tenant_id: str,
    case_id: str,
    case_no: str,
    case_level: str,
    transaction_id: str,
    amount: int,
) -> None:
    """建案成功后的通知扇出（fire-and-forget，失败仅告警）：

    1. frd:ws_events 发布 case.created（前端实时刷新案件列表）
    2. 构造 webhook_event（case.created）并按租户 ACTIVE webhook 商户
       调度 webhook.deliver 投递
    """
    # structlog logger（支持 kwargs；模块级 stdlib task logger 的
    # warning/error 不接受关键字上下文）
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    payload = {
        "case_id": case_id,
        "case_no": case_no,
        "level": case_level,
        "status": "OPEN",
        "transaction_id": transaction_id,
        "amount": amount,
    }
    try:
        asyncio.run(_notify_case_created_async(tenant_id, payload))
    except Exception as exc:
        logger.warning("case_created_notify_failed", case_no=case_no, error=str(exc))


async def _notify_case_created_async(tenant_id: str, payload: dict[str, Any]) -> None:
    """通知扇出的异步实现：WS 推送 + webhook 事件构造与调度。"""
    from sqlalchemy import select

    from app.core.logging import get_logger
    from app.db.sync_session import sync_session_scope
    from app.models.tenant import Merchant
    from app.services.webhook import store_webhook_event
    from app.services.ws_events import publish_ws_event

    logger = get_logger(__name__)

    # 1. WS 实时推送
    await publish_ws_event(tenant_id, "case.created", payload)

    # 2. Webhook 事件投递（eager 模式下不走 broker）
    from app.workers.celery_app import celery_app

    if celery_app.conf.task_always_eager:
        return
    with sync_session_scope(tenant_id) as session:
        rows = session.execute(
            select(Merchant.id).where(
                Merchant.tenant_id == uuid.UUID(tenant_id),
                Merchant.webhook_url.isnot(None),
                Merchant.status == "ACTIVE",
            )
        )
        merchant_ids = [str(m) for m in rows.scalars().all()]
    for merchant_id in merchant_ids:
        event_id = await store_webhook_event(
            tenant_id=tenant_id,
            event_type="case.created",
            data=payload,
            webhook_id=merchant_id,
        )
        if event_id is None:
            continue
        try:
            celery_app.send_task("webhook.deliver", args=[event_id, merchant_id])
        except Exception as exc:
            logger.warning("celery_send_task_failed", task="webhook.deliver", error=str(exc))


@celery_app.task(
    name="scoring.drift_check",
    bind=True,
    base=LoggedTask,
    queue="scoring",
)
def drift_check(self: LoggedTask) -> dict[str, Any]:
    """模型漂移检测（每小时定时，D03 §4.5）。

    按租户迭代（tenants 注册表，RLS 隔离各租户数据）：
    最近 1h 评分分布 vs 最近 7d（不含 1h）参考分布的 PSI，
    结果写入各租户自己的 drift_alerts 表；
    PSI ≥ 0.25（CRITICAL）触发 L2 模型级 Kill Switch（全局熔断）。
    """
    logger.info("drift_check_begin")
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    week_ago = now - timedelta(days=7)

    alert_counts: dict[str, Any] = {"checked": 0, "drifted": 0, "critical": 0}
    try:
        # tenants 表无 RLS（租户注册表），可全局枚举
        from app.models.tenant import Tenant

        with sync_session_scope() as session:
            tenant_ids = session.execute(select(Tenant.id)).scalars().all()

        for tenant_id in tenant_ids:
            tenant_str = str(tenant_id)
            try:
                with sync_session_scope(tenant_str) as session:
                    versions = session.execute(
                        select(ModelVersion.version).distinct()
                    ).scalars().all()
            except Exception as exc:
                logger.error(
                    "drift_check_tenant_failed",
                    tenant_id=tenant_str,
                    error=str(exc),
                )
                continue

            for model_version in versions:
                try:
                    with sync_session_scope(tenant_str) as session:
                        current = session.execute(
                            select(Score.risk_score).where(
                                Score.model_version == model_version,
                                Score.created_at >= hour_ago,
                            )
                        ).scalars().all()
                        reference = session.execute(
                            select(Score.risk_score).where(
                                Score.model_version == model_version,
                                Score.created_at >= week_ago,
                                Score.created_at < hour_ago,
                            )
                        ).scalars().all()

                    if len(current) < 30 or len(reference) < 100:
                        continue  # 样本不足跳过

                    psi = compute_psi([float(s) for s in current], [float(s) for s in reference])
                    severity, is_drifted = classify_severity(psi)
                    alert_counts["checked"] += 1
                    if is_drifted:
                        alert_counts["drifted"] += 1
                    if severity == "CRITICAL":
                        alert_counts["critical"] += 1

                    with sync_session_scope(tenant_str) as session:
                        session.add(
                            DriftAlert(
                                tenant_id=uuid.UUID(tenant_str),
                                model_version=model_version,
                                modality="fused",
                                metric_type="PSI",
                                metric_value=Decimal(str(round(psi, 4))),
                                threshold=Decimal("0.1"),
                                severity=severity,
                                detected_at=now,
                            )
                        )

                    logger.info(
                        "drift_check_model",
                        tenant_id=tenant_str,
                        model_version=model_version,
                        psi=round(psi, 4),
                        severity=severity,
                    )
                except Exception as exc:
                    logger.error(
                        "drift_check_model_failed",
                        tenant_id=tenant_str,
                        model_version=model_version,
                        error=str(exc),
                    )

        # PSI ≥ 0.25（CRITICAL）→ L2 模型级 Kill Switch（ADR-013，全局熔断）
        if alert_counts["critical"] > 0:
            # Celery 同步上下文：创建临时事件循环调用异步 kill_switch
            import asyncio

            from app.services.kill_switch import KillSwitchScope, kill_switch

            asyncio.run(
                kill_switch.activate(
                    scope=KillSwitchScope.L2_MODEL,
                    target="fused",
                    reason=f"drift_check critical: {alert_counts['critical']} model(s) PSI>=0.25",
                    operator_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                )
            )
    except Exception as exc:
        logger.error("drift_check_failed", error=str(exc))
        return {"status": "FAILED", "error": str(exc)}

    logger.info("drift_check_complete", **alert_counts)
    return {"status": "COMPLETED", **alert_counts}


@celery_app.task(
    name="scoring.psi_report",
    bind=True,
    base=LoggedTask,
    queue="scoring",
)
def psi_report(self: LoggedTask) -> dict[str, Any]:
    """PSI 7d 报表生成（每天 02:00 定时，D03 §4.5）。

    按租户迭代（RLS 隔离），报告写入各租户自己的 drift_alerts 表。
    """
    logger.info("psi_report_begin")
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    reports: list[dict[str, Any]] = []
    try:
        from app.models.tenant import Tenant

        with sync_session_scope() as session:
            tenant_ids = session.execute(select(Tenant.id)).scalars().all()

        for tenant_id in tenant_ids:
            tenant_str = str(tenant_id)
            try:
                with sync_session_scope(tenant_str) as session:
                    versions = session.execute(
                        select(ModelVersion.version).distinct()
                    ).scalars().all()
            except Exception as exc:
                logger.error(
                    "psi_report_tenant_failed",
                    tenant_id=tenant_str,
                    error=str(exc),
                )
                continue

            for model_version in versions:
                with sync_session_scope(tenant_str) as session:
                    scores = session.execute(
                        select(Score.risk_score).where(
                            Score.model_version == model_version,
                            Score.created_at >= week_ago,
                        )
                    ).scalars().all()
                if len(scores) < 100:
                    continue
                avg_score = sum(float(s) for s in scores) / len(scores)
                high_ratio = sum(1 for s in scores if float(s) >= 0.6) / len(scores)
                reports.append(
                    {
                        "tenant_id": tenant_str,
                        "model_version": model_version,
                        "sample_count": len(scores),
                        "avg_risk_score": round(avg_score, 4),
                        "high_risk_ratio": round(high_ratio, 4),
                        "period": f"{week_ago.isoformat()}/{now.isoformat()}",
                    }
                )
                with sync_session_scope(tenant_str) as session:
                    session.add(
                        DriftAlert(
                            tenant_id=uuid.UUID(tenant_str),
                            model_version=model_version,
                            modality="fused",
                            metric_type="PSI",
                            metric_value=Decimal(str(round(high_ratio, 4))),
                            threshold=Decimal("0.1"),
                            severity="LOW",
                            detected_at=now,
                        )
                    )
    except Exception as exc:
        logger.error("psi_report_failed", error=str(exc))
        return {"status": "FAILED", "error": str(exc)}

    logger.info("psi_report_complete", model_count=len(reports))
    return {"status": "COMPLETED", "reports": reports}


__all__ = [
    "LoggedTask",
    "drift_check",
    "generate_case",
    "persist_score",
    "persist_transaction",
    "psi_report",
    "score_async",
]
