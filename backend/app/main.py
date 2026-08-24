"""FRD 金融反欺诈系统 FastAPI 应用入口（D03 V1.1 §2 / D05 V1.1 §1）。

启动顺序（lifespan）：
1. configure_logging()
2. init_engine() / init_redis() / init_neo4j()
3. 注册中间件 / 路由 / 异常 handler / Prometheus 指标
4. 服务信号 → 优雅关闭 close_engine / close_redis / close_neo4j

中间件顺序（外 → 内）：
    RequestIdMiddleware → TenantMiddleware → RateLimitMiddleware → AuditMiddleware → 路由
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app import __app_name__, __version__
from app.api.v1.router import router as v1_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.neo4j import close_neo4j, init_neo4j
from app.db.redis import close_redis, init_redis
from app.db.session import close_engine, init_engine
from app.middleware.audit import AuditMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.tenant import TenantMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化资源，关闭时释放。"""
    configure_logging()
    logger.info(
        "app_startup_begin",
        app_name=__app_name__,
        version=__version__,
        env=settings.app_env,
    )

    # 初始化依赖服务（失败不阻断启动，由 readiness 探针反映状态）
    try:
        await init_engine()
    except Exception as exc:
        logger.error("db_init_failed", error=str(exc))
    try:
        await init_redis()
    except Exception as exc:
        logger.error("redis_init_failed", error=str(exc))
    try:
        await init_neo4j()
    except Exception as exc:
        logger.error("neo4j_init_failed", error=str(exc))

    # 规则缓存 pubsub 监听：订阅 frd:rules_reload，收到广播后失效进程内
    # 编译缓存（多副本部署下与 rules API 写路径的 hot_reload 保持一致）。
    # 监听失败仅告警并自动重连，不阻断启动；规则缓存仍有 TTL 300s 兜底。
    from app.services.rule_engine import rule_engine

    rules_reload_task = asyncio.create_task(rule_engine.listen_reload())

    logger.info("app_startup_complete")
    yield

    logger.info("app_shutdown_begin")
    rules_reload_task.cancel()
    try:
        await rules_reload_task
    except asyncio.CancelledError:
        pass
    await close_neo4j()
    await close_redis()
    await close_engine()
    logger.info("app_shutdown_complete")


def create_app() -> FastAPI:
    """应用工厂。"""
    app = FastAPI(
        title=__app_name__,
        version=__version__,
        description="FRD 金融反欺诈与交易风险预警系统 API（D05 V1.1）",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ #
    # 中间件（注册顺序与执行顺序相反：后注册先执行）
    # ------------------------------------------------------------------ #
    # CORS 最外层
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
    # 审计日志（最内层，靠近路由）
    app.add_middleware(AuditMiddleware)
    # 限流
    app.add_middleware(RateLimitMiddleware)
    # 租户上下文
    app.add_middleware(TenantMiddleware)
    # 请求 ID（最内层 → 实际最先执行，确保后续中间件能读到 request_id）
    app.add_middleware(RequestIdMiddleware)

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #
    app.include_router(v1_router, prefix="/api/v1")

    # 健康检查同时挂在根路径，方便探针直接访问 /health /live /ready
    from app.api.v1.health import router as health_router

    app.include_router(health_router, tags=["health"])

    # ------------------------------------------------------------------ #
    # 异常 handler
    # ------------------------------------------------------------------ #
    register_exception_handlers(app)

    # ------------------------------------------------------------------ #
    # Prometheus 指标
    # ------------------------------------------------------------------ #
    if settings.prometheus_enabled:
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_respect_env_var=False,
            excluded_handlers=[".*(/health|/live|/ready|/metrics).*"],
        ).instrument(app).expose(
            app,
            endpoint="/metrics",
            include_in_schema=False,
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """根路径：返回服务基本信息。"""
        return {
            "name": __app_name__,
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()


__all__ = ["app", "create_app"]
