"""ML 模型路由（D05 §6）。

CRUD + canary / promote / rollback / retire / drift。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse, PageResponse
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


@router.get("", response_model=ApiResponse[PageResponse[ModelOut]])
async def list_models(
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[PageResponse[ModelOut]]:
    """查询模型版本列表。"""
    # TODO: 查 model_versions 表
    return ApiResponse(data=PageResponse(items=[], total=0))


@router.post("", response_model=ApiResponse[ModelOut])
async def register_model(
    req: ModelRegisterRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """注册新模型。"""
    # TODO: 校验 artifacts_sha256 + 写 model_versions 表
    return ApiResponse(data=ModelOut(id="TODO", name=req.name, version=req.version, type=req.type, status="REGISTERED", artifacts_path=req.artifacts_path, artifacts_sha256=req.artifacts_sha256, metrics=req.metrics))  # type: ignore[arg-type]


@router.get("/{model_id}", response_model=ApiResponse[ModelOut])
async def get_model(
    model_id: str,
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[ModelOut]:
    """查询模型详情。"""
    # TODO: 查 model_versions 表
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"model not found: {model_id}")


@router.put("/{model_id}", response_model=ApiResponse[ModelOut])
async def update_model(
    model_id: str,
    req: ModelUpdateRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """更新模型元数据（仅 REGISTERED 状态可更新）。"""
    # TODO: 校验 status=REGISTERED + 更新
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="REGISTERED", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.delete("/{model_id}", response_model=ApiResponse[ModelOut])
async def retire_model_delete(
    model_id: str,
    reason: str,
    approver_id: str,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """退役模型（DELETE 语义）。"""
    # TODO: 校验无流量 + 转 RETIRED
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="RETIRED", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.post("/{model_id}/canary", response_model=ApiResponse[ModelOut])
async def canary_model(
    model_id: str,
    req: ModelCanaryRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """启动金丝雀发布（REGISTERED → CANARY）。"""
    # TODO: 状态机校验 + 更新 canary_percent
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="CANARY", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.post("/{model_id}/promote", response_model=ApiResponse[ModelOut])
async def promote_model(
    model_id: str,
    req: ModelPromoteRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """金丝雀晋升为生产（CANARY → ACTIVE）。"""
    # TODO: 状态机校验 + 原 ACTIVE 转 RETIRED
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="ACTIVE", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.post("/{model_id}/rollback", response_model=ApiResponse[ModelOut])
async def rollback_model(
    model_id: str,
    req: ModelRollbackRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """紧急回滚到上一稳定版本。"""
    # TODO: 触发 Kill Switch + 切流量
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="ACTIVE", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.post("/{model_id}/retire", response_model=ApiResponse[ModelOut])
async def retire_model(
    model_id: str,
    req: ModelRetireRequest,
    _user: dict = Depends(require_scope("model:write")),
) -> ApiResponse[ModelOut]:
    """显式退役模型。"""
    # TODO: 状态机校验 + 转 RETIRED
    return ApiResponse(data=ModelOut(id=model_id, name="TODO", version="v1", type="XGB", status="RETIRED", artifacts_path="", artifacts_sha256="", metrics={}))  # type: ignore[arg-type]


@router.get("/{model_id}/drift", response_model=ApiResponse[DriftOut])
async def model_drift(
    model_id: str,
    _user: dict = Depends(require_scope("model:read")),
) -> ApiResponse[DriftOut]:
    """查询模型漂移指标。"""
    # TODO: 查 drift_alerts 表
    return ApiResponse(data=DriftOut(model_id=model_id, drift_status="HEALTHY"))
