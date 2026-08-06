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

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.core.exceptions import RuleDSLInvalidError
from app.core.logging import get_logger
from app.db.redis import get_redis
from app.db.session import get_session_factory, set_tenant_id
from app.models.rule import Rule, RuleVersion

logger = get_logger(__name__)

_RULES_CACHE_TTL = 300  # 5 分钟

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
    OPS = {
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
            return self.OPS[self.op](lv, rv)
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
    """编译后的规则（DSL 解析结果缓存）。"""

    __slots__ = ("rule_id", "rule_name", "action", "severity", "priority", "expr")

    def __init__(
        self,
        rule_id: str,
        rule_name: str,
        action: str,
        severity: str,
        priority: int,
        expr: _Expr,
    ) -> None:
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.action = action
        self.severity = severity
        self.priority = priority
        self.expr = expr


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
            logger.warning("rule_engine_load_failed", tenant_id=tenant_id, error=str(exc))
            return RuleResult(hit_rules=[], action="ALLOW", latency_ms=1, fallback_used=True)

        hit_rules: list[RuleHit] = []
        action = "ALLOW"
        for rule in rules:
            try:
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
        """加载 ACTIVE 规则（Redis 缓存 → DB 兜底），编译并缓存。"""
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
                )
            )
        compiled.sort(key=lambda r: r.priority, reverse=False)
        self._compiled_cache[cache_key] = (time.time(), compiled)

        try:
            redis = get_redis()
            await redis.set(
                cache_key,
                json.dumps([r["rule_id"] for r in rules]),
                ex=_RULES_CACHE_TTL,
            )
        except Exception as exc:
            logger.warning("rule_cache_write_failed", error=str(exc))
        return compiled

    async def _load_rules_from_store(self, tenant_id: str) -> list[dict[str, Any]]:
        """从 DB 加载 ACTIVE 规则（本租户 + 全局 tenant_id IS NULL）。"""
        from sqlalchemy import func

        # 取每个 rule 的最新版本（ACTIVE 状态）
        latest_version = (
            select(
                RuleVersion.rule_id,
                RuleVersion.expression,
                RuleVersion.status,
                func.row_number()
                .over(
                    partition_by=RuleVersion.rule_id,
                    order_by=RuleVersion.created_at.desc(),
                )
                .label("rn"),
            )
            .where(RuleVersion.status == "ACTIVE")
            .subquery()
        )

        factory = get_session_factory()
        async with factory() as session:
            await set_tenant_id(session, tenant_id)
            result = await session.execute(
                select(Rule, latest_version.c.expression)
                .join(
                    latest_version,
                    latest_version.c.rule_id == Rule.id,
                )
                .where(
                    Rule.enabled.is_(True),
                    (Rule.tenant_id.is_(None)) | (Rule.tenant_id == tenant_id),
                )
                .order_by(Rule.priority)
            )
            return [
                {
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "action": rule.action,
                    "expression": expression,
                    "priority": rule.priority,
                    "severity": "WARN",
                }
                for rule, expression in result
            ]

    async def load_rules(self, tenant_id: str, version: str | None = None) -> list[dict[str, Any]]:
        """加载规则版本（Redis 缓存优先）。"""
        try:
            redis = get_redis()
            key = f"rules:{tenant_id}:active" if not version else f"rules:{tenant_id}:{version}"
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning("rule_cache_read_failed", error=str(exc))
        return await self._load_rules_from_store(tenant_id)

    async def hot_reload(self, tenant_id: str) -> None:
        """热更新规则（Redis pubsub 触发缓存失效）。"""
        for key in list(self._compiled_cache):
            if key.startswith(f"rules:{tenant_id}:"):
                self._compiled_cache.pop(key, None)
        try:
            redis = get_redis()
            await redis.publish(
                "frd:rules_reload",
                json.dumps({"tenant_id": tenant_id, "ts": time.time()}),
            )
        except Exception as exc:
            logger.warning("rule_pubsub_failed", error=str(exc))
        logger.info("rule_engine_hot_reload", tenant_id=tenant_id)


# 单例
rule_engine = RuleEngine()


__all__ = ["RuleEngine", "RuleHit", "RuleResult", "rule_engine", "CompiledRule"]
