"""案件管理路由（D05 §8）。"""

from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import session_scope
from app.models.case import Case, CaseEvent
from app.models.transaction import Score, Transaction
from app.schemas.case import (
    CaseCloseRequest,
    CaseCreate,
    CaseEventOut,
    CaseLevel,
    CaseOut,
    CaseUpdate,
    CommentCreate,
)
from app.schemas.common import ApiResponse, CaseStatus, PageResponse

router = APIRouter()


def _to_uuid(value: str) -> uuid.UUID:
    """将字符串转换为 UUID；非 UUID 时用 uuid5 生成确定性 UUID（如 user sub）。"""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(value))


def _parse_uuid(value: str) -> uuid.UUID:
    """解析 UUID 路径参数，非法格式按 NotFoundError 处理。"""
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise NotFoundError(f"case not found: {value}") from exc


def _gen_case_no(now: datetime) -> str:
    """生成案件编号：CS{yyyyMMdd}{6 位随机数字}。"""
    return f"CS{now.strftime('%Y%m%d')}{''.join(random.choices(string.digits, k=6))}"


def _case_to_out(case: Case) -> CaseOut:
    """Case ORM → CaseOut。"""
    return CaseOut(
        id=str(case.id),
        case_no=case.case_no,
        type=case.type,
        level=case.level,
        status=case.status,
        transaction_id=str(case.transaction_id) if case.transaction_id else None,
        score_id=str(case.score_id) if case.score_id else None,
        assigned_to=str(case.assigned_to) if case.assigned_to else None,
        amount=case.amount,
        description=case.description,
        graph_summary=case.graph_summary,
        created_at=case.created_at,
        confirmed_at=case.confirmed_at,
        closed_at=case.closed_at,
    )


def _event_to_out(event: CaseEvent) -> CaseEventOut:
    """CaseEvent ORM → CaseEventOut。"""
    return CaseEventOut(
        id=str(event.id),
        case_id=str(event.case_id),
        action=event.action,
        from_status=event.from_status,
        to_status=event.to_status,
        operator_id=str(event.operator_id),
        comment=event.comment,
        created_at=event.created_at,
    )


async def _load_case(session, case_id: str, tenant_id: str) -> Case:
    """按主键加载案件，找不到抛 NotFoundError。"""
    result = await session.execute(
        select(Case).where(Case.id == _parse_uuid(case_id), Case.tenant_id == uuid.UUID(tenant_id))
    )
    case = result.scalar_one_or_none()
    if case is None:
        raise NotFoundError(f"case not found: {case_id}")
    return case


@router.get("", response_model=ApiResponse[PageResponse[CaseOut]])
async def list_cases(
    status: CaseStatus | None = None,
    level: CaseLevel | None = None,
    case_type: str | None = Query(default=None, alias="type"),
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[PageResponse[CaseOut]]:
    """分页查询案件（支持 status / level / type 过滤，按 created_at 倒序）。"""
    async with session_scope(tenant_id) as session:
        base = select(Case).where(Case.tenant_id == uuid.UUID(tenant_id))
        if status is not None:
            base = base.where(Case.status == status.value)
        if level is not None:
            base = base.where(Case.level == level.value)
        if case_type:
            base = base.where(Case.type == case_type)

        count_q = (
            select(func.count()).select_from(Case).where(Case.tenant_id == uuid.UUID(tenant_id))
        )
        if status is not None:
            count_q = count_q.where(Case.status == status.value)
        if level is not None:
            count_q = count_q.where(Case.level == level.value)
        if case_type:
            count_q = count_q.where(Case.type == case_type)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            base.order_by(Case.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [_case_to_out(c) for c in result.scalars().all()]
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )


@router.post("", response_model=ApiResponse[CaseOut])
async def create_case(
    req: CaseCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """手动创建案件（关联交易，写首条 CREATED 事件）。"""
    now = datetime.now(UTC)
    async with session_scope(tenant_id) as session:
        tx_result = await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == uuid.UUID(tenant_id),
                Transaction.external_tx_id == req.external_tx_id,
            )
        )
        tx = tx_result.scalar_one_or_none()
        if tx is None:
            raise NotFoundError(f"transaction not found: {req.external_tx_id}")

        score_result = await session.execute(
            select(Score)
            .where(Score.transaction_id == tx.id)
            .order_by(Score.created_at.desc())
            .limit(1)
        )
        score = score_result.scalar_one_or_none()

        case = Case(
            tenant_id=uuid.UUID(tenant_id),
            transaction_id=tx.id,
            score_id=score.id if score else None,
            case_no=_gen_case_no(now),
            type="FRAUD",
            level=req.priority.value,
            status=CaseStatus.OPEN.value,
            assigned_to=_to_uuid(req.assignee_id) if req.assignee_id else None,
            amount=tx.amount,
            description=req.description,
        )
        session.add(case)
        await session.flush()

        event = CaseEvent(
            tenant_id=uuid.UUID(tenant_id),
            case_id=case.id,
            action="CREATED",
            from_status=None,
            to_status=CaseStatus.OPEN.value,
            operator_id=_to_uuid(_user["sub"]),
            comment=req.description,
        )
        session.add(event)
        return ApiResponse(data=_case_to_out(case))


