"""三模态推理单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from ml.scoring.modalities.behavior import BehaviorModality
from ml.scoring.modalities.structured import ModalityScore, StructuredModality
from ml.scoring.modalities.text import TextModality


@pytest.fixture
def structured() -> StructuredModality:
    return StructuredModality()


@pytest.fixture
def text() -> TextModality:
    return TextModality()


@pytest.fixture
def behavior() -> BehaviorModality:
    return BehaviorModality()


def test_structured_fallback_when_model_missing(structured: StructuredModality) -> None:
    """模型未加载 → fallback（默认 0.5）。"""
    result = asyncio.run(structured.predict({"amount": 100.0}, "t1"))
    assert result.fallback is True
    assert result.score == 0.5  # default_score
    assert result.modality == "structured"


def test_text_fallback_when_model_missing(text: TextModality) -> None:
    result = asyncio.run(text.predict("test text", "t1"))
    assert result.fallback is True
    assert result.score == 0.5
    assert result.modality == "text"


def test_text_fallback_when_empty(text: TextModality) -> None:
    result = asyncio.run(text.predict("", "t1"))
    assert result.fallback is True
    assert "empty_text" in (result.label or "")


def test_behavior_fallback_when_model_missing(behavior: BehaviorModality) -> None:
    result = asyncio.run(behavior.predict([[0.1, 0.2]], "t1"))
    assert result.fallback is True
    assert result.score == 0.5
    assert result.modality == "behavior"


def test_behavior_fallback_when_empty(behavior: BehaviorModality) -> None:
    result = asyncio.run(behavior.predict([], "t1"))
    assert result.fallback is True
    assert "empty_series" in (result.label or "")


def test_behavior_pad_or_truncate(behavior: BehaviorModality) -> None:
    """序列长度不足 → pad 到 seq_len。"""
    tensor = behavior._pad_or_truncate([[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]])
    # shape: (1, n_features, seq_len)
    assert tensor.shape[0] == 1
    assert tensor.shape[1] == behavior._n_features
    assert tensor.shape[2] == behavior._seq_len
