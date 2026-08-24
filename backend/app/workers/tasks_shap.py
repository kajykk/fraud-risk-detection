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
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.config import settings
from app.core.logging import configure_logging
from app.db.sync_session import sync_session_scope
from app.models.transaction import ShapExplanation
from app.services.shap_provider import generate_shap_factors
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
        # 基于交易特征生成 SHAP 因子（规则式 provider，与同步路径一致）
        risk_score = float(feature_values.get("risk_score", 0.5))
        shap_data = generate_shap_factors(feature_values, risk_score)

        factors = [
            {"feature": f["name"], "value": f["value"], "shap_value": f["shap"], "contribution": round(f["shap"], 4)}
            for f in shap_data["features"]
        ]
        result = {
            "shap_task_id": f"shap_task_{uuid.uuid4()}",
            "decision_id": decision_id,
            "score_id": score_id,
            "factors": factors,
            "base_value": shap_data["base_value"],
            "output_value": shap_data["prediction"],
            "model_version": model_version,
            "status": "READY",
        }

        # 写入 shap_explanations 表
        try:
            with sync_session_scope(tenant_id) as session:
                session.add(
                    ShapExplanation(
                        tenant_id=uuid.UUID(tenant_id),
                        score_id=uuid.UUID(score_id),
                        factors=factors,
                        base_value=shap_data["base_value"],
                        output_value=shap_data["prediction"],
                        model_version=model_version,
                        expires_at=datetime.now(UTC)
                        + timedelta(hours=settings.scoring_shap_cache_hours),
                    )
                )
        except Exception as exc:
            logger.warning("shap_db_write_failed", error=str(exc))

        # 写入 Redis 缓存（TTL 24h）
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
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc


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
    deleted = 0
    try:
        import asyncio

        deleted = asyncio.run(_cleanup_orphan_keys())
    except Exception as exc:
        logger.error("shap_cache_cleanup_failed", error=str(exc))
        return {"status": "FAILED", "error": str(exc)}
    logger.info("shap_cache_cleanup_complete", deleted=deleted)
    return {"status": "COMPLETED", "deleted": deleted}


async def _cleanup_orphan_keys() -> int:
    """扫描 shap_cache:* 并删除无 TTL 的孤儿 key。"""
    from app.db.redis import get_redis

    redis = get_redis()
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="shap_cache:*", count=200)
        for key in keys:
            ttl = await redis.ttl(key)
            if ttl == -1:  # 无 TTL 的孤儿 key
                await redis.delete(key)
                deleted += 1
        if cursor == 0:
            break
    return deleted


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

    复用 ws_events.publish_ws_event，保证消息结构完整对齐前端
    WsMessage（event_id / event_type / tenant_id / occurred_at / data）。
    """
    from app.services.ws_events import publish_ws_event

    await publish_ws_event(
        tenant_id,
        "transaction.shap_ready",
        {"decision_id": decision_id, "shap_status": "READY"},
    )


__all__ = ["ShapTask", "cache_cleanup", "compute_shap"]
