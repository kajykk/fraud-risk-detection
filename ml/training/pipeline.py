"""训练管道主入口。

管道流程（D03 §4.3 / §5.2）：
    load_data → feature_eng → train(structured/text/behavior/fusion) → evaluate → register

触发条件（D03 §5.2）：
- 每周一 06:00 模型再训练评估
- 累积 10000 条标记 → 触发训练
- 金丝雀发布（7 天观察期，ADR-008）

执行环境：Celery Worker（异步任务，不进主路径）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from .data_loader import DataLoader
from .feature_store import FeatureStore
from .register import (
    ModelRegistration,
    ModelRegistry,
    compute_data_hash,
    compute_file_sha256,
)
from .train_behavior import train as train_behavior
from .train_fusion import train as train_fusion
from .train_structured import train as train_structured
from .train_text import train as train_text

logger = structlog.get_logger(__name__)


@dataclass
class PipelineConfig:
    tenant_id: str
    period_start: str
    period_end: str
    output_dir: str = "models"
    structured_path: str = "models/structured.xgb"
    text_path: str = "models/text_bert"
    behavior_path: str = "models/behavior_cnn.pt"
    fusion_path: str = "models/fusion.pt"
    model_version_prefix: str = "v1"


class TrainingPipeline:
    """端到端训练管道。"""

    def __init__(
        self,
        pg_dsn: str,
        config: PipelineConfig,
        feature_store: FeatureStore | None = None,
    ) -> None:
        self._pg_dsn = pg_dsn
        self.config = config
        self.feature_store = feature_store or FeatureStore()
        self.loader = DataLoader(pg_dsn)
        self.registry = ModelRegistry(pg_dsn)

    async def run(self) -> dict[str, Any]:
        """运行完整训练管道。"""
        logger.info(
            "pipeline.start",
            tenant_id=self.config.tenant_id,
            period=(self.config.period_start, self.config.period_end),
        )
        await self.loader.connect()
        await self.registry.connect()
        try:
            dataset = await self.loader.load_training_data(
                tenant_id=self.config.tenant_id,
                period_start=self.config.period_start,
                period_end=self.config.period_end,
            )
            if not dataset.labels:
                logger.warning("pipeline.no_data")
                return {"status": "no_data"}

            data_hash = compute_data_hash(dataset.structured)

            # 训练三模态 + 融合层
            structured_features = [
                self.feature_store.engineer(raw) for raw in dataset.structured
            ]
            s_result = train_structured(
                structured_features, dataset.labels, self.config.structured_path
            )
            t_result = train_text(dataset.texts, dataset.labels, self.config.text_path)
            b_result = train_behavior(
                dataset.behavior_series, dataset.labels, self.config.behavior_path
            )

            # 融合层训练（用三模态在训练集上的预测分数作为 Stacking 输入）
            # 此处简化：直接复用各模态评估指标作为占位
            s_metrics, t_metrics, b_metrics = s_result.metrics, t_result.metrics, b_result.metrics
            f_result = train_fusion(
                structured_scores=[s_metrics.get("auc", 0.5)] * len(dataset.labels),
                text_scores=[t_metrics.get("auc", 0.5)] * len(dataset.labels),
                behavior_scores=[b_metrics.get("auc", 0.5)] * len(dataset.labels),
                labels=dataset.labels,
                save_path=self.config.fusion_path,
            )

            # 注册到 model_versions 表
            registrations = [
                self._build_registration(
                    "STRUCTURED", s_result.model_path, s_result.metrics, data_hash
                ),
                self._build_registration(
                    "TEXT", t_result.model_path, t_result.metrics, data_hash
                ),
                self._build_registration(
                    "BEHAVIOR", b_result.model_path, b_result.metrics, data_hash
                ),
                self._build_registration(
                    "FUSION", f_result.model_path, f_result.metrics, data_hash
                ),
            ]
            model_ids: list[str] = []
            for reg in registrations:
                model_id = await self.registry.register(reg)
                if model_id:
                    model_ids.append(model_id)

            logger.info("pipeline.done", registered=len(model_ids))
            return {
                "status": "ok",
                "n_samples": len(dataset.labels),
                "registered_models": model_ids,
                "metrics": {
                    "structured": s_result.metrics,
                    "text": t_result.metrics,
                    "behavior": b_result.metrics,
                    "fusion": f_result.metrics,
                },
            }
        finally:
            await self.loader.close()
            await self.registry.close()

    def _build_registration(
        self,
        model_type: str,
        model_path: str,
        metrics: dict[str, float],
        data_hash: str,
    ) -> ModelRegistration:
        return ModelRegistration(
            tenant_id=self.config.tenant_id,
            model_type=model_type,
            version=f"{self.config.model_version_prefix}.0",
            status="REGISTERED",
            metrics=metrics,
            training_data_hash=data_hash,
            feature_names=self.feature_store.schema.feature_names,
            artifacts_path=model_path,
            sha256=compute_file_sha256(model_path) if __import__("os").path.exists(model_path) else "",
            canary_percent=0,
            observation_hours=168,
        )


def run_pipeline_sync(
    pg_dsn: str, tenant_id: str, period_start: str, period_end: str
) -> dict[str, Any]:
    """同步入口（供 Celery worker 调用）。"""
    config = PipelineConfig(
        tenant_id=tenant_id, period_start=period_start, period_end=period_end
    )
    pipeline = TrainingPipeline(pg_dsn, config)
    return asyncio.run(pipeline.run())


__all__ = ["PipelineConfig", "TrainingPipeline", "run_pipeline_sync"]
