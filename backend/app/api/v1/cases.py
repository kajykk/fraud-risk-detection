"""案件管理路由（D05 §8）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.case import (
    CaseCloseRequest,
    CaseCreate,
    CaseEventOut,
    CaseOut,
    CaseUpdate,
    CommentCreate,
)
from app.schemas.common import ApiResponse, PageResponse

router = APIRouter()


@router.get("", response_model=ApiResponse[PageResponse[CaseOut]])
async def list_cases(
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[PageResponse[CaseOut]]:
    """分页查询案件。"""
    # TODO: 查 cases 表
    return ApiResponse(data=PageResponse(items=[], total=0))


@router.post("", response_model=ApiResponse[CaseOut])
async def create_case(
    req: CaseCreate,
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """手动创建案件。"""
    # TODO: 写 cases 表
    return ApiResponse(data=CaseOut(id="TODO", case_no="TODO", type=req.type if hasattr(req, 'type') else "FRAUD", level=req.priority, status="OPEN", amount=0, created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.get("/{case_id}", response_model=ApiResponse[CaseOut])
async def get_case(
    case_id: str,
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[CaseOut]:
    """查询案件详情。"""
    # TODO: 查 cases 表
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"case not found: {case_id}")


@router.patch("/{case_id}", response_model=ApiResponse[CaseOut])
async def update_case(
    case_id: str,
    req: CaseUpdate,
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """更新案件状态/优先级/处理人。"""
    # TODO: 更新 cases 表 + 写 case_events
    return ApiResponse(data=CaseOut(id=case_id, case_no="TODO", type="FRAUD", level="P1", status="OPEN", amount=0, created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.post("/{case_id}/comments", response_model=ApiResponse[CaseEventOut])
async def add_comment(
    case_id: str,
    req: CommentCreate,
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseEventOut]:
    """添加案件备注。"""
    # TODO: 写 case_events 表
    return ApiResponse(data=CaseEventOut(id="TODO", case_id=case_id, action="COMMENT", operator_id="TODO", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.post("/{case_id}/close", response_model=ApiResponse[CaseOut])
async def close_case(
    case_id: str,
    req: CaseCloseRequest,
    _user: dict = Depends(require_scope("case:write")),
) -> ApiResponse[CaseOut]:
    """关闭案件。"""
    # TODO: 状态机校验 + 写 cases.closed_at
    return ApiResponse(data=CaseOut(id=case_id, case_no="TODO", type="FRAUD", level="P1", status="CLOSED", amount=0, created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.get("/{case_id}/timeline", response_model=ApiResponse[list[CaseEventOut]])
async def case_timeline(
    case_id: str,
    _user: dict = Depends(require_scope("case:read")),
) -> ApiResponse[list[CaseEventOut]]:
    """案件操作时间线。"""
    # TODO: 查 case_events 表
    return ApiResponse(data=[])
