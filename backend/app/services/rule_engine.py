"""RuleEngine（D03 §4.2）。

- DSL 解析 + 匹配
- 规则版本加载（Redis 缓存，按 tenant_id 分片）
- 热更新（Redis pubsub）
- 短路求值（按优先级）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


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
    """规则引擎（DSL 解析 + 匹配）。

    D03 §4.1 200ms 预算：Rule Engine P99 ≤ 10ms。
    """

    async def evaluate(
        self,
        transaction: dict[str, Any],
        tenant_id: str,
    ) -> RuleResult:
        """评估交易命中哪些规则。

        TODO（M2 实现）：
        1. 从 Redis 加载规则版本（key: rules:{tenant_id}:active）
        2. CEL 编译 DSL（缓存编译结果）
        3. 短路求值（按 priority 排序）
        4. 任一 BLOCK 即 BLOCK；任一 REVIEW 即 REVIEW
        """
        logger.info("rule_engine_evaluate", tenant_id=tenant_id, external_tx_id=transaction.get("external_tx_id"))
        # 骨架：无规则命中，返回 ALLOW
        return RuleResult(hit_rules=[], action="ALLOW", latency_ms=1, fallback_used=False)

    async def load_rules(self, tenant_id: str, version: str | None = None) -> list[dict[str, Any]]:
        """加载规则版本（Redis 缓存）。

        TODO: 从 Redis 读取 rules:{tenant_id}:{version}；缓存未命中查 DB。
        """
        return []

    async def hot_reload(self, tenant_id: str) -> None:
        """热更新规则（Redis pubsub 触发）。"""
        logger.info("rule_engine_hot_reload", tenant_id=tenant_id)


# 单例
rule_engine = RuleEngine()


__all__ = ["RuleEngine", "RuleHit", "RuleResult", "rule_engine"]
