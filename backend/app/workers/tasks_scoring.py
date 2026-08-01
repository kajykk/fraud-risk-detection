"""评分相关异步任务（D03 V1.1 §4.1 / ADR-014）。

任务清单：
- persist_score: 异步持久化评分到 scores 表（Kafka Consumer 触发）
- persist_transaction: 异步持久化交易到 transactions 表
- generate_case: 高风险交易自动生成案件（risk_band=HIGH/CRITICAL）
- drift_check: 模型漂移检测（每小时定时）
- psi_report: PSI 7d 报告生成（每天定时）
"""

from __future__ import annotations

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

        from app.services.scoring import scoring_orchestrator

        result = asyncio.run(scoring_orchestrator.score_sync(transaction, tenant_id))
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
    """异步持久化评分到 scores 表（Kafka Consumer 触发，D03 ADR-014）。"""
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
    """异步持久化交易到 transactions 表（Kafka Consumer 触发）。"""
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
    return {
        "status": "CREATED",
        "case_id": str(case.id),
        "case_level": case_level,
        "transaction_id": transaction_id,
    }


@celery_app.task(
    name="scoring.drift_check",
    bind=True,
    base=LoggedTask,
    queue="scoring",
)
def drift_check(self: LoggedTask) -> dict[str, Any]:
    """模型漂移检测（每小时定时，D03 §4.5）。

    计算最近 1h 评分分布 vs 最近 7d（不含 1h）参考分布的 PSI，
    结果写入 drift_alerts 表；PSI ≥ 0.25（CRITICAL）触发 L2 模型级 Kill Switch。
    """
    logger.info("drift_check_begin")
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    week_ago = now - timedelta(days=7)

    alert_counts: dict[str, Any] = {"checked": 0, "drifted": 0, "critical": 0}
    try:
        # 遍历所有模型（含全局，按 model_version 聚合）
        with sync_session_scope() as session:
            versions = session.execute(
                select(ModelVersion.version).distinct()
            ).scalars().all()

        for model_version in versions:
            try:
                with sync_session_scope() as session:
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

                with sync_session_scope() as session:
                    session.add(
                        DriftAlert(
                            tenant_id=None,
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
                    model_version=model_version,
                    psi=round(psi, 4),
                    severity=severity,
                )
            except Exception as exc:
                logger.error("drift_check_model_failed", model_version=model_version, error=str(exc))

        # PSI ≥ 0.25（CRITICAL）→ L2 模型级 Kill Switch（ADR-013）
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
    """PSI 7d 报表生成（每天 02:00 定时，D03 §4.5）。"""
    logger.info("psi_report_begin")
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    reports: list[dict[str, Any]] = []
    try:
        with sync_session_scope() as session:
            versions = session.execute(
                select(ModelVersion.version).distinct()
            ).scalars().all()

        for model_version in versions:
            with sync_session_scope() as session:
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
                    "model_version": model_version,
                    "sample_count": len(scores),
                    "avg_risk_score": round(avg_score, 4),
                    "high_risk_ratio": round(high_ratio, 4),
                    "period": f"{week_ago.isoformat()}/{now.isoformat()}",
                }
            )
            session.add(
                DriftAlert(
                    tenant_id=None,
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
