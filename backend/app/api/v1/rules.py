"""规则引擎路由（D05 §5）。

CRUD + 版本管理 + 灰度推进 + 回滚。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_scope
from app.schemas.common import ApiResponse, PageResponse
from app.schemas.rule import (
    RuleCreate,
    RuleOut,
    RulePromoteRequest,
    RuleRollbackRequest,
    RuleUpdate,
    RuleVersionCreate,
    RuleVersionOut,
)

router = APIRouter()


@router.get("", response_model=ApiResponse[PageResponse[RuleOut]])
async def list_rules(
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[PageResponse[RuleOut]]:
    """分页查询规则列表。"""
    # TODO: 查 rules 表
    return ApiResponse(data=PageResponse(items=[], total=0))


@router.post("", response_model=ApiResponse[RuleOut])
async def create_rule(
    req: RuleCreate,
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleOut]:
    """新建规则（创建 DRAFT 版本 v1）。"""
    # TODO: 写 rules + rule_versions 表
    return ApiResponse(data=RuleOut(id="TODO", rule_id="R057", name=req.name, dsl=req.dsl, severity=req.severity, action=req.action, status="DRAFT", version="v1", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.get("/{rule_id}", response_model=ApiResponse[RuleOut])
async def get_rule(
    rule_id: str,
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[RuleOut]:
    """查询规则详情（含版本历史）。"""
    # TODO: 查 rules + rule_versions 表
    from app.core.exceptions import NotFoundError

    raise NotFoundError(f"rule not found: {rule_id}")


@router.put("/{rule_id}", response_model=ApiResponse[RuleOut])
async def update_rule(
    rule_id: str,
    req: RuleUpdate,
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleOut]:
    """更新规则草稿（仅 DRAFT 状态可更新）。"""
    # TODO: 校验 status=DRAFT + 更新
    return ApiResponse(data=RuleOut(id=rule_id, rule_id="R001", name="TODO", dsl="", severity="WARN", action="REVIEW", status="DRAFT", version="v1", created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str,
    _user: dict = Depends(require_scope("rule:write")),
) -> None:
    """软删除规则（仅 DRAFT 状态可删除）。"""
    # TODO: 校验 status=DRAFT + 标记 deleted_at
    return None


@router.post("/{rule_id}/versions", response_model=ApiResponse[RuleVersionOut])
async def create_version(
    rule_id: str,
    req: RuleVersionCreate,
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """基于当前规则创建新版本草稿。"""
    # TODO: 写 rule_versions 表
    return ApiResponse(data=RuleVersionOut(id="TODO", rule_id=rule_id, version="v2", dsl=req.dsl, status="DRAFT", canary_percent=0, created_by="TODO", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.post("/{rule_id}/promote", response_model=ApiResponse[RuleVersionOut])
async def promote_rule(
    rule_id: str,
    req: RulePromoteRequest,
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """版本灰度推进：DRAFT → CANARY → ACTIVE。"""
    # TODO: 状态机校验 + 更新 rule_versions.status
    return ApiResponse(data=RuleVersionOut(id="TODO", rule_id=rule_id, version="v2", dsl="", status=req.to_status, canary_percent=req.canary_percentage or 0, created_by="TODO", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.post("/{rule_id}/rollback", response_model=ApiResponse[RuleVersionOut])
async def rollback_rule(
    rule_id: str,
    req: RuleRollbackRequest,
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """紧急回滚到上一稳定版本。"""
    # TODO: 当前版本转 RETIRED + 目标版本转 ACTIVE
    return ApiResponse(data=RuleVersionOut(id="TODO", rule_id=rule_id, version="v1", dsl="", status="ACTIVE", canary_percent=0, created_by="TODO", created_at="2026-01-01T00:00:00Z"))  # type: ignore[arg-type]


@router.get("/{rule_id}/hits", response_model=ApiResponse[PageResponse[dict]])
async def rule_hits(
    rule_id: str,
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[PageResponse[dict]]:
    """查询规则历史命中。"""
    # TODO: 查 scores.rule_hits JSONB
    return ApiResponse(data=PageResponse(items=[], total=0))
