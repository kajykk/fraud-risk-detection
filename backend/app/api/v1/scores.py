"""评分查询 + SHAP 异步路由（D05 §4.7-4.9）。

- GET /scores/{decision_id}：查询评分详情
- POST /scores/{decision_id}/shap：触发 SHAP 异步计算
- GET /scores/{decision_id}/shap/status：查询 SHAP 计算状态
- GET /scores/{decision_id}/shap/result：获取 SHAP 结果
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse
from app.schemas.score import (
    ShapResult,
    ShapStatus,
    ShapStatusEnum,
    ShapTriggerRequest,
    ShapTriggerResponse,
)

router = APIRouter()


@router.get("/{decision_id}", response_model=ApiResponse[dict])
async def get_score(
    decision_id: str,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[dict]:
    """查询评分详情。"""
    # TODO: 查 scores 表
    return ApiResponse(data={"decision_id": decision_id, "status": "TODO"})


@router.post("/{decision_id}/shap", response_model=ApiResponse[ShapTriggerResponse])
async def trigger_shap(
    decision_id: str,
    req: ShapTriggerRequest,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapTriggerResponse]:
    """触发 SHAP 异步计算（D03 ADR-007，不进主路径）。"""
    shap_task_id = f"shap_task_{uuid.uuid4()}"
    # TODO: 投递 Celery 任务 tasks_shap.compute_shap
    return ApiResponse(
        data=ShapTriggerResponse(
            shap_task_id=shap_task_id,
            decision_id=decision_id,
            status=ShapStatusEnum.RUNNING,
            estimated_seconds=5,
            websocket_event="transaction.shap_ready",
        )
    )


@router.get("/{decision_id}/shap/status", response_model=ApiResponse[ShapStatus])
async def shap_status(
    decision_id: str,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapStatus]:
    """查询 SHAP 计算状态。"""
    # TODO: 查 Celery result backend
    return ApiResponse(
        data=ShapStatus(
            shap_task_id=f"shap_task_{decision_id}",
            decision_id=decision_id,
            status=ShapStatusEnum.RUNNING,
            progress=0.5,
            result_url=f"/api/v1/scores/{decision_id}/shap/result",
        )
    )


@router.get("/{decision_id}/shap/result", response_model=ApiResponse[ShapResult])
async def shap_result(
    decision_id: str,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapResult]:
    """获取 SHAP 计算结果。"""
    # TODO: 查 shap_explanations 表
    from app.core.exceptions import ShapNotReadyError

    raise ShapNotReadyError(f"shap not ready for decision_id={decision_id}")
