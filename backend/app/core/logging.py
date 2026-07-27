"""structlog 配置（D03 V1.1 §1.3 可观测性）。

提供结构化 JSON 日志，集成 request_id 与 tenant_id 上下文。
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import settings


def configure_logging() -> None:
    """配置 structlog + 标准库 logging，输出 JSON 到 stdout。"""
    log_level = getattr(logging, settings.app_log_level.upper(), logging.INFO)

    # 标准库 logging 配置（structlog 内部依赖）
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
        format="%(message)s",
    )

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            timestamper,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个 structlog logger。"""
    return structlog.get_logger(name)


def bind_request_context(request_id: str, tenant_id: str | None = None) -> None:
    """绑定 request_id / tenant_id 到 contextvar，后续日志自动携带。"""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    if tenant_id:
        structlog.contextvars.bind_contextvars(tenant_id=tenant_id)


__all__ = ["bind_request_context", "configure_logging", "get_logger"]
