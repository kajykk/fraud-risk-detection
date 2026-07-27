"""SHAP 异步计算任务（D03 V1.1 ADR-007 / D05 V1.1 §4）。

任务清单：
- compute_shap: 计算单笔交易 SHAP Top5 特征贡献
- cache_cleanup: SHAP 缓存清理（每天 03:00 定时，过期 24h 数据）

SHAP 计算约束：
- 单笔 ≤ 2s（D03 ADR-007）
- 缓存 TTL 24h（settings.scoring_shap_cache_hours）
- 失败重试 3 次，超时入死信
- 完成后发布 WebSocket 事件 transaction.shap_ready
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.config import settings
from app.core.logging import configure_logging
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


class ShapTask(Task):
    """SHAP 任务基类：启动时配置 structlog。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        configure_logging()
        return super().__call__(*args, **kwargs)


@celery_app.task(
    name="shap.compute",
    bind=True,
    base=ShapTask,
    queue="shap",
    max_retries=3,
    default_retry_delay=10,
    soft_time_limit=120,
    time_limit=150,
)
def compute_shap(
    self: ShapTask,
    tenant_id: str,
    decision_id: str,
    score_id: str,
    feature_values: dict[str, Any],
    model_version: str,
) -> dict[str, Any]:
    """异步计算 SHAP Top5 特征贡献。

    Args:
        tenant_id: 租户 ID
        decision_id: 评分决策 ID（dec_xxx）
        score_id: 评分记录 ID（UUID）
        feature_values: 特征值字典
        model_version: 模型版本号

    Returns:
        SHAP 结果 dict，含 factors / base_value / output_value
    """
    logger.info(
        "shap_compute_begin",
        tenant_id=tenant_id,
        decision_id=decision_id,
        score_id=score_id,
        model_version=model_version,
    )

    try:
        # TODO: 加载模型 + 计算 SHAP
        # from shap import TreeExplainer
        # explainer = TreeExplainer(model)
        # shap_values = explainer.shap_values(feature_matrix)
        # top5_indices = np.argsort(np.abs(shap_values))[-5:][::-1]

        # 骨架：生成占位结果
        factors = [
            {"feature": k, "value": v, "shap_value": 0.0, "contribution": 0.0}
            for k, v in list(feature_values.items())[:5]
        ]
        result = {
            "shap_task_id": f"shap_task_{uuid.uuid4()}",
            "decision_id": decision_id,
            "score_id": score_id,
            "factors": factors,
            "base_value": 0.5,
            "output_value": 0.5,
            "model_version": model_version,
            "status": "READY",
        }

        # 写入 Redis 缓存（TTL 24h）
        # NOTE: Celery worker 是同步模型，使用 asyncio.run 创建临时事件循环
        asyncio.run(_cache_shap_result(tenant_id, decision_id, result))

        # 发布 WebSocket 事件
        asyncio.run(_publish_shap_ready_event(tenant_id, decision_id))

        logger.info(
            "shap_compute_complete",
            tenant_id=tenant_id,
            decision_id=decision_id,
            factors_count=len(factors),
        )
        return result

    except Exception as exc:
        logger.error(
            "shap_compute_failed",
            tenant_id=tenant_id,
            decision_id=decision_id,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))


@celery_app.task(
    name="shap.cache_cleanup",
    bind=True,
    base=ShapTask,
    queue="shap",
)
def cache_cleanup(self: ShapTask) -> dict[str, Any]:
    """SHAP 缓存清理（每天 03:00 定时）。

    清理 Redis key 模式：shap_cache:{tenant}:*
    过期策略：TTL 由 settings.scoring_shap_cache_hours 控制（24h），
    此任务作为兜底，扫描并删除无 TTL 的孤儿 key。
    """
    logger.info("shap_cache_cleanup_begin")
    # TODO: SCAN shap_cache:* 并检查 TTL，删除无 TTL 的孤儿 key
    return {"status": "COMPLETED", "note": "TODO: implement cache cleanup"}


async def _cache_shap_result(
    tenant_id: str,
    decision_id: str,
    result: dict[str, Any],
) -> None:
    """写入 SHAP 结果到 Redis（TTL 24h）。"""
    try:
        from app.db.redis import get_redis

        redis = get_redis()
        key = f"shap_cache:{tenant_id}:{decision_id}"
        ttl_seconds = settings.scoring_shap_cache_hours * 3600
        await redis.set(key, json.dumps(result), ex=ttl_seconds)
    except Exception as exc:
        logger.warning("shap_cache_write_failed", error=str(exc))


async def _publish_shap_ready_event(tenant_id: str, decision_id: str) -> None:
    """发布 WebSocket 事件 transaction.shap_ready（D05 §2.8）。

    通过 Redis pubsub 广播到所有 API 实例，由 WebSocket 端点推送给客户端。
    """
    try:
        from app.db.redis import get_redis

        redis = get_redis()
        event = {
            "event_type": "transaction.shap_ready",
            "tenant_id": tenant_id,
            "data": {"decision_id": decision_id, "shap_status": "READY"},
        }
        await redis.publish("frd:ws_events", json.dumps(event))
    except Exception as exc:
        logger.warning("shap_event_publish_failed", error=str(exc))


__all__ = ["ShapTask", "cache_cleanup", "compute_shap"]
