"""交易评分路由（D05 §4）。

- POST /transactions/score：同步评分（核心接口，P99 < 200ms）
- POST /transactions/score/async：异步评分（深度分析）
- GET /transactions/score/tasks/{task_id}：查询异步任务
- POST /transactions/score/batch：批量评分
- POST /transactions/feedback：反馈真实欺诈标签
- GET /transactions/{external_tx_id}：查询交易评分详情
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import NotFoundError
from app.schemas.common import ApiResponse
from app.schemas.transaction import (
    AsyncScoreResponse,
    BatchScoreRequest,
    BatchScoreResponse,
    BatchScoreResultItem,
    FeedbackRequest,
    TransactionDetail,
    TransactionScoreRequest,
    TransactionScoreResponse,
)
from app.services.scoring import scoring_orchestrator

router = APIRouter()


@router.post("/score", response_model=ApiResponse[TransactionScoreResponse])
async def score_transaction(
    req: TransactionScoreRequest,
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[TransactionScoreResponse]:
    """实时交易评分（核心接口，P99 < 200ms）。"""
    tx_dict = req.model_dump(mode="json")
    result = await scoring_orchestrator.score_sync(tx_dict, tenant_id)
    return ApiResponse(
        data=TransactionScoreResponse(
            decision=result.decision,
            risk_score=result.risk_score,
            risk_band=result.risk_band,
            model_version=result.model_version,
            rule_hits=result.rule_hits,
            explainability=result.explainability,
            latency_ms=result.latency_ms,
            case_id=result.case_id,
            decision_id=result.decision_id,
        )
    )


@router.post("/score/async", response_model=ApiResponse[AsyncScoreResponse])
async def score_async(
    req: TransactionScoreRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[AsyncScoreResponse]:
    """异步评分（深度分析，含 GNN 团伙检测）。"""
    from app.workers.celery_app import celery_app
    from app.workers.tasks_scoring import score_async as score_async_task

    tx_dict = req.model_dump(mode="json")
    if celery_app.conf.task_always_eager:
        # 内联模式（测试/单机）：本地执行，不投递 broker
        result = score_async_task.apply(args=[tenant_id, tx_dict])
    else:
        result = celery_app.send_task(
            "scoring.score_async",
            args=[tenant_id, tx_dict],
            queue="scoring",
        )
    return ApiResponse(
        data=AsyncScoreResponse(
            task_id=result.id,
            status="RUNNING",
            estimated_seconds=30,
            callback_event="transaction.analysis_completed",
        )
    )


@router.get("/score/tasks/{task_id}", response_model=ApiResponse[dict])
async def get_score_task(
    task_id: str,
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[dict]:
    """查询异步评分任务状态。"""
    from app.workers.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    if result.state == "PENDING":
        status = "PENDING"
    elif result.state == "STARTED":
        status = "RUNNING"
    elif result.state in ("SUCCESS",):
        status = "COMPLETED"
    elif result.state == "FAILURE":
        status = "FAILED"
    else:
        status = result.state

    payload: dict = {"task_id": task_id, "status": status}
    if result.successful() and isinstance(result.result, dict):
        payload.update(result.result)
    elif result.failed() and isinstance(result.result, BaseException):
        payload["error"] = str(result.result)
    return ApiResponse(data=payload)


@router.post("/score/batch", response_model=ApiResponse[BatchScoreResponse])
async def score_batch(
    req: BatchScoreRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[BatchScoreResponse]:
    """批量评分（最多 100 条/批，并发执行）。"""
    from app.schemas.common import Decision, RiskBand

    async def _score_one(tx: dict) -> BatchScoreResultItem:
        try:
            result = await scoring_orchestrator.score_sync(tx, tenant_id)
            return BatchScoreResultItem(
                external_tx_id=tx["external_tx_id"],
                decision=result.decision,
                risk_score=result.risk_score,
                risk_band=result.risk_band,
            )
        except Exception as exc:
            return BatchScoreResultItem(
                external_tx_id=tx["external_tx_id"],
                decision=Decision.DENY,
                risk_score=0.0,
                risk_band=RiskBand.CRITICAL,
                error=str(exc),
            )

    tx_list = [t.model_dump(mode="json") for t in req.transactions]
    results = await asyncio.gather(*[_score_one(tx) for tx in tx_list])
    success_count = sum(1 for r in results if r.error is None)
    return ApiResponse(
        data=BatchScoreResponse(
            results=results,
            success_count=success_count,
            failure_count=len(results) - success_count,
        )
    )


@router.post("/feedback", response_model=ApiResponse[dict])
async def feedback(
    req: FeedbackRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[dict]:
    """反馈真实欺诈标签（用于模型再训练）。"""
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models.transaction import Transaction

    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.external_tx_id == req.external_tx_id,
            )
        )
        tx = result.scalar_one_or_none()
        if tx is None:
            raise NotFoundError(f"transaction not found: {req.external_tx_id}")
        features = dict(tx.risk_features or {})
        features["is_fraud"] = req.label
        features["label_source"] = req.label_source
        features["labeled_at"] = req.labeled_at.isoformat()
        if req.evidence:
            features["label_evidence"] = req.evidence
        tx.risk_features = features
    return ApiResponse(data={"status": "accepted", "external_tx_id": req.external_tx_id})


@router.get("", response_model=ApiResponse[dict])
async def list_transactions(
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:read")),
    external_tx_id: str | None = None,
    decision: str | None = None,
    risk_band: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    """交易列表查询（D05 §5.3）。"""
    from sqlalchemy import desc, func, select

    from app.db.session import session_scope
    from app.models.transaction import Score, Transaction

    async with session_scope(tenant_id) as session:
        # 构建基础查询：transactions JOIN scores
        base = (
            select(Transaction, Score)
            .outerjoin(Score, Score.transaction_id == Transaction.id)
            .where(Transaction.tenant_id == tenant_id)
        )

        # 过滤条件
        if external_tx_id:
            base = base.where(Transaction.external_tx_id.ilike(f"%{external_tx_id}%"))
        if decision:
            base = base.where(Score.decision == decision)
        if risk_band:
            base = base.where(Score.risk_band == risk_band)

        # 总数
        count_q = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.tenant_id == tenant_id)
        )
        if external_tx_id:
            count_q = count_q.where(Transaction.external_tx_id.ilike(f"%{external_tx_id}%"))

        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        # 分页
        base = base.order_by(desc(Transaction.created_at)).offset(
            (page - 1) * page_size
        ).limit(page_size)
        result = await session.execute(base)

        items = []
        for tx, sc in result:
            item = {
                "external_tx_id": tx.external_tx_id,
                "tx_type": tx.tx_type,
                "channel": tx.channel,
                "is_3ds_verified": tx.is_3ds_verified,
                "user_created_at": None,
                "acquirer_id": None,
                "shipping_country": None,
                "billing_country": None,
                "case_id": None,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
                "metadata": tx.metadata_,
                "decision": sc.decision if sc else None,
                "risk_score": float(sc.risk_score) if sc else None,
                "risk_band": sc.risk_band if sc else None,
                "model_version": sc.model_version if sc else None,
                "rule_hits": sc.rule_hits if sc else [],
                "explainability": {
                    "model_contribution": 0.65,
                    "rule_contribution": 0.35,
                    "shap_status": "PENDING",
                },
                "decision_id": str(sc.id) if sc else None,
            }
            items.append(item)

        return ApiResponse(
            data={
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
            }
        )


@router.get("/{external_tx_id}", response_model=ApiResponse[TransactionDetail])
async def get_transaction(
    external_tx_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[TransactionDetail]:
    """查询交易评分详情。"""
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models.transaction import Score, Transaction

    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(Transaction, Score)
            .outerjoin(Score, Score.transaction_id == Transaction.id)
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.external_tx_id == external_tx_id,
            )
        )
        row = result.first()
        if row is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"transaction not found: {external_tx_id}")

        tx, sc = row
        return ApiResponse(
            data=TransactionDetail(
                external_tx_id=tx.external_tx_id,
                decision=sc.decision if sc else "ALLOW",
                risk_score=float(sc.risk_score) if sc else 0.0,
                risk_band=sc.risk_band if sc else "LOW",
                model_version=sc.model_version if sc else "unknown",
                rule_hits=sc.rule_hits if sc else [],
                explainability={
                    "model_contribution": 0.65,
                    "rule_contribution": 0.35,
                    "shap_status": "PENDING",
                },
                tx_type=tx.tx_type,
                channel=tx.channel,
                is_3ds_verified=tx.is_3ds_verified,
                user_created_at=None,
                acquirer_id=None,
                shipping_country=None,
                billing_country=None,
                case_id=None,
                decision_id=str(sc.id) if sc else "",
                created_at=tx.created_at.isoformat() if tx.created_at else "",
            )
        )
