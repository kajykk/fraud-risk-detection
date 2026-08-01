"""行为时序模态推理（1D-CNN）。

对应 D03 §4.3：
    behavior → 1D-CNN + IsolationForest → score_behavior (P99 25ms)

输入：行为时序序列（点击流 / 输入节奏 / 滑动轨迹）
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


class BehaviorModality:
    """行为时序模态（1D-CNN）。

    使用 PyTorch 2.4 加载 1D-CNN 模型，对行为时序序列进行推理。
    模型结构：Conv1d × 3 + GlobalAvgPool + Linear(sigmoid)。
    """

    name = "behavior"

    def __init__(self) -> None:
        self._model: Any | None = None  # torch.nn.Module
        self._device: Any | None = None
        self._seq_len: int = 50  # 固定序列长度
        self._n_features: int = 8  # 每帧特征维度（点击/输入/滑动等）
        self._redis: Any | None = None

    async def load_model(self, redis_client: Any | None = None) -> None:
        """加载 1D-CNN 模型工件。"""
        self._redis = redis_client
        try:
            import torch  # type: ignore

            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = self._build_model()
            state = torch.load(
                settings.models.behavior_path, map_location=self._device, weights_only=True
            )
            model.load_state_dict(state)
            model.to(self._device)
            model.eval()
            self._model = model
            logger.info("behavior.model.loaded", path=settings.models.behavior_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("behavior.model.load_failed", error=str(exc))
            self._model = None

    def _build_model(self):
        """构建 1D-CNN 模型结构（与训练侧 train_behavior.py 保持一致）。"""
        import torch.nn as nn  # type: ignore

        class Behavior1DCNN(nn.Module):
            def __init__(self, in_channels: int, seq_len: int) -> None:
                super().__init__()
                self.conv1 = nn.Conv1d(in_channels, 32, kernel_size=3, padding=1)
                self.conv2 = nn.Conv1d(32, 64, kernel_size=3, padding=1)
                self.conv3 = nn.Conv1d(64, 128, kernel_size=3, padding=1)
                self.relu = nn.ReLU()
                self.pool = nn.AdaptiveAvgPool1d(1)
                self.fc = nn.Linear(128, 1)

            def forward(self, x):
                # x shape: (batch, in_channels, seq_len)
                import torch  # type: ignore

                x = self.relu(self.conv1(x))
                x = self.relu(self.conv2(x))
                x = self.relu(self.conv3(x))
                x = self.pool(x).squeeze(-1)
                return torch.sigmoid(self.fc(x))

        return Behavior1DCNN(self._n_features, self._seq_len)

    async def predict(
        self, series: list[list[float]], tenant_id: str
    ) -> ModalityScore:
        """1D-CNN 推理（线程池执行）。"""
        if self._model is None:
            return await self.fallback(tenant_id, reason="model_not_loaded")
        if not series:
            return await self.fallback(tenant_id, reason="empty_series")

        start = time.perf_counter()
        try:
            score = await asyncio.get_running_loop().run_in_executor(
                None, self._infer_sync, series
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ModalityScore(
                score=score,
                modality=self.name,
                latency_ms=latency_ms,
                label="fraud_proba",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("behavior.predict.failed", error=str(exc))
            return await self.fallback(tenant_id, reason="predict_exception")

    def _infer_sync(self, series: list[list[float]]) -> float:
        import torch  # type: ignore

        with torch.no_grad():
            tensor = self._pad_or_truncate(series).to(self._device)
            # shape: (1, n_features, seq_len)
            output = self._model(tensor)
            return float(output.squeeze().item())

    def _pad_or_truncate(self, series: list[list[float]]):
        import torch  # type: ignore

        # 转置为 (n_features, seq_len) 并 pad/truncate 到固定长度
        if len(series) >= self._seq_len:
            series = series[: self._seq_len]
        # 转置
        cols = list(zip(*series, strict=False)) if series else [[0.0] * self._n_features]
        while len(cols) < self._n_features:
            cols.append([0.0] * len(series))
        for i, col in enumerate(cols):
            if len(col) < self._seq_len:
                cols[i] = list(col) + [0.0] * (self._seq_len - len(col))
        import numpy as np

        arr = np.asarray(cols, dtype=np.float32)
        return torch.from_numpy(arr).unsqueeze(0)

    async def fallback(self, tenant_id: str, reason: str = "unknown") -> ModalityScore:
        score = await self._lookup_recent_score(tenant_id)
        logger.warning(
            "behavior.fallback.triggered",
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
            return settings.behavior.default_score
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            values = await self._redis.lrange(key, 0, settings.behavior.recent_scores_window - 1)
            if not values:
                return settings.behavior.default_score
            nums = [float(v) for v in values if v is not None]
            if not nums:
                return settings.behavior.default_score
            return sum(nums) / len(nums)
        except Exception as exc:  # noqa: BLE001
            logger.warning("behavior.history.read_failed", error=str(exc))
            return settings.behavior.default_score

    async def record_score(self, tenant_id: str, score: float) -> None:
        if self._redis is None:
            return
        try:
            key = (
                f"{settings.redis.modality_history_prefix}:"
                f"{tenant_id}:{self.name}:recent_scores"
            )
            await self._redis.rpush(key, float(score))
            await self._redis.ltrim(key, -settings.behavior.recent_scores_window, -1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("behavior.history.write_failed", error=str(exc))


__all__ = ["BehaviorModality"]
