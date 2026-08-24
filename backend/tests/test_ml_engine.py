"""MLScoringEngine 远程推理（ml-serving :8501）与启发式回退单元测试。

覆盖：
- auto 模式远程成功：响应契约映射（分数/fallback_flags/SHAP 透传）、
  X-Api-Key 头、请求体字段与行为序列包装
- 远程超时 / HTTP 5xx / 响应畸形：回退本地启发式并记录 warning
- heuristic 模式：完全不发起网络请求
- 轻量熔断器：连续失败打开 → 冷却期内跳过远程 → 半开恢复探测
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import app.services.ml_engine as ml_engine_module
from app.config import settings
from app.services.ml_engine import MLScoringEngine

REMOTE_SCORE_RESPONSE: dict[str, Any] = {
    "transaction_id": "TX20260727000001",
    "risk_score": 0.42,
    "risk_band": "MEDIUM",
    "modality_scores": {
        "structured": {"score": 0.32, "latency_ms": 18.5, "fallback": False, "label": "xgb_v1"},
        "text": {"score": 0.71, "latency_ms": 28.2, "fallback": False, "label": "bert_v1"},
        "behavior": {
            "score": 0.45,
            "latency_ms": 0.0,
            "fallback": True,
            "label": "fallback:timeout",
        },
        "fused_score": 0.42,
        "risk_band": "MEDIUM",
        "latency_ms": 31.0,
        "fallback_flags": {"behavior": "timeout"},
        "all_fallback": False,
    },
    "latency_ms": 33.4,
    "fallback_flags": {"behavior": "timeout"},
    "all_fallback": False,
}


class _LogRecorder:
    """structlog logger 替身，记录事件名用于断言 warning。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def warning(self, event: str, **_: Any) -> None:
        self.events.append(("warning", event))

    def info(self, event: str, **_: Any) -> None:
        self.events.append(("info", event))

    def error(self, event: str, **_: Any) -> None:
        self.events.append(("error", event))


def _make_handler(
    log: list[httpx.Request],
    *,
    payload: dict[str, Any] | None = None,
    status: int = 200,
    exc: Exception | None = None,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if exc is not None:
            raise exc
        return httpx.Response(status, json=payload if payload is not None else {})

    return handler


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ml_engine_module, "_build_http_client", _factory)


@pytest.fixture(autouse=True)
def _spy_logger(monkeypatch: pytest.MonkeyPatch) -> _LogRecorder:
    rec = _LogRecorder()
    monkeypatch.setattr(ml_engine_module, "logger", rec)
    return rec


@pytest.fixture(autouse=True)
def _default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ml_engine_mode", "auto")
    monkeypatch.setattr(settings, "ml_service_url", "http://ml-serving-test:8501")
    monkeypatch.setattr(settings, "ml_api_key", "")


async def test_build_http_client_uses_configured_timeouts() -> None:
    async with ml_engine_module._build_http_client() as client:
        assert client.timeout.connect == settings.ml_connect_timeout_seconds
        assert client.timeout.read == settings.ml_read_timeout_seconds


