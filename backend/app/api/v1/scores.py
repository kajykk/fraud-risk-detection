"""评分查询 + SHAP 异步路由（D05 §4.7-4.9）。

- GET /scores/{decision_id}：查询评分详情
- POST /scores/{decision_id}/shap：触发 SHAP 异步计算
- GET /scores/{decision_id}/shap/status：查询 SHAP 计算状态
- GET /scores/{decision_id}/shap/result：获取 SHAP 结果
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import NotFoundError
from app.db.session import session_scope
from app.models.transaction import Score, ShapExplanation, Transaction
from app.schemas.common import ApiResponse
from app.schemas.score import (
    ShapResult,
    ShapStatus,
    ShapStatusEnum,
    ShapTriggerRequest,
    ShapTriggerResponse,
)
from app.services.shap_provider import generate_shap_factors

router = APIRouter()


def _tx_to_dict(tx: Transaction | None) -> dict:
    """交易记录 → SHAP 输入 dict（与 transactions.py 保持一致）。"""
    return {
        "amount": tx.amount if tx else 0,
        "card_bin": tx.card_bin if tx else "",
        "tx_type": tx.tx_type if tx else "",
        "is_3ds_verified": tx.is_3ds_verified if tx else False,
        "channel": tx.channel if tx else "",
        "merchant_category": tx.merchant_category if tx else "",
    }


async def _load_score_with_tx(
    decision_id: str, tenant_id: str
) -> tuple[Score, Transaction | None]:
    """加载 score + 关联 transaction（RLS 隔离）。"""
    async with session_scope(tenant_id) as session:
        score_result = await session.execute(
            select(Score).where(Score.id == uuid.UUID(decision_id))
        )
        score = score_result.scalar_one_or_none()
        if score is None:
            raise NotFoundError(f"score not found: {decision_id}")
        tx_result = await session.execute(
            select(Transaction).where(Transaction.id == score.transaction_id)
        )
        tx = tx_result.scalar_one_or_none()
    return score, tx


@router.get("/{decision_id}", response_model=ApiResponse[dict])
async def get_score(
    decision_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[dict]:
    """查询评分详情。"""
    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(Score).where(Score.id == uuid.UUID(decision_id))
        )
        score = result.scalar_one_or_none()
        if score is None:
            raise NotFoundError(f"score not found: {decision_id}")
        return ApiResponse(data={
            "decision_id": decision_id,
            "decision": score.decision,
            "risk_score": float(score.risk_score),
            "risk_band": score.risk_band,
            "model_version": score.model_version,
            "latency_ms": score.latency_ms,
        })


@router.post("/{decision_id}/shap", response_model=ApiResponse[ShapTriggerResponse])
async def trigger_shap(
    decision_id: str,
    req: ShapTriggerRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapTriggerResponse]:
    """触发 SHAP 计算 — 同步模式（mock provider，无异步队列依赖）。"""
    score, tx = await _load_score_with_tx(decision_id, tenant_id)

    # 生成 SHAP 因子
    shap_data = generate_shap_factors(_tx_to_dict(tx), float(score.risk_score))

    # 写入 shap_explanations 表
    async with session_scope(tenant_id) as session:
        shap_record = ShapExplanation(
            tenant_id=score.tenant_id,
            score_id=score.id,
            factors=shap_data["features"],
            base_value=shap_data["base_value"],
            output_value=shap_data["prediction"],
            model_version=score.model_version,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(shap_record)

    return ApiResponse(
        data=ShapTriggerResponse(
            shap_task_id=f"shap_task_{decision_id}",
            decision_id=decision_id,
            status=ShapStatusEnum.READY,
            estimated_seconds=0,
            websocket_event="transaction.shap_ready",
        )
    )


@router.get("/{decision_id}/shap/status", response_model=ApiResponse[ShapStatus])
async def shap_status(
    decision_id: str,
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapStatus]:
    """查询 SHAP 计算状态 — 同步模式直接返回 COMPLETED。"""
    return ApiResponse(
        data=ShapStatus(
            shap_task_id=f"shap_task_{decision_id}",
            decision_id=decision_id,
            status=ShapStatusEnum.COMPLETED,
            progress=1.0,
            result_url=f"/api/v1/scores/{decision_id}/shap/result",
        )
    )


@router.get("/{decision_id}/shap/result", response_model=ApiResponse[ShapResult])
async def shap_result(
    decision_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapResult]:
    """获取 SHAP 计算结果 — 从 shap_explanations 表读取。"""
    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(ShapExplanation).where(
                ShapExplanation.score_id == uuid.UUID(decision_id)
            )
        )
        shap_record = result.scalar_one_or_none()

        if shap_record is None:
            # 尝试自动计算
            score_result = await session.execute(
                select(Score).where(Score.id == uuid.UUID(decision_id))
            )
            score = score_result.scalar_one_or_none()
            if score is None:
                raise NotFoundError(f"score not found: {decision_id}")

            tx_result = await session.execute(
                select(Transaction).where(Transaction.id == score.transaction_id)
            )
            tx = tx_result.scalar_one_or_none()

            shap_data = generate_shap_factors(_tx_to_dict(tx), float(score.risk_score))
            return ApiResponse(
                data=ShapResult(
                    shap_task_id=f"shap_task_{decision_id}",
                    decision_id=decision_id,
                    model_id=score.model_version,
                    base_value=shap_data["base_value"],
                    prediction=shap_data["prediction"],
                    features=shap_data["features"],
                    completed_at=datetime.now(UTC).isoformat(),
                )
            )

        return ApiResponse(
            data=ShapResult(
                shap_task_id=f"shap_task_{decision_id}",
                decision_id=decision_id,
                model_id=shap_record.model_version,
                base_value=float(shap_record.base_value),
                prediction=float(shap_record.output_value),
                features=shap_record.factors,
                completed_at=shap_record.computed_at.isoformat() if shap_record.computed_at else datetime.now(UTC).isoformat(),
            )
        )
