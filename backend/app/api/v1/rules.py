"""规则引擎路由（D05 §5）。

CRUD + 版本管理 + 灰度推进 + 回滚。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, or_, select, update

from app.api.deps import get_tenant_id, require_scope
from app.core.exceptions import (
    ApproverRequiredError,
    NoRollbackTargetError,
    NotFoundError,
    RuleNotDeletableError,
    RuleNotDraftError,
    RuleStatusTransitionInvalidError,
)
from app.db.session import session_scope
from app.models.rule import Rule, RuleVersion
from app.models.transaction import Score
from app.schemas.common import ApiResponse, PageResponse, RuleStatus
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

_DEFAULT_SEVERITY = "WARN"

# 允许的状态机转移：DRAFT → CANARY → ACTIVE
_TRANSITIONS: dict[RuleStatus, set[RuleStatus]] = {
    RuleStatus.DRAFT: {RuleStatus.CANARY},
    RuleStatus.CANARY: {RuleStatus.ACTIVE},
}


def _to_uuid(value: str) -> uuid.UUID:
    """将字符串转换为 UUID；非 UUID 时用 uuid5 生成确定性 UUID（如 user sub）。"""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(value))


def _infer_category(dsl: str) -> str:
    """根据 DSL 关键字推断规则类别，无法推断时返回 CUSTOM。"""
    dsl_upper = dsl.upper()
    for keyword, category in (
        ("AMOUNT", "AMOUNT"),
        ("GEO", "GEO"),
        ("COUNTRY", "GEO"),
        ("DEVICE", "DEVICE"),
        ("VELOCITY", "VELOCITY"),
        ("COUNT", "VELOCITY"),
        ("AML", "AML"),
        ("SANCTION", "AML"),
    ):
        if keyword in dsl_upper:
            return category
    return "CUSTOM"


def _next_version(current_version: str | None) -> str:
    """版本号递增：v1 → v2。"""
    if not current_version:
        return "v2"
    try:
        return f"v{int(current_version.lstrip('vV')) + 1}"
    except ValueError:
        return "v2"


def _rule_to_out(rule: Rule, version: RuleVersion | None) -> RuleOut:
    """Rule ORM → RuleOut。

    注：severity / valid_from / valid_to / scope 模型无对应字段，返回默认值。
    """
    return RuleOut(
        id=str(rule.id),
        rule_id=rule.rule_id,
        name=rule.name,
        description=rule.description,
        dsl=version.expression if version else rule.expression,
        severity=_DEFAULT_SEVERITY,
        action=rule.action,
        status=RuleStatus(version.status) if version else RuleStatus.DRAFT,
        version=version.version if version else rule.current_version,
        valid_from=None,
        valid_to=None,
        scope={},
        hit_count_24h=0,
        false_positive_rate=0.0,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _version_to_out(rule: Rule, version: RuleVersion) -> RuleVersionOut:
    """RuleVersion ORM → RuleVersionOut（rule_id 用规则的业务编号）。"""
    return RuleVersionOut(
        id=str(version.id),
        rule_id=rule.rule_id,
        version=version.version,
        dsl=version.expression,
        status=RuleStatus(version.status),
        canary_percent=version.canary_percent,
        created_by=str(version.created_by),
        created_at=version.created_at,
        promoted_at=version.promoted_at,
    )


async def _load_rule(session, rule_id: str, tenant_id: str) -> Rule:
    """按业务编号加载规则（含 tenant_id 为空的全局规则），找不到抛 NotFoundError。"""
    result = await session.execute(
        select(Rule).where(
            Rule.rule_id == rule_id,
            or_(Rule.tenant_id == uuid.UUID(tenant_id), Rule.tenant_id.is_(None)),
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise NotFoundError(f"rule not found: {rule_id}")
    return rule


async def _latest_version(session, rule: Rule) -> RuleVersion | None:
    """查询规则最新版本（created_at 倒序取第一条）。"""
    result = await session.execute(
        select(RuleVersion)
        .where(RuleVersion.rule_id == rule.id)
        .order_by(RuleVersion.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=ApiResponse[PageResponse[RuleOut]])
async def list_rules(
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[PageResponse[RuleOut]]:
    """分页查询规则列表（tenant_id 为空代表全局规则）。"""
    async with session_scope(tenant_id) as session:
        scope_filter = or_(
            Rule.tenant_id == uuid.UUID(tenant_id), Rule.tenant_id.is_(None)
        )
        total = (
            await session.execute(
                select(func.count()).select_from(Rule).where(scope_filter)
            )
        ).scalar() or 0
        result = await session.execute(
            select(Rule)
            .where(scope_filter)
            .order_by(Rule.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = []
        for rule in result.scalars().all():
            version = await _latest_version(session, rule)
            items.append(_rule_to_out(rule, version))
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )


@router.post("", response_model=ApiResponse[RuleOut])
async def create_rule(
    req: RuleCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleOut]:
    """新建规则（创建 DRAFT 版本 v1）。"""
    async with session_scope(tenant_id) as session:
        seq = (
            await session.execute(
                select(func.count())
                .select_from(Rule)
                .where(Rule.tenant_id == uuid.UUID(tenant_id))
            )
        ).scalar() or 0
        rule = Rule(
            tenant_id=uuid.UUID(tenant_id),
            rule_id=f"R{seq + 1:04d}",
            name=req.name,
            description=req.description,
            category=_infer_category(req.dsl),
            expression=req.dsl,
            action=req.action,
            priority=50,
            enabled=True,
            current_version="v1",
        )
        session.add(rule)
        await session.flush()
        version = RuleVersion(
            tenant_id=uuid.UUID(tenant_id),
            rule_id=rule.id,
            version="v1",
            expression=req.dsl,
            status=RuleStatus.DRAFT.value,
            canary_percent=0,
            created_by=_to_uuid(_user["sub"]),
        )
        session.add(version)
        return ApiResponse(data=_rule_to_out(rule, version))


@router.get("/{rule_id}", response_model=ApiResponse[RuleOut])
async def get_rule(
    rule_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[RuleOut]:
    """查询规则详情（含最新版本信息）。"""
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        version = await _latest_version(session, rule)
        return ApiResponse(data=_rule_to_out(rule, version))


@router.put("/{rule_id}", response_model=ApiResponse[RuleOut])
async def update_rule(
    rule_id: str,
    req: RuleUpdate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleOut]:
    """更新规则草稿（仅最新版本为 DRAFT 可更新）。"""
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        version = await _latest_version(session, rule)
        if version is None or version.status != RuleStatus.DRAFT.value:
            raise RuleNotDraftError(f"rule {rule_id} is not in DRAFT status")
        if req.name is not None:
            rule.name = req.name
        if req.description is not None:
            rule.description = req.description
        if req.dsl is not None:
            rule.expression = req.dsl
            version.expression = req.dsl
        rule.updated_at = datetime.now(UTC)
        return ApiResponse(data=_rule_to_out(rule, version))


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> None:
    """删除规则（仅最新版本为 DRAFT 可删，物理删除 Rule + RuleVersion）。"""
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        version = await _latest_version(session, rule)
        if version is None or version.status != RuleStatus.DRAFT.value:
            raise RuleNotDeletableError(f"rule {rule_id} is not deletable")
        await session.execute(delete(RuleVersion).where(RuleVersion.rule_id == rule.id))
        await session.delete(rule)
    return None


@router.post("/{rule_id}/versions", response_model=ApiResponse[RuleVersionOut])
async def create_version(
    rule_id: str,
    req: RuleVersionCreate,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """基于当前规则创建新版本草稿（版本号递增）。"""
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        next_version = _next_version(rule.current_version)
        version = RuleVersion(
            tenant_id=uuid.UUID(tenant_id),
            rule_id=rule.id,
            version=next_version,
            expression=req.dsl,
            status=RuleStatus.DRAFT.value,
            canary_percent=0,
            created_by=_to_uuid(_user["sub"]),
        )
        session.add(version)
        rule.current_version = next_version
        rule.updated_at = datetime.now(UTC)
        await session.flush()
        return ApiResponse(data=_version_to_out(rule, version))


@router.post("/{rule_id}/promote", response_model=ApiResponse[RuleVersionOut])
async def promote_rule(
    rule_id: str,
    req: RulePromoteRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """版本灰度推进：DRAFT → CANARY → ACTIVE。"""
    if not req.approver_id:
        raise ApproverRequiredError("approver required")
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        version = await _latest_version(session, rule)
        if version is None or version.status != req.from_status.value:
            raise RuleStatusTransitionInvalidError(
                f"rule {rule_id} current status is not {req.from_status.value}"
            )
        if req.to_status not in _TRANSITIONS.get(req.from_status, set()):
            raise RuleStatusTransitionInvalidError(
                f"invalid transition {req.from_status.value} -> {req.to_status.value}"
            )
        version.status = req.to_status.value
        if req.to_status == RuleStatus.CANARY:
            version.canary_percent = req.canary_percentage or 0
        if req.to_status == RuleStatus.ACTIVE:
            version.promoted_at = datetime.now(UTC)
            # 同规则其他 ACTIVE 版本转 RETIRED
            await session.execute(
                update(RuleVersion)
                .where(
                    RuleVersion.rule_id == rule.id,
                    RuleVersion.status == RuleStatus.ACTIVE.value,
                    RuleVersion.id != version.id,
                )
                .values(status=RuleStatus.RETIRED.value)
            )
        return ApiResponse(data=_version_to_out(rule, version))


@router.post("/{rule_id}/rollback", response_model=ApiResponse[RuleVersionOut])
async def rollback_rule(
    rule_id: str,
    req: RuleRollbackRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:write")),
) -> ApiResponse[RuleVersionOut]:
    """紧急回滚：当前版本转 RETIRED，目标版本（缺省取最近 RETIRED）转 ACTIVE。"""
    if not req.approver_id:
        raise ApproverRequiredError("approver required")
    async with session_scope(tenant_id) as session:
        rule = await _load_rule(session, rule_id, tenant_id)
        current = await _latest_version(session, rule)
        if current is None or current.status != RuleStatus.ACTIVE.value:
            raise RuleStatusTransitionInvalidError(f"rule {rule_id} is not ACTIVE")
        if req.target_version is not None:
            target_result = await session.execute(
                select(RuleVersion).where(
                    RuleVersion.rule_id == rule.id,
                    RuleVersion.version == f"v{req.target_version}",
                )
            )
            target = target_result.scalar_one_or_none()
        else:
            target_result = await session.execute(
                select(RuleVersion)
                .where(
                    RuleVersion.rule_id == rule.id,
                    RuleVersion.status == RuleStatus.RETIRED.value,
                )
                .order_by(RuleVersion.created_at.desc())
                .limit(1)
            )
            target = target_result.scalar_one_or_none()
        if target is None:
            raise NoRollbackTargetError(f"no rollback target for rule {rule_id}")
        current.status = RuleStatus.RETIRED.value
        target.status = RuleStatus.ACTIVE.value
        target.promoted_at = datetime.now(UTC)
        rule.current_version = target.version
        rule.updated_at = datetime.now(UTC)
        return ApiResponse(data=_version_to_out(rule, target))


@router.get("/{rule_id}/hits", response_model=ApiResponse[PageResponse[dict]])
async def rule_hits(
    rule_id: str,
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(require_scope("rule:read")),
) -> ApiResponse[PageResponse[dict]]:
    """查询规则历史命中（scores.rule_hits JSONB 包含该规则的评分记录）。"""
    async with session_scope(tenant_id) as session:
        await _load_rule(session, rule_id, tenant_id)
        hit_filter = Score.rule_hits.contains([{"rule_id": rule_id}])
        total = (
            await session.execute(
                select(func.count())
                .select_from(Score)
                .where(Score.tenant_id == uuid.UUID(tenant_id), hit_filter)
            )
        ).scalar() or 0
        result = await session.execute(
            select(Score)
            .where(Score.tenant_id == uuid.UUID(tenant_id), hit_filter)
            .order_by(Score.scored_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = []
        for score in result.scalars().all():
            items.append(
                {
                    "score_id": str(score.id),
                    "transaction_id": str(score.transaction_id),
                    "risk_score": float(score.risk_score),
                    "risk_band": score.risk_band,
                    "decision": score.decision,
                    "rule_hits": score.rule_hits,
                    "scored_at": score.scored_at.isoformat() if score.scored_at else None,
                }
            )
        return ApiResponse(
            data=PageResponse(items=items, page=page, page_size=page_size, total=total)
        )
