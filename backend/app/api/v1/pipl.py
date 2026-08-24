"""PIPL 数据主体权利路由（D05 §13，共 8 个接口）。

- POST /pipl/consent：授予同意（§13.1）
- POST /pipl/consent/withdraw：撤回同意（§13.2）
- GET /pipl/consent/{user_id}：查询同意记录（§13.3）
- GET /pipl/data-export：申请数据导出（§13.4）
- GET /pipl/data-export/{task_id}/status：查询导出状态（§13.5）
- POST /pipl/deletion：申请数据删除（§13.6）
- GET /pipl/deletion/{request_id}/status：查询删除状态（§13.7）
- POST /pipl/rectification：数据更正请求（§13.8）

Scope 约定（与 auth._default_scopes 角色矩阵统一为 pipl:* 命名）：
- 读端点（查询状态）要求 pipl:read
- 写端点（授予/撤回同意、导出/删除/更正申请）要求 pipl:write
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import (
    ConsentAlreadyGrantedError,
    ConsentAlreadyWithdrawnError,
    ConsentNotFoundError,
    NotFoundError,
    SubjectNotVerifiedError,
)
from app.db.session import session_scope
from app.models.pipl import ConsentRecord, DeletionRequest
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.pipl import (
    ConsentCreate,
    ConsentOut,
    ConsentStatus,
    ConsentWithdraw,
    DataExportRequest,
    DataExportStatusOut,
    DeletionRequestIn,
    DeletionStatusOut,
    RectificationRequest,
    RectificationStatusOut,
)

router = APIRouter()


def _check_verification_token(token: str) -> None:
    """校验身份核验 token（骨架阶段仅非空校验）。

    TODO: 对接身份核验服务（短信/邮箱 OTP 等）做完整校验后再落库。
    """
    if not token:
        raise SubjectNotVerifiedError("verification token required")


def _consent_to_out(record: ConsentRecord) -> ConsentOut:
    """ConsentRecord ORM → ConsentOut（scope/policy_version 模型未存，返回默认值）。"""
    return ConsentOut(
        consent_id=str(record.id),
        user_id=record.user_id,
        status=record.consent_status,
        purpose=record.purpose,
        legal_basis=record.legal_basis,
        consent_type=record.consent_type,
        scope=[],
        granted_at=record.granted_at,
        expires_at=None,
        withdrawn_at=record.withdrawn_at,
        policy_version="",
        evidence_ref=None,
    )


def _deletion_to_out(request: DeletionRequest) -> DeletionStatusOut:
    """DeletionRequest ORM → DeletionStatusOut（scope 模型未存，返回空列表）。"""
    return DeletionStatusOut(
        request_id=str(request.id),
        user_id=request.user_id,
        status=request.status,
        scope=[],
        created_at=request.requested_at,
        completed_at=request.completed_at,
    )


@router.post("/consent", response_model=ApiResponse[ConsentOut])
async def grant_consent(
    req: ConsentCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:write")),
) -> ApiResponse[ConsentOut]:
    """记录用户同意（PIPL §14/§15/§17）。"""
    _check_verification_token(req.verification_token)
    async with session_scope(tenant_id) as session:
        existing = await session.execute(
            select(ConsentRecord).where(
                ConsentRecord.tenant_id == uuid.UUID(tenant_id),
                ConsentRecord.user_id == req.user_id,
                ConsentRecord.purpose == req.purpose.value,
                ConsentRecord.consent_status == ConsentStatus.GRANTED.value,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConsentAlreadyGrantedError(
                f"consent already granted: user={req.user_id} purpose={req.purpose.value}"
            )
        record = ConsentRecord(
            tenant_id=uuid.UUID(tenant_id),
            user_id=req.user_id,
            consent_type=req.consent_type.value,
            consent_status=ConsentStatus.GRANTED.value,
            granted_at=datetime.now(UTC),
            purpose=req.purpose.value,
            legal_basis=req.legal_basis.value,
        )
        session.add(record)
        await session.flush()
        return ApiResponse(data=_consent_to_out(record))


@router.post("/consent/withdraw", response_model=ApiResponse[ConsentOut])
async def withdraw_consent(
    req: ConsentWithdraw,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:write")),
) -> ApiResponse[ConsentOut]:
    """撤回同意（PIPL §16）。"""
    _check_verification_token(req.verification_token)
    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(ConsentRecord).where(
                ConsentRecord.id == uuid.UUID(req.consent_id),
                ConsentRecord.tenant_id == uuid.UUID(tenant_id),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise ConsentNotFoundError(f"consent not found: {req.consent_id}")
        if record.consent_status == ConsentStatus.WITHDRAWN.value:
            raise ConsentAlreadyWithdrawnError(f"consent already withdrawn: {req.consent_id}")
        record.consent_status = ConsentStatus.WITHDRAWN.value
        record.withdrawn_at = datetime.now(UTC)
        return ApiResponse(data=_consent_to_out(record))


@router.get("/consent/{user_id}", response_model=ApiResponse[PageResponse[ConsentOut]])
async def get_consent(
    user_id: str,
    purpose: str | None = None,
    status: str | None = None,
    include_history: bool = False,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:read")),
) -> ApiResponse[PageResponse[ConsentOut]]:
    """查询用户同意状态（PIPL §44 知情权）。"""
    async with session_scope(tenant_id) as session:
        base = select(ConsentRecord).where(
            ConsentRecord.tenant_id == uuid.UUID(tenant_id),
            ConsentRecord.user_id == user_id,
        )
        if purpose:
            base = base.where(ConsentRecord.purpose == purpose)
        if status:
            base = base.where(ConsentRecord.consent_status == status)

        count_q = select(func.count()).select_from(ConsentRecord).where(
            ConsentRecord.tenant_id == uuid.UUID(tenant_id),
            ConsentRecord.user_id == user_id,
        )
        if purpose:
            count_q = count_q.where(ConsentRecord.purpose == purpose)
        if status:
            count_q = count_q.where(ConsentRecord.consent_status == status)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            base.order_by(ConsentRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [_consent_to_out(r) for r in result.scalars().all()]
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )


@router.get("/data-export", response_model=ApiResponse[DataExportStatusOut])
async def request_data_export(
    req: DataExportRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:write")),
) -> ApiResponse[DataExportStatusOut]:
    """申请数据可携带权导出（PIPL §45）。"""
    # TODO: 校验 verification_token + 投递 Celery 任务 tasks_pipl.export_data
    task_id = f"exp_task_{uuid.uuid4()}"
    return ApiResponse(
        data=DataExportStatusOut(
            task_id=task_id,
            user_id=req.user_id,
            status="PROCESSING",
            scope=req.scope.split(","),
            format=req.format,
        )
    )


@router.get("/data-export/{task_id}/status", response_model=ApiResponse[DataExportStatusOut])
async def data_export_status(
    task_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:read")),
) -> ApiResponse[DataExportStatusOut]:
    """查询导出任务状态（无任务存储，预留返回 PROCESSING）。"""
    # TODO: 查 Celery result backend
    return ApiResponse(
        data=DataExportStatusOut(
            task_id=task_id,
            user_id="TODO",
            status="PROCESSING",
        )
    )


@router.post("/deletion", response_model=ApiResponse[DeletionStatusOut])
async def request_deletion(
    req: DeletionRequestIn,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:write")),
) -> ApiResponse[DeletionStatusOut]:
    """申请数据删除（被遗忘权，PIPL §47）。"""
    # TODO: 完整校验 verification_token（骨架阶段仅非空校验）+ 投递 Celery 任务
    _check_verification_token(req.verification_token)
    async with session_scope(tenant_id) as session:
        request = DeletionRequest(
            tenant_id=uuid.UUID(tenant_id),
            user_id=req.user_id,
            request_type="ACCOUNT_DELETION",
            status="PENDING",
            reason=req.reason,
            verification_method="PHONE_OTP",
        )
        session.add(request)
        await session.flush()
        return ApiResponse(data=_deletion_to_out(request))


@router.get("/deletion/{request_id}/status", response_model=ApiResponse[DeletionStatusOut])
async def deletion_status(
    request_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:read")),
) -> ApiResponse[DeletionStatusOut]:
    """查询删除请求状态。"""
    async with session_scope(tenant_id) as session:
        result = await session.execute(
            select(DeletionRequest).where(
                DeletionRequest.id == uuid.UUID(request_id),
                DeletionRequest.tenant_id == uuid.UUID(tenant_id),
            )
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise NotFoundError(f"deletion request not found: {request_id}")
        return ApiResponse(data=_deletion_to_out(request))


@router.post("/rectification", response_model=ApiResponse[RectificationStatusOut])
async def request_rectification(
    req: RectificationRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("pipl:write")),
) -> ApiResponse[RectificationStatusOut]:
    """数据更正请求（PIPL §46）。"""
    # TODO: 完整校验 verification_token（骨架阶段仅非空校验）
    _check_verification_token(req.verification_token)
    async with session_scope(tenant_id) as session:
        request = DeletionRequest(
            tenant_id=uuid.UUID(tenant_id),
            user_id=req.user_id,
            request_type="RECTIFICATION",
            status="PENDING_REVIEW",
            reason=req.reason,
            verification_method="PHONE_OTP",
        )
        session.add(request)
        await session.flush()
        return ApiResponse(
            data=RectificationStatusOut(
                request_id=str(request.id),
                user_id=req.user_id,
                status="PENDING_REVIEW",
                correction_count=len(req.corrections),
            )
        )
