"""三模态并行评分引擎测试（ADR-011）。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from ml.scoring.engine import MLScoringEngine, ModalityScores
from ml.scoring.modalities.structured import ModalityScore


class _FakeRedis:
    """最小可用 Redis mock（仅实现 LPUSH/LRANGE/LTRIM/GET/SET/PING/CLOSE）。"""

    def __init__(self) -> None:
        self._store: Dict[str, List[float]] = {}

    async def rpush(self, key: str, value: float) -> int:
        self._store.setdefault(key, []).append(float(value))
        return len(self._store[key])

    async def lrange(self, key: str, start: int, end: int) -> List[float]:
        values = self._store.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        values = self._store.get(key, [])
        if end == -1:
            end = len(values) - 1
        self._store[key] = values[start : end + 1]

    async def get(self, key: str) -> Any:
        return None

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def engine(fake_redis: _FakeRedis) -> MLScoringEngine:
    eng = MLScoringEngine()
    # 不调用 load（避免依赖真实模型文件），手动注入 redis
    eng._redis = fake_redis  # type: ignore[attr-defined]
    eng.structured._redis = fake_redis
    eng.text._redis = fake_redis
    eng.behavior._redis = fake_redis
    return eng


def test_predict_all_modality_fallback(engine: MLScoringEngine) -> None:
    """三模态模型未加载 → 全部走 fallback（默认 0.5）。"""
    result = asyncio.run(
        engine.predict(
            structured_features={"amount": 100.0},
            text_content="测试文本",
            behavior_series=[[0.1, 0.2]],
            tenant_id="tenant-test",
        )
    )
    assert isinstance(result, ModalityScores)
    assert result.structured.fallback is True
    assert result.text.fallback is True
    assert result.behavior.fallback is True
    assert result.all_fallback is True
    # 默认 0.5 → MEDIUM band
    assert 0.0 <= result.fused_score <= 1.0
    assert result.risk_band in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def test_fallback_flags_recorded(engine: MLScoringEngine) -> None:
    """fallback_flags 标注每个熔断模态。"""
    result = asyncio.run(
        engine.predict(
            structured_features={},
            text_content="",
            behavior_series=[],
            tenant_id="tenant-test",
        )
    )
    assert set(result.fallback_flags.keys()) == {"structured", "text", "behavior"}


def test_to_dict_serializable(engine: MLScoringEngine) -> None:
    """ModalityScores 可序列化为 dict（写入 scores.modality_scores JSONB）。"""
    result = asyncio.run(
        engine.predict(
            structured_features={"amount": 50.0},
            text_content="x",
            behavior_series=[[0.1]],
            tenant_id="t1",
        )
    )
    payload = result.to_dict()
    assert "fused_score" in payload
    assert "risk_band" in payload
    assert "fallback_flags" in payload


def test_modality_score_dataclass() -> None:
    """ModalityScore dataclass 默认值。"""
    s = ModalityScore(score=0.3, modality="structured", latency_ms=1.2)
    assert s.fallback is False
    assert s.label is None
    assert s.extra is None
