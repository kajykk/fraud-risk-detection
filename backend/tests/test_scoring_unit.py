"""ScoringOrchestrator 服务层单元测试（D03 §4.1 关键分支）。

覆盖：
- _score_to_band 阈值边界（0.30 / 0.60 / 0.85）
- _fuse_decisions 双轨融合取更严格决策
- _heuristic_fallback 金额三档启发式
- score_sync：Kill Switch L1 激活走兜底；PAN 缺 token 自动 Tokenization
- dispatch_followup_tasks：持久化失败跳过 / eager 内联不投递 / 高风险建案 /
  reject 决策 webhook 投递闭环 / 事件落库失败跳过投递
- _cache_score：正常写入 TTL 与 Redis 故障降级

外部依赖（DB/Redis/broker/规则引擎/ML 引擎/Tokenization）全部打桩。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

import app.services.scoring as scoring_module
from app.config import settings
from app.schemas.common import Decision, RiskBand
from app.services.kill_switch import KillSwitchScope
from app.services.ml_engine import ModalityScore, ModalityScores
from app.services.rule_engine import RuleHit, RuleResult
from app.services.scoring import ScoreResult
from app.services.scoring import scoring_orchestrator as orch
from app.workers.celery_app import celery_app

TENANT = "00000000-0000-0000-0000-000000000001"


def _ml(fused: float) -> ModalityScores:
    return ModalityScores(structured=ModalityScore(modality="structured", score=0.5), fused_score=fused)


def _result(decision: Decision = Decision.ALLOW) -> ScoreResult:
    return ScoreResult(
        decision=decision,
        risk_score=0.4,
        risk_band=RiskBand.MEDIUM,
        model_version="ml_xgb_v3.2.1",
        decision_id="dec_test",
    )


async def _kill_switch(active: bool):
    async def fake_is_active(scope: KillSwitchScope) -> bool:
        return active

    return fake_is_active


@contextmanager
def _broker_mode(enabled: bool) -> Iterator[None]:
    """临时切换 Celery eager 开关（测试环境默认 eager=True）。"""
    previous = celery_app.conf.task_always_eager
    celery_app.conf.update(task_always_eager=enabled)
    try:
        yield
    finally:
        celery_app.conf.update(task_always_eager=previous)


# --------------------------------------------------------------------------- #
# 风险分档与双轨融合（纯函数）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("score", "band"),
    [
        (0.0, RiskBand.LOW),
        (0.2999, RiskBand.LOW),
        (0.30, RiskBand.MEDIUM),
        (0.5999, RiskBand.MEDIUM),
        (0.60, RiskBand.HIGH),
        (0.8499, RiskBand.HIGH),
        (0.85, RiskBand.CRITICAL),
    ],
)
def test_score_to_band_boundaries(score: float, band: RiskBand) -> None:
    """分档阈值边界：0.30/0.60/0.85 归入更高档。"""
    assert orch._score_to_band(score) == band


@pytest.mark.parametrize(
    ("rule_action", "fused", "expected"),
    [
        ("ALLOW", 0.90, Decision.DENY),
        ("BLOCK", 0.10, Decision.DENY),
        ("REVIEW", 0.70, Decision.CHALLENGE),
        ("ALLOW", 0.45, Decision.REVIEW),
        ("ALLOW", 0.10, Decision.ALLOW),
    ],
)
def test_fuse_decisions_takes_stricter(rule_action: str, fused: float, expected: Decision) -> None:
    """融合取更严格档位：任一 DENY→DENY，CHALLENGE 严于 REVIEW，双 ALLOW 才放行。"""
    rule_result = RuleResult(action=rule_action)
    decision, risk_score, risk_band = orch._fuse_decisions(rule_result, _ml(fused))
    assert decision == expected
    assert risk_score == pytest.approx(fused)
    assert risk_band == orch._score_to_band(fused)


# --------------------------------------------------------------------------- #
# Kill Switch 启发式兜底
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("amount", "decision", "risk_score", "risk_band"),
    [
        (2_000_000, Decision.DENY, 0.95, RiskBand.CRITICAL),
        (600_000, Decision.REVIEW, 0.55, RiskBand.MEDIUM),
        (100, Decision.ALLOW, 0.15, RiskBand.LOW),
    ],
)
def test_heuristic_fallback_amount_tiers(
    amount: int, decision: Decision, risk_score: float, risk_band: RiskBand
) -> None:
    """金额三档：>100 万拒付 / >50 万人工审核 / 其余放行。"""
    result = orch._heuristic_fallback({"amount": amount}, "dec_x", 0.0)
    assert result.decision == decision
    assert result.risk_score == risk_score
    assert result.risk_band == risk_band
    assert result.model_version == "heuristic_v1"
    assert result.rule_hits[0]["rule_id"] == "HEURISTIC"
    assert result.explainability["shap_status"] == "DISABLED"


# --------------------------------------------------------------------------- #
# 主路径分支
# --------------------------------------------------------------------------- #
async def test_score_sync_kill_switch_active_uses_heuristic(monkeypatch) -> None:
    """L1 全局 Kill Switch 激活时短路返回启发式兜底结果。"""

    async def fake_is_active(scope: KillSwitchScope) -> bool:
        return True

    monkeypatch.setattr(scoring_module.kill_switch, "is_active", fake_is_active)
    result = await orch.score_sync({"external_tx_id": "T1", "amount": 2_000_000}, TENANT)
    assert result.decision == Decision.DENY
    assert result.model_version == "heuristic_v1"
    assert result.decision_id.startswith("dec_")
    assert result.latency_ms >= 0


async def test_score_sync_tokenizes_pan_when_card_token_missing(monkeypatch) -> None:
    """仅提供 PAN 时主路径先 Tokenization 再评分，且交易体被回填 token。"""
    tokenized: list[str] = []

    async def fake_is_active(scope: KillSwitchScope) -> bool:
        return False

    async def fake_rule(transaction: dict, tenant_id: str) -> RuleResult:
        return RuleResult(hit_rules=[RuleHit("R1", "big_amount", "REVIEW")], action="REVIEW")

    async def fake_ml(**kwargs: Any) -> ModalityScores:
        return _ml(0.40)

    async def fake_tokenize(pan: str) -> str:
        tokenized.append(pan)
        return "tok_card_generated"

    monkeypatch.setattr(scoring_module.kill_switch, "is_active", fake_is_active)
    monkeypatch.setattr(scoring_module.rule_engine, "evaluate", fake_rule)
    monkeypatch.setattr(scoring_module.ml_engine, "predict_parallel", fake_ml)
    monkeypatch.setattr(scoring_module.tokenization_service, "tokenize", fake_tokenize)

    transaction = {"external_tx_id": "T2", "amount": 100, "card_pan": "6222021234567890"}
    result = await orch.score_sync(transaction, TENANT)
    assert tokenized == ["6222021234567890"]
    assert transaction["card_token"] == "tok_card_generated"
    assert result.modality_scores["structured"] == 0.5
    assert result.explainability["shap_status"] == "PENDING"
    assert result.explainability["shap_task_id"].startswith("shap_task_")


# --------------------------------------------------------------------------- #
# 异步跟进任务投递
# --------------------------------------------------------------------------- #
def _patch_ws_publish(monkeypatch, published: list[dict]) -> None:
    async def fake_publish(tenant_id: str, event_type: str, data: dict, *, event_id: str | None = None) -> bool:
        published.append({"tenant_id": tenant_id, "event_type": event_type, "data": data})
        return True

    monkeypatch.setattr(scoring_module, "publish_ws_event", fake_publish)


def _recorder_send(sent: list[tuple[str, list]]):
    def fake_send(name: str, args: list | None = None, **kwargs: Any) -> None:
        sent.append((name, list(args or [])))

    return fake_send


async def test_dispatch_skips_all_when_transaction_not_persisted(monkeypatch) -> None:
    """持久化失败（transaction_id=None）时不发布任何事件/任务。"""
    published: list[dict] = []
    sent: list[tuple[str, list]] = []
    _patch_ws_publish(monkeypatch, published)
    monkeypatch.setattr(celery_app, "send_task", _recorder_send(sent))

    await orch.dispatch_followup_tasks(TENANT, {}, _result(), None, None, [])
    assert published == []
    assert sent == []


async def test_dispatch_eager_mode_publishes_ws_but_no_broker_task(monkeypatch) -> None:
    """eager 内联模式：WS 实时事件照发，Celery 任务不投递（由显式调用触发）。"""
    published: list[dict] = []
    sent: list[tuple[str, list]] = []
    _patch_ws_publish(monkeypatch, published)
    monkeypatch.setattr(celery_app, "send_task", _recorder_send(sent))

    with _broker_mode(True):
        await orch.dispatch_followup_tasks(TENANT, {"external_tx_id": "TX"}, _result(), "tx1", "s1", ["m1"])

    assert len(published) == 1
    assert published[0]["event_type"] == "transaction.analysis_completed"
    assert published[0]["data"]["transaction_id"] == "tx1"
    assert sent == []


async def test_dispatch_critical_risk_sends_case_and_shap_tasks(monkeypatch) -> None:
    """非 eager + CRITICAL：投递 scoring.generate_case 与 shap.compute 两个任务。"""
    published: list[dict] = []
    sent: list[tuple[str, list]] = []
    _patch_ws_publish(monkeypatch, published)
    monkeypatch.setattr(celery_app, "send_task", _recorder_send(sent))

    result = _result()
    result.risk_band = RiskBand.CRITICAL
    with _broker_mode(False):
        await orch.dispatch_followup_tasks(
            TENANT, {"external_tx_id": "TX9", "amount": 900_000, "note_text": "sus"}, result, "tx9", "s9", []
        )

    by_name = dict(sent)
    assert set(by_name) == {"scoring.generate_case", "shap.compute"}
    assert by_name["scoring.generate_case"][0] == TENANT
    assert by_name["scoring.generate_case"][1] == "tx9"
    assert by_name["scoring.generate_case"][2]["risk_band"] == "CRITICAL"
    assert by_name["shap.compute"][2] == "s9"
    assert by_name["shap.compute"][4] == "ml_xgb_v3.2.1"
    assert len(published) == 1


async def test_dispatch_deny_decision_delivers_webhook_per_merchant(monkeypatch) -> None:
    """DENY + 已配置 webhook 的 ACTIVE 商户：逐商户落事件并调度 webhook.deliver。"""
    stored: list[dict] = []
    sent: list[tuple[str, list]] = []

    async def fake_store(*, tenant_id: str, event_type: str, data: dict, webhook_id: str) -> str:
        stored.append({"tenant_id": tenant_id, "event_type": event_type, "webhook_id": webhook_id})
        return f"evt_{webhook_id}"

    _patch_ws_publish(monkeypatch, [])
    monkeypatch.setattr(scoring_module, "store_webhook_event", fake_store)
    monkeypatch.setattr(celery_app, "send_task", _recorder_send(sent))

    result = _result(decision=Decision.DENY)
    result.risk_band = RiskBand.LOW
    with _broker_mode(False):
        await orch.dispatch_followup_tasks(TENANT, {"external_tx_id": "TX8"}, result, "tx8", "s8", ["m1", "m2"])

    assert [s["event_type"] for s in stored] == ["transaction.rejected", "transaction.rejected"]
    deliveries = [args for name, args in sent if name == "webhook.deliver"]
    assert deliveries == [["evt_m1", "m1"], ["evt_m2", "m2"]]
    assert "shap.compute" in {name for name, _ in sent}


async def test_dispatch_webhook_store_failure_skips_delivery_task(monkeypatch) -> None:
    """事件落库失败（返回 None）时跳过对应商户的投递任务，其余任务不受影响。"""
    sent: list[tuple[str, list]] = []

    async def fake_store(**kwargs: Any) -> None:
        return None

    _patch_ws_publish(monkeypatch, [])
    monkeypatch.setattr(scoring_module, "store_webhook_event", fake_store)
    monkeypatch.setattr(celery_app, "send_task", _recorder_send(sent))

    result = _result(decision=Decision.REVIEW)
    result.risk_band = RiskBand.LOW
    with _broker_mode(False):
        await orch.dispatch_followup_tasks(TENANT, {"external_tx_id": "TX7"}, result, "tx7", "s7", ["m1"])

    assert not [name for name, _ in sent if name == "webhook.deliver"]
    assert "shap.compute" in {name for name, _ in sent}


# --------------------------------------------------------------------------- #
# Redis 缓存写入
# --------------------------------------------------------------------------- #
class _FakeRedis:
    def __init__(self) -> None:
        self.sets: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append((key, value, ex))


async def test_cache_score_writes_json_payload_with_ttl(monkeypatch) -> None:
    """缓存键为 score_cache:{tenant}:{tx}，载荷含决策五元组，TTL 来自配置。"""
    redis = _FakeRedis()
    monkeypatch.setattr("app.db.redis.get_redis", lambda: redis)

    await orch._cache_score(TENANT, "tx_cache_1", _result())

    key, value, ttl = redis.sets[0]
    assert key == f"score_cache:{TENANT}:tx_cache_1"
    payload = json.loads(value)
    assert payload == {
        "decision": "ALLOW",
        "risk_score": 0.4,
        "risk_band": "MEDIUM",
        "decision_id": "dec_test",
        "model_version": "ml_xgb_v3.2.1",
    }
    assert ttl == settings.scoring_cache_ttl_seconds


async def test_cache_score_redis_failure_does_not_raise(monkeypatch) -> None:
    """Redis 故障时缓存写入静默降级，不影响评分响应。"""

    def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.db.redis.get_redis", boom)
    await orch._cache_score(TENANT, "tx_cache_1", _result())
