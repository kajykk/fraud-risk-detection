"""交易评分路由（D05 §4）。

- POST /transactions/score：同步评分（核心接口，P99 < 200ms）
- POST /transactions/score/async：异步评分（深度分析）
- GET /transactions/score/tasks/{task_id}：查询异步任务
- POST /transactions/score/batch：批量评分
- POST /transactions/feedback：反馈真实欺诈标签
- GET /transactions/{external_tx_id}：查询交易评分详情
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_tenant_id, require_scope
from app.schemas.common import ApiResponse
from app.schemas.transaction import (
    AsyncScoreResponse,
    BatchScoreRequest,
    BatchScoreResponse,
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
    # TODO: 投递 Celery 任务 tasks_scoring.score_async_task
    import uuid

    task_id = f"score_task_{uuid.uuid4()}"
    return ApiResponse(
        data=AsyncScoreResponse(
            task_id=task_id,
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
    # TODO: 查 Celery result backend
    return ApiResponse(data={"task_id": task_id, "status": "RUNNING"})


@router.post("/score/batch", response_model=ApiResponse[BatchScoreResponse])
async def score_batch(
    req: BatchScoreRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[BatchScoreResponse]:
    """批量评分（最多 100 条/批）。"""
    # TODO: 并发调用 score_sync
    return ApiResponse(data=BatchScoreResponse(results=[], success_count=0, failure_count=0))


@router.post("/feedback", response_model=ApiResponse[dict])
async def feedback(
    req: FeedbackRequest,
    _user: dict = Depends(require_scope("transaction:score")),
) -> ApiResponse[dict]:
    """反馈真实欺诈标签（用于模型再训练）。"""
    # TODO: 写入 transactions.is_fraud 标签
    return ApiResponse(data={"status": "accepted", "external_tx_id": req.external_tx_id})


@router.get("/{external_tx_id}", response_model=ApiResponse[TransactionDetail])
async def get_transaction(
    external_tx_id: str,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[TransactionDetail]:
    """查询交易评分详情。"""
    # TODO: 查 DB
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"transaction not found: {external_tx_id}")
