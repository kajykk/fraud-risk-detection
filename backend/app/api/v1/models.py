"""ML 模型路由（D05 §6）。

CRUD + canary / promote / rollback / retire / drift。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import (
    ModelHasTrafficError,
    ModelNotAvailableError,
    ModelNotDeletableError,
    ModelNotEditableError,
    ModelVersionExistsError,
    NotFoundError,
)
from app.db.session import session_scope
from app.models.model_version import DriftAlert, ModelVersion
from app.schemas.common import ApiResponse, ModelStatus, PageResponse
from app.schemas.model_version import (
    DriftOut,
    ModelCanaryRequest,
    ModelOut,
    ModelPromoteRequest,
    ModelRegisterRequest,
    ModelRetireRequest,
    ModelRollbackRequest,
    ModelUpdateRequest,
)

router = APIRouter()

# DriftAlert.severity → DriftOut.drift_status 映射
_DRIFT_STATUS_MAP = {
    "LOW": "MONITORING",
    "MEDIUM": "ALERTED",
    "HIGH": "CRITICAL",
    "CRITICAL": "CRITICAL",
}


def _model_to_out(model: ModelVersion) -> ModelOut:
    """ModelVersion ORM → ModelOut。

    注：name / entrypoint / runtime / feature_schema_path / description / trained_at
    存于 metrics JSONB；traffic_share 由 status + canary_percent 计算。
    """
    metrics = model.metrics or {}
    if model.status == ModelStatus.ACTIVE.value:
        traffic_share = 100.0
    elif model.status == ModelStatus.CANARY.value:
        traffic_share = float(model.canary_percent)
    else:
        traffic_share = 0.0
    return ModelOut(
        id=str(model.id),
        name=metrics.get("name", ""),
        version=model.version,
        type=model.model_type,
        status=ModelStatus(model.status),
        artifacts_path=model.artifacts_path,
        artifacts_sha256=model.sha256,
        entrypoint=metrics.get("entrypoint"),
        runtime=metrics.get("runtime"),
        metrics=metrics,
        feature_schema_path=metrics.get("feature_schema_path"),
        trained_at=metrics.get("trained_at"),
        registered_at=model.created_at,
        promoted_at=model.promoted_at,
        traffic_share=traffic_share,
        description=metrics.get("description"),
    )


async def _load_model(session, model_id: str, tenant_id: str) -> ModelVersion:
    """按主键加载模型，找不到抛 NotFoundError。"""
    result = await session.execute(
        select(ModelVersion).where(
            ModelVersion.id == uuid.UUID(model_id),
            ModelVersion.tenant_id == uuid.UUID(tenant_id),
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise NotFoundError(f"model not found: {model_id}")
    return model


@router.get("", response_model=ApiResponse[PageResponse[ModelOut]])
async def list_models(
    model_type: str | None = None,
    status: ModelStatus | None = None,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[PageResponse[ModelOut]]:
    """查询模型版本列表（支持 model_type / status 过滤）。"""
    async with session_scope(tenant_id) as session:
        base = select(ModelVersion).where(
            ModelVersion.tenant_id == uuid.UUID(tenant_id)
        )
        if model_type:
            base = base.where(ModelVersion.model_type == model_type)
        if status is not None:
            base = base.where(ModelVersion.status == status.value)

        count_q = (
            select(func.count())
            .select_from(ModelVersion)
            .where(ModelVersion.tenant_id == uuid.UUID(tenant_id))
        )
        if model_type:
            count_q = count_q.where(ModelVersion.model_type == model_type)
        if status is not None:
            count_q = count_q.where(ModelVersion.status == status.value)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            base.order_by(ModelVersion.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [_model_to_out(m) for m in result.scalars().all()]
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )


@router.post("", response_model=ApiResponse[ModelOut])
async def register_model(
    req: ModelRegisterRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """注册新模型（同租户同 model_type 同 version 唯一）。"""
    async with session_scope(tenant_id) as session:
        dup_result = await session.execute(
            select(ModelVersion).where(
                ModelVersion.tenant_id == uuid.UUID(tenant_id),
                ModelVersion.model_type == req.type,
                ModelVersion.version == req.version,
            )
        )
        if dup_result.scalar_one_or_none() is not None:
            raise ModelVersionExistsError(
                f"model version already exists: {req.type}/{req.version}"
            )
        metrics = {**req.metrics}
        metrics["name"] = req.name
        metrics["trained_at"] = req.trained_at.isoformat()
        if req.entrypoint is not None:
            metrics["entrypoint"] = req.entrypoint
        if req.runtime is not None:
            metrics["runtime"] = req.runtime
        if req.feature_schema_path is not None:
            metrics["feature_schema_path"] = req.feature_schema_path
        if req.description is not None:
            metrics["description"] = req.description
        model = ModelVersion(
            tenant_id=uuid.UUID(tenant_id),
            model_type=req.type,
            version=req.version,
            status=ModelStatus.REGISTERED.value,
            metrics=metrics,
            training_data_hash="",
            feature_names=[],
            artifacts_path=req.artifacts_path,
            sha256=req.artifacts_sha256,
            canary_percent=0,
            observation_hours=168,
        )
        session.add(model)
        await session.flush()
        return ApiResponse(data=_model_to_out(model))


@router.get("/{model_id}", response_model=ApiResponse[ModelOut])
async def get_model(
    model_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[ModelOut]:
    """查询模型详情。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        return ApiResponse(data=_model_to_out(model))


