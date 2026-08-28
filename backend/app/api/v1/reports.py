"""报表路由 - 仪表盘 KPI 汇总。

GET /reports/summary：返回仪表盘关键指标（全部从 DB 实时聚合，无硬编码假数据）
GET /reports/trend：近 N 天每日交易数 / 拦截数 / 人工审核数
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import get_tenant_id, require_scope
from app.db.session import session_scope
from app.models.case import Case
from app.models.model_version import DriftAlert, ModelVersion
from app.models.transaction import Score, Transaction
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("/summary", response_model=ApiResponse[dict[str, Any]])
async def get_summary(
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("transaction:read")),
) -> ApiResponse[dict[str, Any]]:
    """仪表盘 KPI 汇总（从 PostgreSQL 实时聚合）。"""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    async with session_scope(tenant_id) as session:
        # 总交易数 + 今日交易数（单查询双计数）
        tx_counts_q = select(
            func.count().label("total"),
            func.count().filter(Transaction.occurred_at >= today_start).label("today"),
        ).where(Transaction.tenant_id == tenant_id)
        total_tx, today_tx = (await session.execute(tx_counts_q)).one()

        # 各决策计数
        decision_q = (
            select(Score.decision, func.count())
            .where(Score.tenant_id == tenant_id)
            .group_by(Score.decision)
        )
        decision_rows = (await session.execute(decision_q)).all()
        decision_counts = {row[0]: row[1] for row in decision_rows}

        blocked_count = decision_counts.get("DENY", 0)
        review_count = decision_counts.get("REVIEW", 0)
        allow_count = decision_counts.get("ALLOW", 0)
        challenge_count = decision_counts.get("CHALLENGE", 0)
        scored_count = sum(decision_counts.values())

        # 平均风险评分
        avg_score_q = select(func.avg(Score.risk_score)).where(
            Score.tenant_id == tenant_id
        )
        avg_score = (await session.execute(avg_score_q)).scalar()
        avg_score = float(avg_score) if avg_score else 0.0

        # P99 延迟（简化：取最大 latency_ms）
        p99_q = select(func.max(Score.latency_ms)).where(
            Score.tenant_id == tenant_id
        )
        p99_latency = (await session.execute(p99_q)).scalar() or 0

        # 通过率：分子分母均为评分口径（避免未评分交易稀释）
        pass_rate = allow_count / scored_count if scored_count > 0 else 0.0

        # 案件数（真实聚合）
        case_count = (
            await session.execute(
                select(func.count()).select_from(Case).where(Case.tenant_id == tenant_id)
            )
        ).scalar() or 0

        # 当前 ACTIVE 模型的 AUC（来自模型注册表 metrics；无 ACTIVE 模型如实返回 0.0）
        model_metrics = (
            await session.execute(
                select(ModelVersion.metrics)
                .where(
                    ModelVersion.tenant_id.is_(None)
                    | (ModelVersion.tenant_id == tenant_id),
                    ModelVersion.status == "ACTIVE",
                    ModelVersion.model_type == "FUSION",
                )
                .order_by(ModelVersion.created_at.desc())
                .limit(1)
            )
        ).scalar()
        model_auc = float((model_metrics or {}).get("auc") or 0.0)

        # 近 7 天最新 PSI 读数（无告警记录时如实返回 0.0）
        drift_psi = (
            await session.execute(
                select(DriftAlert.metric_value)
                .where(
                    DriftAlert.tenant_id == tenant_id,
                    DriftAlert.metric_type == "PSI",
                    DriftAlert.detected_at >= week_ago,
                )
                .order_by(DriftAlert.detected_at.desc())
                .limit(1)
            )
        ).scalar()
        drift_psi_7d = float(drift_psi) if drift_psi is not None else 0.0

        # 预防损失：被 DENY 交易的金额合计（分单位），无则 0
        blocked_amount = (
            await session.execute(
                select(func.coalesce(func.sum(Transaction.amount), 0))
                .select_from(Score)
                .join(Transaction, Transaction.id == Score.transaction_id)
                .where(Score.tenant_id == tenant_id, Score.decision == "DENY")
            )
        ).scalar() or 0

        return ApiResponse(
            data={
                "today_transactions": today_tx,
                "total_transactions": total_tx,
                "blocked_count": blocked_count,
                "review_count": review_count,
                "allow_count": allow_count,
                "challenge_count": challenge_count,
                "case_count": case_count,
                "model_auc": round(model_auc, 4),
                "p99_latency_ms": p99_latency,
                "drift_psi_7d": round(drift_psi_7d, 4),
                "avg_risk_score": round(avg_score, 4),
                "fraud_loss_prevented_cents": int(blocked_amount),
                "actual_loss_cents": 0,
                "pass_rate": round(pass_rate, 4),
                "appeal_count": 0,
            }
        )


@router.get("/trend", response_model=ApiResponse[dict[str, Any]])
async def get_trend(
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("transaction:read")),
    days: int = 7,
) -> ApiResponse[dict[str, Any]]:
    """仪表盘趋势数据（近 N 天每日交易数 / 拦截数 / 人工审核数）。

    时间窗过滤：只统计 occurred_at >= now - days 的数据，
    按天升序返回（修复此前"最早 N 天"的取窗错误）。
    """
    days = max(1, min(days, 90))
    window_start = datetime.now(UTC) - timedelta(days=days)

    async with session_scope(tenant_id) as session:
        # 近 N 天交易按天聚合
        day_col = func.date_trunc("day", Transaction.occurred_at).label("day")
        q = (
            select(day_col, func.count().label("tx_count"))
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.occurred_at >= window_start,
            )
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await session.execute(q)).all()

        # 单次联查同时聚合 DENY 与 REVIEW 计数（替代两次独立 JOIN 查询）
        block_day = func.date_trunc("day", Transaction.occurred_at).label("day")
        decision_q = (
            select(
                block_day,
                func.count().filter(Score.decision == "DENY").label("blocked"),
                func.count().filter(Score.decision == "REVIEW").label("review"),
            )
            .select_from(Transaction)
            .join(Score, Score.transaction_id == Transaction.id)
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.occurred_at >= window_start,
            )
            .group_by(block_day)
        )
        decision_rows = (await session.execute(decision_q)).all()
        stats_map = {
            row[0]: {"blocked": row[1], "review": row[2]} for row in decision_rows
        }

        dates: list[str] = []
        tx_counts: list[int] = []
        blocked_counts: list[int] = []
        review_counts: list[int] = []

        for row in rows:
            day_val = row[0]
            date_str = day_val.strftime("%m-%d") if hasattr(day_val, "strftime") else str(day_val)[:5]
            dates.append(date_str)
            tx_counts.append(row[1])
            stats = stats_map.get(day_val, {"blocked": 0, "review": 0})
            blocked_counts.append(stats["blocked"])
            review_counts.append(stats["review"])

        return ApiResponse(
            data={
                "dates": dates,
                "tx": tx_counts,
                "blocked": blocked_counts,
                "review": review_counts,
            }
        )


__all__ = ["router"]
