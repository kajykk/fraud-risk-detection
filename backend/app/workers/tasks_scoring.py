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
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.core.logging import configure_logging
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


class LoggedTask(Task):
    """自定义 Task 基类：在 worker 进程启动时配置 structlog。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        configure_logging()
        return super().__call__(*args, **kwargs)


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
    """异步持久化评分到 scores 表（Kafka Consumer 触发，D03 ADR-014）。

    Args:
        tenant_id: 租户 ID
        transaction_id: 交易 ID（UUID）
        score_data: 评分结果（risk_score / risk_band / decision / rule_hits / ...）
    """
    logger.info(
        "persist_score_begin",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        decision=score_data.get("decision"),
    )

    # TODO: 同步 SQLAlchemy session 写入 scores 表
    # from sqlalchemy.ext.asyncio import AsyncSession
    # from app.db.session import session_scope
    # from app.models.transaction import Score
    # async with session_scope(tenant_id=tenant_id) as session:
    #     score = Score(
    #         tenant_id=uuid.UUID(tenant_id),
    #         transaction_id=uuid.UUID(transaction_id),
    #         ...
    #     )
    #     session.add(score)

    logger.info(
        "persist_score_complete",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        note="TODO: implement DB persistence",
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
    # TODO: 写入 transactions 表
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
    case_id = f"case_{uuid.uuid4()}"

    logger.info(
        "generate_case_begin",
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        risk_band=risk_band,
        case_level=case_level,
        case_id=case_id,
    )

    # TODO: 写入 cases 表 + case_events 表
    return {
        "status": "CREATED",
        "case_id": case_id,
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

    计算指标（基准 §3.12）：
    - PSI（默认）
    - KL / KS / Wasserstein（备选）

    阈值（基准 §3.12）：
    - PSI < 0.1  → LOW
    - 0.1 ≤ PSI < 0.25 → MEDIUM
    - 0.25 ≤ PSI < 0.5 → HIGH
    - PSI ≥ 0.5 → CRITICAL（触发 Kill Switch L2_MODEL）
    """
    logger.info("drift_check_begin")
    # TODO: 读取最近 1h 评分分布 vs 训练集分布，计算 PSI
    # TODO: 写入 drift_alerts 表
    # TODO: PSI ≥ 0.5 触发 kill_switch.activate(L2_MODEL, ...)
    return {"status": "COMPLETED", "note": "TODO: implement drift detection"}


@celery_app.task(
    name="scoring.psi_report",
    bind=True,
    base=LoggedTask,
    queue="scoring",
)
def psi_report(self: LoggedTask) -> dict[str, Any]:
    """PSI 7d 报表生成（每天 02:00 定时，D03 §4.5）。"""
    logger.info("psi_report_begin")
    # TODO: 聚合 7 天 PSI 指标生成报表
    return {"status": "COMPLETED", "note": "TODO: implement PSI 7d report"}


__all__ = [
    "LoggedTask",
    "drift_check",
    "generate_case",
    "persist_score",
    "persist_transaction",
    "psi_report",
]