@router.put("/{model_id}", response_model=ApiResponse[ModelOut])
async def update_model(
    model_id: str,
    req: ModelUpdateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """更新模型元数据（仅 REGISTERED 可更新，写入 metrics）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        if model.status != ModelStatus.REGISTERED.value:
            raise ModelNotEditableError(f"model {model_id} is not editable")
        metrics = dict(model.metrics or {})
        if req.description is not None:
            metrics["description"] = req.description
        if req.feature_schema_path is not None:
            metrics["feature_schema_path"] = req.feature_schema_path
        if req.entrypoint is not None:
            metrics["entrypoint"] = req.entrypoint
        model.metrics = metrics
        return ApiResponse(data=_model_to_out(model))


@router.delete("/{model_id}", response_model=ApiResponse[ModelOut])
async def retire_model_delete(
    model_id: str,
    reason: str,
    approver_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """退役模型（DELETE 语义，仅 REGISTERED 可退役）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        if model.status != ModelStatus.REGISTERED.value:
            raise ModelNotDeletableError(f"model {model_id} is not deletable")
        model.status = ModelStatus.RETIRED.value
        model.retired_at = datetime.now(UTC)
        return ApiResponse(data=_model_to_out(model))


@router.post("/{model_id}/canary", response_model=ApiResponse[ModelOut])
async def canary_model(
    model_id: str,
    req: ModelCanaryRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """启动金丝雀发布（REGISTERED → CANARY）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        if model.status != ModelStatus.REGISTERED.value:
            raise ModelNotAvailableError(f"model {model_id} is not available for canary")
        model.status = ModelStatus.CANARY.value
        model.canary_percent = req.traffic_percentage
        model.canary_started_at = datetime.now(UTC)
        model.observation_hours = req.observation_hours
        return ApiResponse(data=_model_to_out(model))


@router.post("/{model_id}/promote", response_model=ApiResponse[ModelOut])
async def promote_model(
    model_id: str,
    req: ModelPromoteRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """金丝雀晋升为生产（CANARY → ACTIVE，同租户其他 ACTIVE 转 RETIRED）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        if model.status != ModelStatus.CANARY.value:
            raise ModelNotAvailableError(f"model {model_id} is not in CANARY status")
        model.status = ModelStatus.ACTIVE.value
        model.promoted_at = datetime.now(UTC)
        await session.execute(
            update(ModelVersion)
            .where(
                ModelVersion.tenant_id == uuid.UUID(tenant_id),
                ModelVersion.status == ModelStatus.ACTIVE.value,
                ModelVersion.id != model.id,
            )
            .values(
                status=ModelStatus.RETIRED.value,
                retired_at=datetime.now(UTC),
            )
        )
        return ApiResponse(data=_model_to_out(model))


@router.post("/{model_id}/rollback", response_model=ApiResponse[ModelOut])
async def rollback_model(
    model_id: str,
    req: ModelRollbackRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """紧急回滚：当前转 RETIRED，目标模型（非 ACTIVE）转 ACTIVE。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        target = await _load_model(session, req.target_model_id, tenant_id)
        if target.status == ModelStatus.ACTIVE.value or model.id == target.id:
            raise ModelNotAvailableError(
                f"target model {req.target_model_id} is not available"
            )
        model.status = ModelStatus.RETIRED.value
        model.retired_at = datetime.now(UTC)
        target.status = ModelStatus.ACTIVE.value
        target.promoted_at = datetime.now(UTC)
        return ApiResponse(data=_model_to_out(target))


@router.post("/{model_id}/retire", response_model=ApiResponse[ModelOut])
async def retire_model(
    model_id: str,
    req: ModelRetireRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """显式退役（非 ACTIVE 可退，ACTIVE 需先切流量）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        if model.status == ModelStatus.ACTIVE.value:
            raise ModelHasTrafficError(f"model {model_id} still has traffic")
        model.status = ModelStatus.RETIRED.value
        model.retired_at = datetime.now(UTC)
        return ApiResponse(data=_model_to_out(model))


@router.get("/{model_id}/drift", response_model=ApiResponse[DriftOut])
async def model_drift(
    model_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[DriftOut]:
    """查询模型漂移指标（drift_alerts 最近记录，无记录则 HEALTHY）。"""
    async with session_scope(tenant_id) as session:
        model = await _load_model(session, model_id, tenant_id)
        result = await session.execute(
            select(DriftAlert)
            .where(
                DriftAlert.tenant_id == uuid.UUID(tenant_id),
                DriftAlert.model_version == model.version,
            )
            .order_by(DriftAlert.detected_at.desc())
            .limit(1)
        )
        alert = result.scalar_one_or_none()
        if alert is None:
            return ApiResponse(data=DriftOut(model_id=model_id, drift_status="HEALTHY"))
        metric_value = float(alert.metric_value)
        return ApiResponse(
            data=DriftOut(
                model_id=model_id,
                drift_status=_DRIFT_STATUS_MAP.get(alert.severity, "HEALTHY"),
                psi_1d=metric_value if alert.metric_type == "PSI" else None,
                psi_7d=None,
                kl_divergence=metric_value if alert.metric_type == "KL" else None,
                last_checked_at=alert.detected_at,
                feature_drifts=[
                    {
                        "metric_type": alert.metric_type,
                        "metric_value": metric_value,
                        "threshold": float(alert.threshold),
                        "severity": alert.severity,
                        "detected_at": alert.detected_at.isoformat()
                        if alert.detected_at
                        else None,
                    }
                ],
            )
        )
