"""PIPL 数据主体权利路由（D05 §13，共 8 个接口）。

- POST /pipl/consent：授予同意（§13.1）
- POST /pipl/consent/withdraw：撤回同意（§13.2）
- GET /pipl/consent/{user_id}：查询同意记录（§13.3）
- GET /pipl/data-export：申请数据导出（§13.4）
- GET /pipl/data-export/{task_id}/status：查询导出状态（§13.5）
- POST /pipl/deletion：申请数据删除（§13.6）
- GET /pipl/deletion/{request_id}/status：查询删除状态（§13.7）
- POST /pipl/rectification：数据更正请求（§13.8）
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.pipl import (
    ConsentCreate,
    ConsentOut,
    ConsentWithdraw,
    DataExportRequest,
    DataExportStatusOut,
    DeletionRequestIn,
    DeletionStatusOut,
    RectificationRequest,
    RectificationStatusOut,
)

router = APIRouter()


@router.post("/consent", response_model=ApiResponse[ConsentOut])
async def grant_consent(
    req: ConsentCreate,
    _user: dict = Depends(require_scope("consent:write")),
) -> ApiResponse[ConsentOut]:
    """记录用户同意（PIPL §14/§15/§17）。"""
    # TODO: 校验 verification_token + 写 consent_records 表
    consent_id = f"cns_{uuid.uuid4()}"
    return ApiResponse(data=ConsentOut(
        consent_id=consent_id,
        user_id=req.user_id,
        status="GRANTED",  # type: ignore[arg-type]
        purpose=req.purpose,
        legal_basis=req.legal_basis,
        consent_type=req.consent_type,
        scope=req.scope,
        policy_version=req.policy_version,
    ))


@router.post("/consent/withdraw", response_model=ApiResponse[ConsentOut])
async def withdraw_consent(
    req: ConsentWithdraw,
    _user: dict = Depends(require_scope("consent:write")),
) -> ApiResponse[ConsentOut]:
    """撤回同意（PIPL §16）。"""
    # TODO: 更新 consent_records.consent_status=WITHDRAWN + 触发下游处理
    return ApiResponse(data=ConsentOut(
        consent_id=req.consent_id,
        user_id=req.user_id,
        status="WITHDRAWN",  # type: ignore[arg-type]
        purpose="TRANSACTION_SCORING",  # type: ignore[arg-type]
        legal_basis="CONSENT",  # type: ignore[arg-type]
        consent_type="EXPLICIT",  # type: ignore[arg-type]
        scope=[],
        policy_version="PP_v2.1",
    ))


@router.get("/consent/{user_id}", response_model=ApiResponse[PageResponse[ConsentOut]])
async def get_consent(
    user_id: str,
    purpose: str | None = None,
    status: str | None = None,
    include_history: bool = False,
    _user: dict = Depends(require_scope("consent:write")),
) -> ApiResponse[PageResponse[ConsentOut]]:
    """查询用户同意状态（PIPL §44 知情权）。"""
    # TODO: 查 consent_records 表
    return ApiResponse(data=PageResponse(items=[], total=0))


@router.get("/data-export", response_model=ApiResponse[DataExportStatusOut])
async def request_data_export(
    req: DataExportRequest,
    _user: dict = Depends(require_scope("privacy:write")),
) -> ApiResponse[DataExportStatusOut]:
    """申请数据可携带权导出（PIPL §45）。"""
    # TODO: 校验 verification_token + 投递 Celery 任务 tasks_pipl.export_data
    task_id = f"exp_task_{uuid.uuid4()}"
    return ApiResponse(data=DataExportStatusOut(
        task_id=task_id,
        user_id=req.user_id,
        status="PROCESSING",
        scope=req.scope.split(","),
        format=req.format,
    ))


@router.get("/data-export/{task_id}/status", response_model=ApiResponse[DataExportStatusOut])
async def data_export_status(
    task_id: str,
    _user: dict = Depends(require_scope("privacy:write")),
) -> ApiResponse[DataExportStatusOut]:
    """查询导出任务状态。"""
    # TODO: 查 Celery result backend
    return ApiResponse(data=DataExportStatusOut(
        task_id=task_id,
        user_id="TODO",
        status="PROCESSING",
    ))


@router.post("/deletion", response_model=ApiResponse[DeletionStatusOut])
async def request_deletion(
    req: DeletionRequestIn,
    _user: dict = Depends(require_scope("privacy:write")),
) -> ApiResponse[DeletionStatusOut]:
    """申请数据删除（被遗忘权，PIPL §47）。"""
    # TODO: 校验 verification_token + 写 deletion_requests 表 + 投递 Celery 任务
    request_id = f"del_req_{uuid.uuid4()}"
    return ApiResponse(data=DeletionStatusOut(
        request_id=request_id,
        user_id=req.user_id,
        status="PENDING",
        scope=req.scope,
    ))


@router.get("/deletion/{request_id}/status", response_model=ApiResponse[DeletionStatusOut])
async def deletion_status(
    request_id: str,
    _user: dict = Depends(require_scope("privacy:write")),
) -> ApiResponse[DeletionStatusOut]:
    """查询删除请求状态。"""
    # TODO: 查 deletion_requests 表
    return ApiResponse(data=DeletionStatusOut(
        request_id=request_id,
        user_id="TODO",
        status="PENDING",
    ))


@router.post("/rectification", response_model=ApiResponse[RectificationStatusOut])
async def request_rectification(
    req: RectificationRequest,
    _user: dict = Depends(require_scope("privacy:write")),
) -> ApiResponse[RectificationStatusOut]:
    """数据更正请求（PIPL §46）。"""
    # TODO: 校验 verification_token + 写 deletion_requests (request_type=RECTIFICATION)
    request_id = f"rect_req_{uuid.uuid4()}"
    return ApiResponse(data=RectificationStatusOut(
        request_id=request_id,
        user_id=req.user_id,
        status="PENDING_REVIEW",
        correction_count=len(req.corrections),
    ))
