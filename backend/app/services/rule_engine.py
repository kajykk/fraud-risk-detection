"""RuleEngine（D03 §4.2）。

- 安全 DSL 解析（tokenizer + 递归下降，不支持 eval）
- 规则版本加载（Redis 缓存，按 tenant_id 分片）
- 短路求值（按 priority 排序，任一 BLOCK 即 BLOCK）
- 热更新（Redis pubsub 触发缓存失效）

DSL 语法（expr := or_expr）：
    and_expr  := cmp_expr ("&&" cmp_expr)*
    cmp_expr  := operand ("==" | "!=" | ">" | ">=" | "<" | "<=") operand
    operand   := field | number | string | bool
    field     := [a-z_][a-z0-9_]*（对应交易字段）
示例：
    amount > 1000000 && tx_type == "WITHDRAW"
    channel == "QR" || amount >= 500000
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select

from app.core.exceptions import RuleDSLInvalidError
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.db.session import get_session_factory, set_tenant_id
from app.models.rule import Rule, RuleVersion

logger = get_logger(__name__)

_RULES_CACHE_TTL = 300  # 5 分钟
_RULES_RELOAD_CHANNEL = "frd:rules_reload"

# 表达式最大括号嵌套深度（防递归下降栈溢出）
_MAX_PARSE_DEPTH = 64

_TOKEN_RE = re.compile(
    r"\s*(?P<num>-?\d+(?:\.\d+)?)"
    r"|\s*(?P<str>\"[^\"]*\"|'[^']*')"
    r"|\s*(?P<op>==|!=|>=|<=|>|<|&&|\|\||\(|\))"
    r"|\s*(?P<field>[a-zA-Z_][a-zA-Z0-9_]*)"
)


class _DslSyntaxError(ValueError):
    pass


class _StrLiteral:
    """字符串字面量（与字段名区分，避免被当作 tx 字段查询）。"""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"_StrLiteral({self.value!r})"


class _Expr:
    def evaluate(self, tx: dict[str, Any]) -> bool:
        raise NotImplementedError


class _CmpExpr(_Expr):
    OPS: dict[str, Callable[[Any, Any], bool]] = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }

    def __init__(self, left: Any, op: str, right: Any) -> None:
        self.left = left
        self.op = op
        self.right = right

    @staticmethod
    def _resolve(operand: Any, tx: dict[str, Any]) -> tuple[Any, bool]:
        """解析操作数为实际值。返回 (value, found)。

        - _StrLiteral → 字面量
        - str → 视为字段名查 tx（缺失时 found=False）
        - 其他（int/float/bool）→ 原样
        """
        if isinstance(operand, _StrLiteral):
            return operand.value, True
        if isinstance(operand, str):
            if operand not in tx:
                return None, False
            return tx[operand], True
        return operand, True

    def evaluate(self, tx: dict[str, Any]) -> bool:
        lv, l_found = self._resolve(self.left, tx)
        rv, r_found = self._resolve(self.right, tx)
        if not l_found or not r_found:
            return False
        if lv is None or rv is None:
            return False
        try:
            return bool(self.OPS[self.op](lv, rv))
        except TypeError:
            # 类型不匹配（如 int vs str）视为不命中
            return False


class _AndExpr(_Expr):
    def __init__(self, parts: list[_Expr]) -> None:
        self.parts = parts

    def evaluate(self, tx: dict[str, Any]) -> bool:
        return all(p.evaluate(tx) for p in self.parts)


class _OrExpr(_Expr):
    def __init__(self, parts: list[_Expr]) -> None:
        self.parts = parts

    def evaluate(self, tx: dict[str, Any]) -> bool:
        return any(p.evaluate(tx) for p in self.parts)


def _parse_expression(dsl: str) -> _Expr:
    """解析 DSL 字符串为表达式树。非法语法抛 _DslSyntaxError。"""
    tokens = _tokenize(dsl)
    pos = 0

    def peek() -> tuple[str, str] | None:
        return tokens[pos] if pos < len(tokens) else None

    def parse_or(depth: int = 0) -> _Expr:
        nonlocal pos
        left = parse_and(depth)
        while peek() == ("op", "||"):
            pos += 1
            right = parse_and(depth)
            parts = left.parts if isinstance(left, _OrExpr) else [left]
            parts.append(right)
            left = _OrExpr(parts)
        return left

    def parse_and(depth: int = 0) -> _Expr:
        nonlocal pos
        left = parse_cmp(depth)
        while peek() == ("op", "&&"):
            pos += 1
            right = parse_cmp(depth)
            parts = left.parts if isinstance(left, _AndExpr) else [left]
            parts.append(right)
            left = _AndExpr(parts)
        return left

    def parse_cmp(depth: int = 0) -> _Expr:
        nonlocal pos
        if depth > _MAX_PARSE_DEPTH:
            raise _DslSyntaxError(f"expression nesting too deep (max {_MAX_PARSE_DEPTH})")
        if peek() == ("op", "("):
            pos += 1
            inner = parse_or(depth + 1)
            if peek() != ("op", ")"):
                raise _DslSyntaxError("missing closing parenthesis")
            pos += 1
            return inner
        left = parse_operand()
        tok = peek()
        if tok is None or tok[0] != "op" or tok[1] not in _CmpExpr.OPS:
            raise _DslSyntaxError(f"expected comparison operator, got {tok}")
        pos += 1
        right = parse_operand()
        return _CmpExpr(left, tok[1], right)

    def parse_operand() -> Any:
        nonlocal pos
        tok = peek()
        if tok is None:
            raise _DslSyntaxError("unexpected end of expression")
        kind, value = tok
        pos += 1
        if kind == "num":
            return float(value) if "." in value else int(value)
        if kind == "str":
            return _StrLiteral(value[1:-1])
        if kind == "field":
            if value in ("true", "True"):
                return True
            if value in ("false", "False"):
                return False
            return value
        raise _DslSyntaxError(f"unexpected token {value}")

    if not tokens:
        raise _DslSyntaxError("empty expression")
    expr = parse_or()
    if pos != len(tokens):
        raise _DslSyntaxError(f"unexpected trailing tokens: {tokens[pos:]}")
    return expr


def _tokenize(dsl: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    idx = 0
    while idx < len(dsl):
        # 尾随空白（含 \n）应被容忍，而非当作非法字符
        if dsl[idx:].isspace():
            break
        match = _TOKEN_RE.match(dsl, idx)
        if match is None:
            raise _DslSyntaxError(f"unexpected character at offset {idx}")
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        idx = match.end()
    return tokens


def validate_expression(dsl: str) -> None:
    """校验 DSL 语法（供规则创建/更新接口在入库前调用）。

    校验失败抛 RuleDSLInvalidError（含具体原因），避免坏规则入库后
    在运行时拖垮整个租户的规则引擎。
    """
    try:
        _parse_expression(dsl)
    except _DslSyntaxError as exc:
        raise RuleDSLInvalidError(f"invalid rule expression: {exc}") from exc


class CompiledRule:
    """编译后的规则（DSL 解析结果缓存）。

    is_canary=True 的规则为灰度版本：仅对确定性分桶命中的流量生效
    （canary_percent 为放量百分比 0-100）。
    """

    __slots__ = (
        "rule_id",
        "rule_name",
        "action",
        "severity",
        "priority",
        "expr",
        "is_canary",
        "canary_percent",
    )

    def __init__(
        self,
        rule_id: str,
        rule_name: str,
        action: str,
        severity: str,
        priority: int,
        expr: _Expr,
        *,
        is_canary: bool = False,
        canary_percent: int = 100,
    ) -> None:
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.action = action
        self.severity = severity
        self.priority = priority
        self.expr = expr
        self.is_canary = is_canary
        self.canary_percent = canary_percent


def _canary_bucket(rule_id: str, external_tx_id: str) -> int:
    """确定性灰度分桶（0-99）：同一交易对同一规则恒落同桶，保证体验一致。"""
    import hashlib

    digest = hashlib.md5(f"{rule_id}:{external_tx_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass
class RuleHit:
    """命中规则。"""

    rule_id: str
    rule_name: str
    action: str  # BLOCK / REVIEW
    severity: str = "WARN"
    explanation: str | None = None


@dataclass
class RuleResult:
    """规则引擎输出。"""

    hit_rules: list[RuleHit] = field(default_factory=list)
    action: str = "ALLOW"  # 任一 BLOCK -> BLOCK；任一 REVIEW -> REVIEW；无 -> ALLOW
    latency_ms: int = 0
    fallback_used: bool = False


class RuleEngine:
    """规则引擎（DSL 解析 + 匹配）。"""

    _compiled_cache: dict[str, tuple[float, list[CompiledRule]]] = {}

    async def evaluate(
        self,
        transaction: dict[str, Any],
        tenant_id: str,
    ) -> RuleResult:
        """评估交易命中哪些规则（短路：任一 BLOCK 即 BLOCK）。"""
        start = time.perf_counter()
        try:
            rules = await self._load_compiled(tenant_id)
        except Exception as exc:
            # fail-closed：规则引擎故障时降级为人工审核，绝不静默放行
            logger.warning("rule_engine_load_failed", tenant_id=tenant_id, error=str(exc))
            return RuleResult(hit_rules=[], action="REVIEW", latency_ms=1, fallback_used=True)

        hit_rules: list[RuleHit] = []
        action = "ALLOW"
        for rule in rules:
            try:
                # 灰度规则：确定性分桶放量，未命中桶的交易跳过该规则
                if rule.is_canary:
                    tx_key = str(transaction.get("external_tx_id") or "")
                    if _canary_bucket(rule.rule_id, tx_key) >= rule.canary_percent:
                        continue
                if rule.expr.evaluate(transaction):
                    severity = rule.severity or "WARN"
                    hit_rules.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            rule_name=rule.rule_name,
                            action=rule.action,
                            severity=severity,
                            explanation=f"rule {rule.rule_id} matched",
                        )
                    )
                    if rule.action == "BLOCK":
                        action = "BLOCK"
                        break  # 短路：任一 BLOCK 即 BLOCK
                    if rule.action == "REVIEW" and action != "BLOCK":
                        action = "REVIEW"
            except Exception as exc:
                logger.warning(
                    "rule_eval_failed",
                    tenant_id=tenant_id,
                    rule_id=rule.rule_id,
                    error=str(exc),
                )

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "rule_engine_evaluate",
            tenant_id=tenant_id,
            external_tx_id=transaction.get("external_tx_id"),
            hit_count=len(hit_rules),
            action=action,
            latency_ms=latency_ms,
        )
        return RuleResult(hit_rules=hit_rules, action=action, latency_ms=latency_ms)

    async def _load_compiled(self, tenant_id: str) -> list[CompiledRule]:
        """加载生效规则（ACTIVE 全量 + CANARY 灰度；Redis 缓存 → DB 兜底），编译并缓存。"""
        cache_key = f"rules:{tenant_id}:active"
        cache_ts, cached = self._compiled_cache.get(cache_key, (0.0, []))
        if time.time() - cache_ts < _RULES_CACHE_TTL:
            return cached

        rules = await self._load_rules_from_store(tenant_id)
        compiled: list[CompiledRule] = []
        for rule in rules:
            try:
                expr = _parse_expression(rule["expression"])
            except _DslSyntaxError as exc:
                # 单条坏规则隔离：跳过并告警，避免拖垮整个租户的规则引擎
                # （fail-closed 兜底见 evaluate：坏规则不参与决策）
                logger.error(
                    "rule_compile_failed",
                    tenant_id=tenant_id,
                    rule_id=rule["rule_id"],
                    error=str(exc),
                )
                continue
            compiled.append(
                CompiledRule(
                    rule_id=rule["rule_id"],
                    rule_name=rule["name"],
                    action=rule["action"],
                    severity=rule.get("severity", "WARN"),
                    priority=rule.get("priority", 50),
                    expr=expr,
                    is_canary=rule.get("status") == "CANARY",
                    canary_percent=int(rule.get("canary_percent", 100)),
                )
            )
        compiled.sort(key=lambda r: r.priority, reverse=False)
        self._compiled_cache[cache_key] = (time.time(), compiled)

        try:
            redis = get_redis()
            # 与 load_rules 共用同一命名空间，写入完整规则数据（而非仅 rule_id），
            # 避免同 key 两种形状导致 load_rules 命中后反序列化出字符串列表
            await redis.set(
                cache_key,
                json.dumps(rules, ensure_ascii=False),
                ex=_RULES_CACHE_TTL,
            )
        except Exception as exc:
            logger.warning("rule_cache_write_failed", error=str(exc))
        return compiled

    async def _load_rules_from_store(self, tenant_id: str) -> list[dict[str, Any]]:
        """从 DB 加载生效规则（本租户 + 全局 tenant_id IS NULL）。

        加载 ACTIVE 与 CANARY 两个状态的最新版本：
        - ACTIVE：全量生效；
        - CANARY：灰度版本，evaluate 按确定性分桶（canary_percent）放量。
        同一规则允许同时存在一条 ACTIVE（旧版全量）+ 一条 CANARY（新版灰度），
        这是金丝雀发布的预期形态。
        """
        factory = get_session_factory()
        async with factory() as session:
            await set_tenant_id(session, tenant_id)
            result = await session.execute(
                select(
                    Rule,
                    RuleVersion.expression,
                    RuleVersion.status,
                    RuleVersion.canary_percent,
                )
                .join(RuleVersion, RuleVersion.rule_id == Rule.id)
                .where(
                    Rule.enabled.is_(True),
                    RuleVersion.status.in_(["ACTIVE", "CANARY"]),
                    or_(Rule.tenant_id.is_(None), Rule.tenant_id == tenant_id),
                )
                .order_by(Rule.priority, RuleVersion.created_at.desc())
            )
            # 每条规则的每个状态取最新一条（created_at 倒序首个命中）
            picked: dict[tuple[str, str], dict[str, Any]] = {}
            for rule, expression, status, canary_pct in result:
                key = (str(rule.id), str(status))
                if key in picked:
                    continue
                picked[key] = {
                    "rule_pk": str(rule.id),
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "action": rule.action,
                    "expression": expression,
                    "priority": rule.priority,
                    "severity": "WARN",
                    "status": str(status),
                    "canary_percent": int(canary_pct or 0),
                }
            return list(picked.values())

    async def load_rules(self, tenant_id: str, version: str | None = None) -> list[dict[str, Any]]:
        """加载规则版本（Redis 缓存优先）。"""
        try:
            redis = get_redis()
            key = f"rules:{tenant_id}:active" if not version else f"rules:{tenant_id}:{version}"
            cached = await redis.get(key)
            if cached:
                data: list[dict[str, Any]] = json.loads(cached)
                return data
        except Exception as exc:
            logger.warning("rule_cache_read_failed", error=str(exc))
        return await self._load_rules_from_store(tenant_id)

    def invalidate_cache(self, tenant_id: str | None = None) -> int:
        """失效进程内规则编译缓存。

        tenant_id 非空时仅失效该租户（含全局前缀匹配），为空时全量失效。
        返回清除的缓存条数。供 API 写路径与 pubsub 监听共用，
        保证多进程/多副本部署下各进程缓存一致。
        """
        prefix = f"rules:{tenant_id}:" if tenant_id else "rules:"
        removed = 0
        for key in list(self._compiled_cache):
            if key.startswith(prefix):
                self._compiled_cache.pop(key, None)
                removed += 1
        return removed

    async def hot_reload(self, tenant_id: str) -> None:
        """热更新规则：失效本进程缓存 + Redis pubsub 广播其他进程失效。"""
        self.invalidate_cache(tenant_id)
        try:
            redis = get_redis()
            await redis.publish(
                _RULES_RELOAD_CHANNEL,
                json.dumps({"tenant_id": tenant_id, "ts": time.time()}),
            )
        except Exception as exc:
            logger.warning("rule_pubsub_failed", error=str(exc))
        logger.info("rule_engine_hot_reload", tenant_id=tenant_id)

    async def listen_reload(self) -> None:
        """订阅 frd:rules_reload，收到广播后失效本进程规则编译缓存。

        由 app lifespan 启动为后台协程；断线后指数退避重连，
        取消（应用关闭）时静默退出。
        """
        while True:
            pubsub = None
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(_RULES_RELOAD_CHANNEL)
                logger.info("rules_reload_subscribed", channel=_RULES_RELOAD_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    tenant_id = _parse_reload_message(message.get("data"))
                    removed = self.invalidate_cache(tenant_id)
                    logger.info(
                        "rules_cache_invalidated",
                        tenant_id=tenant_id,
                        keys_removed=removed,
                        source="pubsub",
                    )
            except asyncio.CancelledError:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()  # type: ignore[no-untyped-call]
                raise
            except Exception as exc:
                logger.warning("rules_reload_listener_retry", error=str(exc))
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()  # type: ignore[no-untyped-call]
                await asyncio.sleep(5)


def _parse_reload_message(data: Any) -> str | None:
    """解析 reload 消息中的 tenant_id；解析失败返回 None（全量失效）。"""
    try:
        payload = json.loads(data)
        tenant_id = payload.get("tenant_id")
        return str(tenant_id) if tenant_id else None
    except (TypeError, ValueError):
        return None


# 单例
rule_engine = RuleEngine()


__all__ = [
    "CompiledRule",
    "RuleEngine",
    "RuleHit",
    "RuleResult",
    "rule_engine",
]
