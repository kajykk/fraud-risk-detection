"""SHAP Top5 解释器（ADR-007）。

D03 §4.1 / §5.2 明确：
- SHAP 异步计算 + 缓存 24h
- 不进主路径（200ms 预算）
- TreeExplainer（XGBoost）+ DeepExplainer（PyTorch）

输出 Top5 因子列表，存入 PostgreSQL shap_explanations 表（D04 §3.2）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog

from .config import settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ShapFactor:
    """单个 SHAP 因子。"""

    feature: str
    value: float
    shap_value: float  # 贡献度（可正可负）


@dataclass(frozen=True)
class ShapExplanation:
    """SHAP Top5 解释结果。"""

    prediction_id: str
    factors: List[ShapFactor]
    base_value: float
    output_value: float
    model_version: str
    computed_at: float  # epoch seconds
    cached: bool = False


class ShapExplainer:
    """SHAP 解释器（异步 + 24h Redis 缓存）。

    使用策略：
    - 结构化（XGBoost）→ TreeExplainer
    - 文本/行为（PyTorch）→ DeepExplainer
    - 缓存 key: shap:{model_version}:{prediction_hash}, TTL 24h
    """

    def __init__(self) -> None:
        self._redis: Optional[Any] = None
        self._tree_explainer: Optional[Any] = None  # shap.TreeExplainer
        self._deep_explainer: Optional[Any] = None  # shap.DeepExplainer
        self._model_version: str = "v1.0.0"

    async def init_redis(self, redis_client: Any) -> None:
        self._redis = redis_client

    def attach_tree_model(self, model: Any, model_version: str = "v1.0.0") -> None:
        """绑定 XGBoost 模型并构造 TreeExplainer。"""
        try:
            import shap  # type: ignore

            self._tree_explainer = shap.TreeExplainer(model)
            self._model_version = model_version
            logger.info("shap.tree_explainer.ready", model_version=model_version)
        except Exception as exc:  # noqa: BLE001
            logger.error("shap.tree_explainer.init_failed", error=str(exc))
            self._tree_explainer = None

    def attach_deep_model(self, model: Any, background: Any, model_version: str = "v1.0.0") -> None:
        """绑定 PyTorch 模型并构造 DeepExplainer。"""
        try:
            import shap  # type: ignore

            self._deep_explainer = shap.DeepExplainer(model, background)
            self._model_version = model_version
            logger.info("shap.deep_explainer.ready", model_version=model_version)
        except Exception as exc:  # noqa: BLE001
            logger.error("shap.deep_explainer.init_failed", error=str(exc))
            self._deep_explainer = None

    async def explain(
        self,
        prediction_id: str,
        features: Dict[str, Any],
        feature_vector: Optional[List[float]] = None,
        feature_names: Optional[List[str]] = None,
    ) -> Optional[ShapExplanation]:
        """计算 Top5 SHAP 因子（异步执行，先查缓存）。"""
        cache_key = self._cache_key(prediction_id, features)
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached

        if self._tree_explainer is None or feature_vector is None:
            logger.warning(
                "shap.explain.skipped",
                reason="tree_explainer_not_ready",
                prediction_id=prediction_id,
            )
            return None

        start = time.perf_counter()
        try:
            factors, base_value, output_value = await asyncio.get_running_loop().run_in_executor(
                None,
                self._explain_tree_sync,
                feature_vector,
                feature_names,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("shap.explain.failed", error=str(exc), prediction_id=prediction_id)
            return None

        latency_ms = (time.perf_counter() - start) * 1000.0
        explanation = ShapExplanation(
            prediction_id=prediction_id,
            factors=factors[:5],
            base_value=base_value,
            output_value=output_value,
            model_version=self._model_version,
            computed_at=time.time(),
            cached=False,
        )
        await self._write_cache(cache_key, explanation)
        logger.info(
            "shap.explain.done",
            prediction_id=prediction_id,
            latency_ms=latency_ms,
            n_factors=len(factors),
        )
        return explanation

    def _explain_tree_sync(
        self,
        feature_vector: List[float],
        feature_names: Optional[List[str]] = None,
    ) -> tuple[List[ShapFactor], float, float]:
        """同步 TreeExplainer 计算（在 thread executor 中执行）。"""
        import numpy as np  # type: ignore

        arr = np.asarray([feature_vector], dtype=np.float32)
        shap_values = self._tree_explainer.shap_values(arr)  # type: ignore[union-attr]
        # 兼容二分类返回 list[2] 的情况
        if isinstance(shap_values, list):
            shap_values = shap_values[-1]
        shap_values = shap_values[0]  # 取首条样本

        names = feature_names or [f"f{i}" for i in range(len(feature_vector))]
        base_value = float(self._tree_explainer.expected_value)  # type: ignore[union-attr]
        if isinstance(base_value, list):
            base_value = float(base_value[-1])
        output_value = base_value + float(sum(shap_values))

        factors = [
            ShapFactor(feature=str(names[i]), value=float(feature_vector[i]), shap_value=float(sv))
            for i, sv in enumerate(shap_values)
        ]
        factors.sort(key=lambda f: abs(f.shap_value), reverse=True)
        return factors, base_value, output_value

    def _cache_key(self, prediction_id: str, features: Dict[str, Any]) -> str:
        payload = json.dumps({"pid": prediction_id, "f": features}, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"shap:{self._model_version}:{digest}"

    async def _read_cache(self, key: str) -> Optional[ShapExplanation]:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            factors = [ShapFactor(**f) for f in data["factors"]]
            return ShapExplanation(
                prediction_id=data["prediction_id"],
                factors=factors,
                base_value=data["base_value"],
                output_value=data["output_value"],
                model_version=data["model_version"],
                computed_at=data["computed_at"],
                cached=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shap.cache.read_failed", error=str(exc))
            return None

    async def _write_cache(self, key: str, explanation: ShapExplanation) -> None:
        if self._redis is None:
            return
        try:
            data = {
                "prediction_id": explanation.prediction_id,
                "factors": [
                    {"feature": f.feature, "value": f.value, "shap_value": f.shap_value}
                    for f in explanation.factors
                ],
                "base_value": explanation.base_value,
                "output_value": explanation.output_value,
                "model_version": explanation.model_version,
                "computed_at": explanation.computed_at,
            }
            await self._redis.set(
                key, json.dumps(data, default=str), ex=settings.redis.shap_cache_ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shap.cache.write_failed", error=str(exc))


__all__ = ["ShapFactor", "ShapExplanation", "ShapExplainer"]
