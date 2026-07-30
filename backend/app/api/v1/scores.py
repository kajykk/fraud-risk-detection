"""评分查询 + SHAP 异步路由（D05 §4.7-4.9）。

- GET /scores/{decision_id}：查询评分详情
- POST /scores/{decision_id}/shap：触发 SHAP 异步计算
- GET /scores/{decision_id}/shap/status：查询 SHAP 计算状态
- GET /scores/{decision_id}/shap/result：获取 SHAP 结果
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.transaction import Score

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Score).where(Score.id == uuid.UUID(decision_id))
        )
        score = result.scalar_one_or_none()
        if score is None:
            from app.core.exceptions import NotFoundError

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
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapTriggerResponse]:
    """触发 SHAP 计算 — 同步模式（mock provider，无异步队列依赖）。"""
    from app.services.shap_provider import generate_shap_factors
    from sqlalchemy import select
    from app.db.session import get_session_factory
    from app.models.transaction import Score, Transaction

    factory = get_session_factory()
    async with factory() as session:
        # 查 score + transaction
        score_result = await session.execute(
            select(Score).where(Score.id == uuid.UUID(decision_id))
        )
        score = score_result.scalar_one_or_none()
        if score is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"score not found: {decision_id}")

        tx_result = await session.execute(
            select(Transaction).where(Transaction.id == score.transaction_id)
        )
        tx = tx_result.scalar_one_or_none()

        # 生成 mock SHAP
        tx_dict = {
            "amount": tx.amount if tx else 0,
            "card_bin": tx.card_bin if tx else "",
            "tx_type": tx.tx_type if tx else "",
            "is_3ds_verified": tx.is_3ds_verified if tx else False,
            "channel": tx.channel if tx else "",
            "merchant_category": tx.merchant_category if tx else "",
        }
        shap_data = generate_shap_factors(tx_dict, float(score.risk_score))

        # 写入 shap_explanations 表
        from app.models.transaction import ShapExplanation
        from datetime import datetime, timezone, timedelta

        shap_record = ShapExplanation(
            tenant_id=score.tenant_id,
            score_id=score.id,
            factors=shap_data["features"],
            base_value=shap_data["base_value"],
            output_value=shap_data["prediction"],
            model_version=score.model_version,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(shap_record)
        await session.commit()

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
    _user: dict = Depends(require_scope("transaction:read")),
) -> ApiResponse[ShapResult]:
    """获取 SHAP 计算结果 — 从 shap_explanations 表读取。"""
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.transaction import ShapExplanation

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ShapExplanation).where(
                ShapExplanation.score_id == uuid.UUID(decision_id)
            )
        )
        shap_record = result.scalar_one_or_none()
        if shap_record is None:
            # 尝试自动计算
            from app.services.shap_provider import generate_shap_factors
            from app.models.transaction import Score, Transaction

            score_result = await session.execute(
                select(Score).where(Score.id == uuid.UUID(decision_id))
            )
            score = score_result.scalar_one_or_none()
            if score is None:
                from app.core.exceptions import NotFoundError
                raise NotFoundError(f"score not found: {decision_id}")

            tx_result = await session.execute(
                select(Transaction).where(Transaction.id == score.transaction_id)
            )
            tx = tx_result.scalar_one_or_none()

            tx_dict = {
                "amount": tx.amount if tx else 0,
                "card_bin": tx.card_bin if tx else "",
                "tx_type": tx.tx_type if tx else "",
                "is_3ds_verified": tx.is_3ds_verified if tx else False,
                "channel": tx.channel if tx else "",
                "merchant_category": tx.merchant_category if tx else "",
            }
            shap_data = generate_shap_factors(tx_dict, float(score.risk_score))

            return ApiResponse(
                data=ShapResult(
                    shap_task_id=f"shap_task_{decision_id}",
                    decision_id=decision_id,
                    model_id=score.model_version,
                    base_value=shap_data["base_value"],
                    prediction=shap_data["prediction"],
                    features=shap_data["features"],
                    completed_at=datetime.now(timezone.utc).isoformat(),
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
                completed_at=shap_record.computed_at.isoformat() if shap_record.computed_at else datetime.now(timezone.utc).isoformat(),
            )
        )