@router.get("/{case_id}", response_model=ApiResponse[CaseOut])
async def get_case(
    case_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[CaseOut]:
    """查询案件详情。"""
    async with session_scope(tenant_id) as session:
        case = await _load_case(session, case_id, tenant_id)
        return ApiResponse(data=_case_to_out(case))


@router.patch("/{case_id}", response_model=ApiResponse[CaseOut])
async def update_case(
    case_id: str,
    req: CaseUpdate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """更新案件状态/处理人/备注（写对应事件）。"""
    async with session_scope(tenant_id) as session:
        case = await _load_case(session, case_id, tenant_id)

        if req.status is not None:
            from_status = case.status
            case.status = req.status.value
            session.add(
                CaseEvent(
                    tenant_id=uuid.UUID(tenant_id),
                    case_id=case.id,
                    action="STATUS_CHANGED",
                    from_status=from_status,
                    to_status=req.status.value,
                    operator_id=_to_uuid(_user["sub"]),
                    comment=req.comment,
                )
            )
        if req.assignee_id is not None:
            case.assigned_to = _to_uuid(req.assignee_id)
            session.add(
                CaseEvent(
                    tenant_id=uuid.UUID(tenant_id),
                    case_id=case.id,
                    action="ASSIGNED",
                    operator_id=_to_uuid(_user["sub"]),
                    comment=req.comment,
                )
            )
        return ApiResponse(data=_case_to_out(case))


@router.post("/{case_id}/comments", response_model=ApiResponse[CaseEventOut])
async def add_comment(
    case_id: str,
    req: CommentCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseEventOut]:
    """添加案件备注。"""
    async with session_scope(tenant_id) as session:
        await _load_case(session, case_id, tenant_id)
        event = CaseEvent(
            tenant_id=uuid.UUID(tenant_id),
            case_id=_parse_uuid(case_id),
            action="COMMENT",
            operator_id=_to_uuid(_user["sub"]),
            comment=req.comment,
        )
        session.add(event)
        await session.flush()
        return ApiResponse(data=_event_to_out(event))


@router.post("/{case_id}/close", response_model=ApiResponse[CaseOut])
async def close_case(
    case_id: str,
    req: CaseCloseRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """关闭案件（状态机校验：非 CLOSED）。"""
    async with session_scope(tenant_id) as session:
        case = await _load_case(session, case_id, tenant_id)
        if case.status == CaseStatus.CLOSED.value:
            raise ConflictError(f"case already closed: {case_id}")
        from_status = case.status
        case.status = CaseStatus.CLOSED.value
        case.closed_at = datetime.now(UTC)
        session.add(
            CaseEvent(
                tenant_id=uuid.UUID(tenant_id),
                case_id=case.id,
                action="CLOSED",
                from_status=from_status,
                to_status=CaseStatus.CLOSED.value,
                operator_id=_to_uuid(_user["sub"]),
                comment=req.comment,
            )
        )
        return ApiResponse(data=_case_to_out(case))


@router.get("/{case_id}/timeline", response_model=ApiResponse[list[CaseEventOut]])
async def case_timeline(
    case_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[list[CaseEventOut]]:
    """案件操作时间线（created_at 升序）。"""
    async with session_scope(tenant_id) as session:
        await _load_case(session, case_id, tenant_id)
        result = await session.execute(
            select(CaseEvent)
            .where(CaseEvent.case_id == _parse_uuid(case_id))
            .order_by(CaseEvent.created_at.asc())
        )
        events = [_event_to_out(e) for e in result.scalars().all()]
        return ApiResponse(data=events)
