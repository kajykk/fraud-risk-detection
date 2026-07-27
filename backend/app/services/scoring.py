"""ScoringOrchestrator（D03 §4.1，200ms 预算双轨 + 三模态并行）。

同步评分主路径（必须 ≤ 200ms）：
1. Tokenization (5ms)
2. 并行评分 asyncio.gather (35ms)：
   ├── Rule Engine (10ms)
   └── ML Engine 三模态并行 (30ms + 5ms 融合)
3. 双轨决策融合 (5ms)
4. Redis 缓存写入 (3ms)
5. Kafka 异步发布 fire-and-forget (2ms)

不进主路径：
- DB 写入：Kafka Consumer 异步消费（ADR-014）
- SHAP 计算：异步 Worker + 缓存 24h（ADR-007）
- 案件生成：异步 Worker
- Webhook 回调：异步可靠推送
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.schemas.common import Decision, RiskBand
from app.services.kill_switch import KillSwitchScope, kill_switch
from app.services.ml_engine import ml_engine
from app.services.rule_engine import rule_engine
from app.services.tokenization import tokenization_service

logger = get_logger(__name__)


@dataclass
class ScoreResult:
    """评分结果。"""

    decision: Decision
    risk_score: float
    risk_band: RiskBand
    model_version: str
    rule_hits: list[dict[str, Any]] = field(default_factory=list)
    modality_scores: dict[str, Any] = field(default_factory=dict)
    explainability: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    decision_id: str = ""
    case_id: str | None = None
    cached: bool = False


class ScoringOrchestrator:
    """评分主路径编排器。"""

    def __init__(self) -> None:
        self.budget_ms = settings.scoring_p99_budget_ms

    async def score_sync(
        self,
        transaction: dict[str, Any],
        tenant_id: str,
    ) -> ScoreResult:
        """同步评分主路径（P99 ≤ 200ms）。

        步骤：
        1. Kill Switch 检查（L1 全局）
        2. Tokenization（5ms）
        3. 并行评分 asyncio.gather：Rule Engine || ML Engine（35ms）
        4. 双轨决策融合（5ms）
        5. Redis 缓存写入（3ms）
        6. Kafka 异步发布 fire-and-forget（2ms）
        """
        start = time.perf_counter()
        decision_id = f"dec_{uuid.uuid4()}"

        # 1. Kill Switch 检查（L1 全局）
        if await kill_switch.is_active(KillSwitchScope.L1_GLOBAL):
            logger.warning("kill_switch_global_active", tenant_id=tenant_id)
            # 启发式规则兜底（金额阈值）
            return self._heuristic_fallback(transaction, decision_id, start)

        # 2. Tokenization（如未提供 card_token）
        if not transaction.get("card_token") and transaction.get("card_pan"):
            token = await tokenization_service.tokenize(transaction["card_pan"])
            transaction["card_token"] = token

        # 3. 并行评分：Rule Engine || ML Engine
        rule_task = rule_engine.evaluate(transaction, tenant_id)
        ml_task = ml_engine.predict_parallel(
            features=transaction,
            text=transaction.get("note_text"),
            behavior=transaction.get("behavior_series"),
            tenant_id=tenant_id,
        )
        rule_result, ml_result = await asyncio.gather(rule_task, ml_task)

        # 4. 双轨决策融合
        decision, risk_score, risk_band = self._fuse_decisions(rule_result, ml_result)

        latency_ms = int((time.perf_counter() - start) * 1000)

        result = ScoreResult(
            decision=decision,
            risk_score=risk_score,
            risk_band=risk_band,
            model_version="ml_xgb_v3.2.1",  # TODO: 从 model registry 读取 ACTIVE 版本
            rule_hits=[{"rule_id": r.rule_id, "rule_name": r.rule_name, "severity": r.severity} for r in rule_result.hit_rules],
            modality_scores={
                "structured": ml_result.structured.score if ml_result.structured else None,
                "text": ml_result.text.score if ml_result.text else None,
                "behavior": ml_result.behavior.score if ml_result.behavior else None,
                "fused": ml_result.fused_score,
                "fallback_flags": ml_result.fallback_flags,
            },
            explainability={
                "model_contribution": 0.65,
                "rule_contribution": 0.35,
                "shap_status": "PENDING",
                "shap_task_id": f"shap_task_{uuid.uuid4()}",
            },
            latency_ms=latency_ms,
            decision_id=decision_id,
        )

        # 5. Redis 缓存写入（fire-and-forget）
        asyncio.create_task(self._cache_score(tenant_id, transaction.get("external_tx_id", ""), result))

        # 6. Kafka 异步发布（fire-and-forget，ADR-014）
        asyncio.create_task(self._publish_to_kafka(tenant_id, transaction, result))

        logger.info(
            "score_sync_completed",
            tenant_id=tenant_id,
            decision=result.decision.value,
            risk_score=result.risk_score,
            latency_ms=result.latency_ms,
        )
        return result

    def _fuse_decisions(self, rule_result: Any, ml_result: Any) -> tuple[Decision, float, RiskBand]:
        """双轨决策融合（D03 §4.1）。

        - 任一 DENY → DENY
        - 任一 CHALLENGE → CHALLENGE
        - 任一 REVIEW → REVIEW
        - 双 ALLOW → ALLOW
        """
        # ML 决策：根据 risk_score 阈值（基准 §3.5）
        risk_score = ml_result.fused_score
        if risk_score >= 0.85:
            ml_decision = Decision.DENY
        elif risk_score >= 0.60:
            ml_decision = Decision.REVIEW
        elif risk_score >= 0.30:
            ml_decision = Decision.REVIEW
        else:
            ml_decision = Decision.ALLOW

        # 规则决策
        rule_action = rule_result.action
        if rule_action == "BLOCK":
            rule_decision = Decision.DENY
        elif rule_action == "REVIEW":
            rule_decision = Decision.REVIEW
        else:
            rule_decision = Decision.ALLOW

        # 融合：取更严格的决策
        severity_order = {
            Decision.ALLOW: 0,
            Decision.REVIEW: 1,
            Decision.CHALLENGE: 2,
            Decision.DENY: 3,
        }
        fused_decision = max(
            [ml_decision, rule_decision],
            key=lambda d: severity_order[d],
        )

        risk_band = self._score_to_band(risk_score)
        return fused_decision, risk_score, risk_band

    def _score_to_band(self, score: float) -> RiskBand:
        """risk_score → risk_band（基准 §3.5）。"""
        if score < 0.30:
            return RiskBand.LOW
        if score < 0.60:
            return RiskBand.MEDIUM
        if score < 0.85:
            return RiskBand.HIGH
        return RiskBand.CRITICAL

    def _heuristic_fallback(
        self,
        transaction: dict[str, Any],
        decision_id: str,
        start: float,
    ) -> ScoreResult:
        """启发式兜底（Kill Switch 激活时，金额阈值规则）。"""
        amount = transaction.get("amount", 0)
        if amount > 1_000_000:  # 10000 元
            decision = Decision.DENY
            risk_score = 0.95
            risk_band = RiskBand.CRITICAL
        elif amount > 500_000:  # 5000 元
            decision = Decision.REVIEW
            risk_score = 0.55
            risk_band = RiskBand.MEDIUM
        else:
            decision = Decision.ALLOW
            risk_score = 0.15
            risk_band = RiskBand.LOW

        return ScoreResult(
            decision=decision,
            risk_score=risk_score,
            risk_band=risk_band,
            model_version="heuristic_v1",
            rule_hits=[{"rule_id": "HEURISTIC", "rule_name": "amount_threshold", "severity": "BLOCK"}],
            explainability={"model_contribution": 0.0, "rule_contribution": 1.0, "shap_status": "DISABLED"},
            latency_ms=int((time.perf_counter() - start) * 1000),
            decision_id=decision_id,
        )

    async def _cache_score(self, tenant_id: str, external_tx_id: str, result: ScoreResult) -> None:
        """Redis 缓存写入（score_cache:{tenant}:{tx_hash}，TTL 24h）。"""
        try:
            from app.db.redis import get_redis

            import json

            redis = get_redis()
            key = f"score_cache:{tenant_id}:{external_tx_id}"
            payload = {
                "decision": result.decision.value,
                "risk_score": result.risk_score,
                "risk_band": result.risk_band.value,
                "decision_id": result.decision_id,
                "model_version": result.model_version,
            }
            await redis.set(key, json.dumps(payload), ex=settings.scoring_cache_ttl_seconds)
        except Exception as exc:
            logger.warning("cache_score_failed", error=str(exc))

    async def _publish_to_kafka(
        self,
        tenant_id: str,
        transaction: dict[str, Any],
        result: ScoreResult,
    ) -> None:
        """Kafka 异步发布（fire-and-forget，ADR-014）。

        TODO: 接入 aiokafka Producer，发布到 frd.transactions / frd.decisions / frd.audit_log 三个 topic。
        骨架阶段仅 log。
        """
        logger.info(
            "kafka_publish_skeleton",
            tenant_id=tenant_id,
            topic=settings.kafka_topic_transactions,
            decision_id=result.decision_id,
            note="TODO: integrate aiokafka producer",
        )


# 单例
scoring_orchestrator = ScoringOrchestrator()


__all__ = ["ScoreResult", "ScoringOrchestrator", "scoring_orchestrator"]
