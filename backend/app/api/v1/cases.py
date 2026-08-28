"""案件管理路由（D05 §8）。"""

from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

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
    CaseType,
    CaseUpdate,
    CommentCreate,
)
from app.schemas.common import ApiResponse, CaseStatus, PageResponse

router = APIRouter()

# 案件状态机（基准 §3.2）：CLOSED 为终态；重开仅允许 FALSE_ALARM → IN_REVIEW 复查
_CASE_TRANSITIONS: dict[str, set[str]] = {
    CaseStatus.OPEN.value: {CaseStatus.IN_REVIEW.value, CaseStatus.FALSE_ALARM.value},
    CaseStatus.IN_REVIEW.value: {
        CaseStatus.CONFIRMED.value,
        CaseStatus.CLOSED.value,
        CaseStatus.FALSE_ALARM.value,
        CaseStatus.OPEN.value,
    },
    CaseStatus.CONFIRMED.value: {CaseStatus.CLOSED.value},
    CaseStatus.FALSE_ALARM.value: {CaseStatus.CLOSED.value, CaseStatus.IN_REVIEW.value},
    CaseStatus.CLOSED.value: set(),
}


def _validate_transition(current: str, target: str) -> None:
    """校验状态转移合法性；非法转移抛 ConflictError。"""
    allowed = _CASE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ConflictError(
            f"invalid status transition: {current} -> {target} "
            f"(allowed: {sorted(allowed) or 'none'})"
        )


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
        type=CaseType(case.type),
        level=CaseLevel(case.level),
        status=CaseStatus(case.status),
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


async def _load_case(session: Any, case_id: str, tenant_id: str) -> Case:
    """按主键加载案件，找不到抛 NotFoundError。"""
    result = await session.execute(
        select(Case).where(Case.id == _parse_uuid(case_id), Case.tenant_id == uuid.UUID(tenant_id))
    )
    case = result.scalar_one_or_none()
    if case is None:
        raise NotFoundError(f"case not found: {case_id}")
    return cast(Case, case)


@router.get("", response_model=ApiResponse[PageResponse[CaseOut]])
async def list_cases(
    status: CaseStatus | None = None,
    level: CaseLevel | None = None,
    case_type: str | None = Query(default=None, alias="type"),
    assignee_id: str | None = None,
    unassigned: bool = False,
    exclude_closed: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("case:read")),
) -> ApiResponse[PageResponse[CaseOut]]:
    """分页查询案件。

    支持 status / level / type / assignee_id / unassigned / exclude_closed 过滤。
    （供前端"我的待办/未分配/已关闭"视图映射真实查询条件。）
    """
    async with session_scope(tenant_id) as session:
        # 单一过滤构造器，保证列表与计数条件永远一致
        filters = [Case.tenant_id == uuid.UUID(tenant_id)]
        if status is not None:
            filters.append(Case.status == status.value)
        if level is not None:
            filters.append(Case.level == level.value)
        if case_type:
            filters.append(Case.type == case_type)
        if assignee_id:
            filters.append(Case.assigned_to == _to_uuid(assignee_id))
        if unassigned:
            filters.append(Case.assigned_to.is_(None))
        if exclude_closed:
            filters.append(Case.status != CaseStatus.CLOSED.value)

        total = (
            await session.execute(
                select(func.count()).select_from(Case).where(*filters)
            )
        ).scalar() or 0
        result = await session.execute(
            select(Case)
            .where(*filters)
            .order_by(Case.created_at.desc())
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
    _user: dict[str, Any] = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """手动创建案件（关联交易，写首条 CREATED 事件）。

    case_no 为日期+随机数，并发创建可能撞唯一约束（0008 迁移）：
    捕获 IntegrityError 重新生成编号重试。
    """
    now = datetime.now(UTC)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
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

                case_no = _gen_case_no(now)
                if attempt:
                    case_no = f"{case_no}-{uuid.uuid4().hex[:4].upper()}"
                case = Case(
                    tenant_id=uuid.UUID(tenant_id),
                    transaction_id=tx.id,
                    score_id=score.id if score else None,
                    case_no=case_no,
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
        except IntegrityError as exc:
            last_exc = exc
    raise ConflictError(f"case_no generation conflict after retries: {last_exc}") from last_exc


@router.get("/{case_id}", response_model=ApiResponse[CaseOut])
async def get_case(
    case_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict[str, Any] = Depends(require_scope("case:read")),
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
    _user: dict[str, Any] = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """更新案件状态/处理人/备注（写对应事件）。"""
    async with session_scope(tenant_id) as session:
        case = await _load_case(session, case_id, tenant_id)

        if req.status is not None:
            from_status = case.status
            to_status = req.status.value
            _validate_transition(from_status, to_status)
            case.status = to_status
            # 统一维护终态时间戳（与 close_case 端点保持一致）
            if to_status == CaseStatus.CONFIRMED.value and case.confirmed_at is None:
                case.confirmed_at = datetime.now(UTC)
            if to_status == CaseStatus.CLOSED.value:
                case.closed_at = datetime.now(UTC)
            session.add(
                CaseEvent(
                    tenant_id=uuid.UUID(tenant_id),
                    case_id=case.id,
                    action="STATUS_CHANGED",
                    from_status=from_status,
                    to_status=to_status,
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
    _user: dict[str, Any] = Depends(require_scope("case:write")),
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
    _user: dict[str, Any] = Depends(require_scope("case:write")),
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
    _user: dict[str, Any] = Depends(require_scope("case:read")),
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
