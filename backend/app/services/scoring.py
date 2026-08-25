"""ScoringOrchestrator（D03 §4.1，200ms 预算双轨 + 三模态并行）。

同步评分主路径（必须 ≤ 200ms）：
1. Tokenization (5ms)
2. 并行评分 asyncio.gather (35ms)：
   ├── Rule Engine (10ms)
   └── ML Engine 三模态并行 (30ms + 5ms 融合)
3. 双轨决策融合 (5ms)
4. Redis 缓存写入 (3ms)

持久化与事件外发（ADR-014 演进 / ADR-016 决策）：
- DB 写入在主路径内 await（保证数据可追溯，无外部 MQ 依赖）
- SHAP 计算：异步 Worker + 缓存 24h（ADR-007）
- 案件生成：异步 Worker
- Webhook 回调：异步可靠推送
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.schemas.common import Decision, RiskBand
from app.services.kill_switch import KillSwitchScope, kill_switch
from app.services.ml_engine import ml_engine
from app.services.rule_engine import rule_engine
from app.services.tokenization import tokenization_service
from app.services.webhook import store_webhook_event
from app.services.ws_events import publish_ws_event

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

        # 5. DB 持久化（等待完成，保证评分可追溯；失败不阻断响应，内部已 catch）
        transaction_id, score_id, webhook_merchant_ids = await self._persist_to_db(
            tenant_id, transaction, result
        )

        # 5.1 异步跟进任务（评分持久化后条件投递，ADR-014）：
        #     高风险（HIGH/CRITICAL）→ scoring.generate_case 自动建案；
        #     全部 → shap.compute 异步解释；reject/manual_review 决策 →
        #     webhook.deliver 事件投递。fire-and-forget，不阻塞响应。
        await self.dispatch_followup_tasks(
            tenant_id, transaction, result, transaction_id, score_id, webhook_merchant_ids
        )

        # 6. Redis 缓存写入（等待完成；失败降级为仅响应，内部已 catch）
        await self._cache_score(tenant_id, transaction.get("external_tx_id", ""), result)

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
            ml_decision = Decision.CHALLENGE
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

    async def _persist_to_db(
        self,
        tenant_id: str,
        transaction: dict[str, Any],
        result: ScoreResult,
    ) -> tuple[str | None, str | None, list[str]]:
        """持久化交易 + 评分到 PostgreSQL（失败不阻断主路径）。

        直接在评分主进程内 await 写入，不依赖外部消息队列
        （ADR-016：MQ 外发延后）。

        Returns:
            (transaction_id, score_id, webhook_merchant_ids)；
            webhook_merchant_ids 为该租户已配置 ACTIVE webhook 的商户 ID
            （供 reject/manual_review 决策构造事件投递）；
            持久化失败时返回 (None, None, [])。
        """
        try:
            from datetime import datetime
            from decimal import Decimal

            from sqlalchemy import select

            from app.db.session import session_scope
            from app.models.tenant import Merchant
            from app.models.transaction import Score, Transaction

            async with session_scope(tenant_id) as session:
                # 1. 写入交易记录
                occurred_at_str = transaction.get("occurred_at", "")
                if occurred_at_str:
                    occurred_at = datetime.fromisoformat(occurred_at_str.replace("Z", "+00:00"))
                else:
                    occurred_at = datetime.now(UTC)

                tx = Transaction(
                    tenant_id=uuid.UUID(tenant_id),
                    external_tx_id=transaction.get("external_tx_id", str(uuid.uuid4())),
                    card_token=transaction.get("card_token", "tok_unknown"),
                    card_bin=transaction.get("card_bin", "000000"),
                    card_last4=transaction.get("card_last4", "0000"),
                    amount=int(transaction.get("amount", 0)),
                    currency=transaction.get("currency", "CNY"),
                    tx_type=transaction.get("tx_type"),
                    channel=transaction.get("channel"),
                    is_3ds_verified=transaction.get("is_3ds_verified", False),
                    merchant_category=transaction.get("merchant_category"),
                    user_account_id=transaction.get("user_id"),
                    note_text=transaction.get("note_text"),
                    risk_features={},
                    occurred_at=occurred_at,
                    received_at=datetime.now(UTC),
                    metadata_={
                        "amount": transaction.get("amount", 0),
                        "currency": transaction.get("currency", "CNY"),
                        "merchant_id": transaction.get("merchant_id"),
                    },
                )
                session.add(tx)
                await session.flush()  # 获取 tx.id

                # 2. 写入评分记录
                score = Score(
                    tenant_id=uuid.UUID(tenant_id),
                    transaction_id=tx.id,
                    model_version=result.model_version,
                    rule_version="rule_v1",
                    risk_score=Decimal(str(result.risk_score)),
                    risk_band=result.risk_band.value,
                    decision=result.decision.value,
                    rule_hits=result.rule_hits,
                    modality_scores=result.modality_scores,
                    feature_values={},
                    cached=result.cached,
                    latency_ms=result.latency_ms,
                )
                session.add(score)
                # session_scope 退出时统一 commit

                logger.info(
                    "db_persist_ok",
                    tenant_id=tenant_id,
                    transaction_id=str(tx.id),
                    external_tx_id=tx.external_tx_id,
                    decision=result.decision.value,
                )
                # 已配置 ACTIVE webhook 的商户（同 session 内查询，热路径仅一次索引查询）
                webhook_rows = await session.execute(
                    select(Merchant.id).where(
                        Merchant.tenant_id == uuid.UUID(tenant_id),
                        Merchant.webhook_url.isnot(None),
                        Merchant.status == "ACTIVE",
                    )
                )
                webhook_merchant_ids = [str(m) for m in webhook_rows.scalars().all()]
                return str(tx.id), str(score.id), webhook_merchant_ids
        except Exception as exc:
            logger.warning("db_persist_failed", error=str(exc), tenant_id=tenant_id)
            return None, None, []

    async def dispatch_followup_tasks(
        self,
        tenant_id: str,
        transaction: dict[str, Any],
        result: ScoreResult,
        transaction_id: str | None,
        score_id: str | None,
        webhook_merchant_ids: list[str] | None = None,
    ) -> None:
        """评分持久化后的异步跟进任务投递（fire-and-forget）。

        - risk_band ∈ {HIGH, CRITICAL} → scoring.generate_case（自动建案）
        - 全部评分 → shap.compute（异步 SHAP 解释，结果缓存 24h）
        - decision ∈ {DENY, REVIEW} → 构造 webhook_event 并按商户投递
          webhook.deliver（reject / manual_review 事件，D05 §11）
        - 全部评分 → frd:ws_events 发布 transaction.analysis_completed（实时推送）

        按名 send_task 投递到 Celery broker；eager 模式（测试/单机内联）
        或持久化失败（无主键）时不投递；broker 异常仅告警不阻断评分响应。
        """
        if transaction_id is None:
            return

        # WS 实时推送：评分分析完成（不依赖 broker，失败内部吞掉）
        await publish_ws_event(
            tenant_id,
            "transaction.analysis_completed",
            {
                "decision_id": result.decision_id,
                "external_tx_id": transaction.get("external_tx_id"),
                "decision": result.decision.value,
                "risk_score": result.risk_score,
                "risk_band": result.risk_band.value,
                "transaction_id": transaction_id,
            },
        )

        try:
            from app.workers.celery_app import celery_app

            if celery_app.conf.task_always_eager:
                # 内联模式（测试/单机）：任务由显式调用触发，不走 broker 投递
                return

            if result.risk_band in (RiskBand.HIGH, RiskBand.CRITICAL):
                self._send_task_safe(
                    celery_app,
                    "scoring.generate_case",
                    args=[
                        tenant_id,
                        transaction_id,
                        {
                            "score_id": score_id,
                            "risk_band": result.risk_band.value,
                            "amount": transaction.get("amount", 0),
                            "description": transaction.get("note_text"),
                        },
                    ],
                )
            self._send_task_safe(
                celery_app,
                "shap.compute",
                args=[
                    tenant_id,
                    result.decision_id,
                    score_id or "",
                    {**transaction, "risk_score": result.risk_score},
                    result.model_version,
                ],
            )
            # Webhook 投递闭环：reject/manual_review 决策 → 每个配置 webhook
            # 的 ACTIVE 商户构造一条事件并调度投递任务
            if (
                result.decision in (Decision.DENY, Decision.REVIEW)
                and webhook_merchant_ids
            ):
                event_type = (
                    "transaction.rejected"
                    if result.decision == Decision.DENY
                    else "transaction.manual_review"
                )
                payload = {
                    "decision_id": result.decision_id,
                    "transaction_id": transaction_id,
                    "external_tx_id": transaction.get("external_tx_id"),
                    "amount": transaction.get("amount", 0),
                    "currency": transaction.get("currency", "CNY"),
                    "risk_score": result.risk_score,
                    "risk_band": result.risk_band.value,
                    "rule_hits": result.rule_hits,
                }
                for merchant_id in webhook_merchant_ids:
                    event_id = await store_webhook_event(
                        tenant_id=tenant_id,
                        event_type=event_type,
                        data=payload,
                        webhook_id=merchant_id,
                    )
                    if event_id is None:
                        continue
                    self._send_task_safe(
                        celery_app,
                        "webhook.deliver",
                        args=[event_id, merchant_id],
                    )
        except Exception as exc:
            logger.warning("followup_tasks_dispatch_failed", error=str(exc))

    @staticmethod
    def _send_task_safe(celery_app: Any, name: str, args: list[Any]) -> None:
        """按名投递 Celery 任务；broker 不可用时仅告警。"""
        try:
            celery_app.send_task(name, args=args)
        except Exception as exc:
            logger.warning("celery_send_task_failed", task=name, error=str(exc))

    async def _cache_score(self, tenant_id: str, external_tx_id: str, result: ScoreResult) -> None:
        """Redis 缓存写入（score_cache:{tenant}:{tx_hash}，TTL 24h）。"""
        try:
            import json

            from app.db.redis import get_redis

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


# 单例
scoring_orchestrator = ScoringOrchestrator()


__all__ = ["ScoreResult", "ScoringOrchestrator", "scoring_orchestrator"]
