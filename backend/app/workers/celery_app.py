"""Celery 应用实例与配置（D03 V1.1 §1.3 / §5.4）。

启动 worker：
    celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

启动 beat：
    celery -A app.workers.celery_app beat --loglevel=info

任务路由（task_routes）：
- scoring.*     → queue=scoring   （评分持久化，高吞吐）
- shap.*        → queue=shap      （SHAP 计算，CPU 密集）
- pipl.*        → queue=pipl      （PIPL 合规任务，低优先级）
- cleanup.*     → queue=cleanup   （定时清理）
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "frd",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks_scoring",
        "app.workers.tasks_shap",
        "app.workers.tasks_pipl",
    ],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务执行
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_extended=True,
    # 重试
    task_default_max_retries=5,
    task_default_retry_backoff=True,
    task_default_retry_backoff_max=600,
    task_default_retry_jitter=True,
    # 任务路由
    task_routes={
        "scoring.*": {"queue": "scoring"},
        "shap.*": {"queue": "shap"},
        "pipl.*": {"queue": "pipl"},
        "cleanup.*": {"queue": "cleanup"},
    },
    task_default_queue="default",
    # 任务时间限制（秒）：soft → 触发 SoftTimeLimitExceeded；hard → 强制终止
    task_time_limit=3600,
    task_soft_time_limit=3000,
    # Beat 定时任务（D08 WBS 4.5.x）
    beat_schedule={
        # 模型漂移检测：每小时
        "drift-check-hourly": {
            "task": "scoring.drift_check",
            "schedule": crontab(minute=5),
            "options": {"queue": "scoring"},
        },
        # 模型 PSI 报告：每天 02:00
        "psi-report-daily": {
            "task": "scoring.psi_report",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "scoring"},
        },
        # SHAP 缓存清理：每天 03:00
        "shap-cache-cleanup": {
            "task": "shap.cache_cleanup",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "shap"},
        },
        # 审计日志归档：每周日 01:00
        "audit-archive-weekly": {
            "task": "cleanup.audit_archive",
            "schedule": crontab(hour=1, minute=0, day_of_week=0),
            "options": {"queue": "cleanup"},
        },
    },
)


__all__ = ["celery_app"]
