"""文本模态推理（BERT 金融微调）。

对应 D03 §4.3：
    text → BERT (金融微调) → score_text (P99 30ms)

输入：交易备注 / 申诉文本 / 对话内容
输出：ModalityScore(score, label, latency_ms)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from ..config import settings
from .structured import ModalityScore

logger = structlog.get_logger(__name__)


class TextModality:
    """文本模态（BERT 金融微调）。

    使用 Transformers 4.44 加载微调后的 BERT 模型，输出欺诈概率。
    推理在 thread executor 中执行避免阻塞事件循环。
    """

    name = "text"

    def __init__(self) -> None:
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None
        self._redis: Any | None = None

    async def load_model(self, redis_client: Any | None = None) -> None:
        """加载 BERT tokenizer + model。"""
        self._redis = redis_client
        try:
            import torch  # type: ignore
            from transformers import (  # type: ignore
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            path = settings.models.text_path
            self._tokenizer = AutoTokenizer.from_pretrained(path)
            self._model = AutoModelForSequenceClassification.from_pretrained(path)
            self._model.to(self._device)
            self._model.eval()
            logger.info("text.model.loaded", path=path, device=str(self._device))
        except Exception as exc:  # noqa: BLE001
            logger.error("text.model.load_failed", error=str(exc))
            self._model = None
            self._tokenizer = None

    async def predict(self, text: str, tenant_id: str) -> ModalityScore:
        """BERT 推理（线程池执行，避免阻塞 asyncio）。"""
        if self._model is None or self._tokenizer is None:
            return await self.fallback(tenant_id, reason="model_not_loaded")
        if not text or not text.strip():
            return await self.fallback(tenant_id, reason="empty_text")

        start = time.perf_counter()
        try:
            score = await asyncio.get_running_loop().run_in_executor(
                None, self._infer_sync, text
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ModalityScore(
                score=score,
                modality=self.name,
                latency_ms=latency_ms,
                label="fraud_proba",
            )
        except TimeoutError:
            return await self.fallback(tenant_id, reason="timeout")
        except Exception as exc:  # noqa: BLE001
            logger.warning("text.predict.failed", error=str(exc))
            return await self.fallback(tenant_id, reason="predict_exception")

    def _infer_sync(self, text: str) -> float:
        """同步 BERT 推理（在 thread executor 中调用）。"""
        import torch  # type: ignore

        with torch.no_grad():
            inputs = self._tokenizer(  # type: ignore[union-attr]
                text,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128,
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            outputs = self._model(**inputs)  # type: ignore[union-attr]
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)
            # 假设标签 1 = fraud
            return float(probs[0, -1].item())

    async def fallback(self, tenant_id: str, reason: str = "unknown") -> ModalityScore:
        score = await self._lookup_recent_score(tenant_id)
        logger.warning(
            "text.fallback.triggered",
            tenant_id=tenant_id,
            reason=reason,
            score=score,
        )
        return ModalityScore(
            score=score,
            modality=self.name,
            latency_ms=0.0,
            fallback=True,
            label=f"fallback:{reason}",
        )

    async def _lookup_recent_score(self, tenant_id: str) -> float:
        if self._redis is None:
            return settings.text.default_score
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            values = await self._redis.lrange(key, 0, settings.text.recent_scores_window - 1)
            if not values:
                return settings.text.default_score
            nums = [float(v) for v in values if v is not None]
            if not nums:
                return settings.text.default_score
            return sum(nums) / len(nums)
        except Exception as exc:  # noqa: BLE001
            logger.warning("text.history.read_failed", error=str(exc))
            return settings.text.default_score

    async def record_score(self, tenant_id: str, score: float) -> None:
        if self._redis is None:
            return
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            await self._redis.rpush(key, float(score))
            await self._redis.ltrim(key, -settings.text.recent_scores_window, -1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("text.history.write_failed", error=str(exc))


__all__ = ["TextModality"]