async def test_remote_success_maps_response_contract(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []
    payload = {**REMOTE_SCORE_RESPONSE, "shap": {"base_value": 0.1, "features": []}}
    _patch_transport(monkeypatch, _make_handler(log, payload=payload))
    monkeypatch.setattr(settings, "ml_api_key", "secret-key")

    engine = MLScoringEngine()
    result = await engine.predict_parallel(
        features={"external_tx_id": "TX20260727000001", "amount": 100},
        text="备注",
        behavior=[0.1, 0.9],
        tenant_id="tenant-a",
    )

    # 网络层：URL、鉴权头、请求体契约
    assert len(log) == 1
    request = log[0]
    assert str(request.url).endswith("/v1/score")
    assert request.headers["X-Api-Key"] == "secret-key"
    body = json.loads(request.content)
    assert body["tenant_id"] == "tenant-a"
    assert body["transaction_id"] == "TX20260727000001"
    assert body["text_content"] == "备注"
    assert body["structured_features"]["amount"] == 100
    # 扁平序列被包装为服务端要求的 list[list[float]]
    assert body["behavior_series"] == [[0.1], [0.9]]

    # 契约映射：分数结构类型不变
    assert result.fused_score == pytest.approx(0.42)
    assert result.structured is not None and result.structured.score == pytest.approx(0.32)
    assert result.text is not None and result.text.score == pytest.approx(0.71)
    assert result.behavior is not None
    assert result.behavior.score == pytest.approx(0.45)
    assert result.behavior.fallback_used is True
    assert isinstance(result.fallback_flags, dict)
    assert result.fallback_flags == {
        "structured": False,
        "text": False,
        "behavior": True,
    }
    assert result.total_latency_ms == pytest.approx(33)
    # SHAP 贡献远程返回则透传
    assert result.shap_contributions == {"base_value": 0.1, "features": []}
    assert ("warning", "ml_remote_failed_fallback_heuristic") not in _spy_logger.events


async def test_remote_timeout_falls_back_to_heuristic(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []

    def _factory() -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            log.append(request)
            raise httpx.ReadTimeout("read timed out", request=request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ml_engine_module, "_build_http_client", _factory)

    engine = MLScoringEngine()
    result = await engine.predict_parallel(
        features={"amount": 600000},
        text=None,
        behavior=None,
        tenant_id="tenant-b",
    )

    # 回退本地启发式：金额 > 500000 → structured 0.65；无文本/序列 → 0.3
    assert len(log) == 1
    assert result.structured is not None and result.structured.score == pytest.approx(0.65)
    assert result.text is not None and result.text.score == pytest.approx(0.3)
    assert result.behavior is not None and result.behavior.score == pytest.approx(0.3)
    assert result.shap_contributions is None
    # 加权融合：0.65*0.6 + 0.3*0.2 + 0.3*0.2 = 0.51
    assert result.fused_score == pytest.approx(0.51)
    assert ("warning", "ml_remote_failed_fallback_heuristic") in _spy_logger.events


async def test_remote_http_error_falls_back_to_heuristic(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []
    _patch_transport(monkeypatch, _make_handler(log, status=500))

    engine = MLScoringEngine()
    result = await engine.predict_parallel(
        features={"amount": 100},
        text="转账备注",
        behavior=[1.0],
        tenant_id="tenant-c",
    )

    assert len(log) == 1
    assert result.structured is not None and result.structured.score == pytest.approx(0.15)
    assert result.text is not None and result.text.score == pytest.approx(0.4)
    assert result.behavior is not None and result.behavior.score == pytest.approx(0.35)
    assert result.shap_contributions is None
    assert ("warning", "ml_remote_failed_fallback_heuristic") in _spy_logger.events


async def test_malformed_remote_response_falls_back_to_heuristic(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []
    _patch_transport(monkeypatch, _make_handler(log, payload={"unexpected": True}))

    engine = MLScoringEngine()
    result = await engine.predict_parallel(
        features={"amount": 100},
        text=None,
        behavior=None,
        tenant_id="tenant-d",
    )

    assert len(log) == 1
    assert result.structured is not None and result.structured.score == pytest.approx(0.15)
    assert result.fused_score == pytest.approx(0.15 * 0.6 + 0.3 * 0.2 + 0.3 * 0.2)
    assert ("warning", "ml_remote_failed_fallback_heuristic") in _spy_logger.events


async def test_heuristic_mode_skips_network(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []
    _patch_transport(monkeypatch, _make_handler(log, payload=REMOTE_SCORE_RESPONSE))
    monkeypatch.setattr(settings, "ml_engine_mode", "heuristic")

    engine = MLScoringEngine()
    result = await engine.predict_parallel(
        features={"amount": 600000},
        text=None,
        behavior=None,
        tenant_id="tenant-e",
    )

    assert log == []
    assert result.structured is not None and result.structured.score == pytest.approx(0.65)
    assert result.fused_score == pytest.approx(0.51)
    assert not any(e[1] == "ml_remote_failed_fallback_heuristic" for e in _spy_logger.events)


async def test_circuit_breaker_opens_then_half_open_recovers(
    monkeypatch: pytest.MonkeyPatch, _spy_logger: _LogRecorder
) -> None:
    log: list[httpx.Request] = []
    _patch_transport(monkeypatch, _make_handler(log, status=503))
    monkeypatch.setattr(settings, "ml_breaker_failure_threshold", 2)
    monkeypatch.setattr(settings, "ml_breaker_recovery_seconds", 3600.0)

    engine = MLScoringEngine()

    for _ in range(2):
        await engine.predict_parallel(
            features={"amount": 100}, text=None, behavior=None, tenant_id="tenant-f"
        )
    assert len(log) == 2
    assert engine._breaker.is_open is True

    # 冷却期内：直接走启发式，不再发起网络请求
    result = await engine.predict_parallel(
        features={"amount": 100}, text=None, behavior=None, tenant_id="tenant-f"
    )
    assert len(log) == 2
    assert result.structured is not None and result.structured.score == pytest.approx(0.15)
    assert any(e[1] == "ml_remote_circuit_open_skip" for e in _spy_logger.events)

    # 半开：冷却期满放行一次探测（仍失败则保持打开）
    engine._breaker.opened_at -= 3601.0
    assert engine._breaker.is_open is False
    await engine.predict_parallel(
        features={"amount": 100}, text=None, behavior=None, tenant_id="tenant-f"
    )
    assert len(log) == 3
