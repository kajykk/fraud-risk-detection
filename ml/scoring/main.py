"""FastAPI ML 评分推理服务入口（端口 8501）。

对应 D03 §2.2 容器视图：ML Engine (scikit-learn + PyTorch) - 三模态并行评分 + SHAP。
- /health: 健康检查
- /v1/score: 同步评分（三模态并行 + 熔断）
- /v1/shap/{prediction_id}: 异步 SHAP 查询（24h 缓存）
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .engine import MLScoringEngine, ModalityScores
from .shap_explainer import ShapExplanation, ShapExplainer

logger = structlog.get_logger(__name__)


_engine: Optional[MLScoringEngine] = None
_shap: Optional[ShapExplainer] = None
_redis: Optional[Any] = None


class ScoreRequest(BaseModel):
    tenant_id: str = Field(..., description="租户 ID")
    transaction_id: str = Field(..., description="交易 ID")
    structured_features: Dict[str, Any] = Field(
        default_factory=dict, description="结构化特征（金额/时间/商户/设备/历史）"
    )
    text_content: str = Field(default="", description="文本内容（备注/对话）")
    behavior_series: List[List[float]] = Field(
        default_factory=list, description="行为时序序列"
    )


class ScoreResponse(BaseModel):
    transaction_id: str
    risk_score: float
    risk_band: str
    modality_scores: Dict[str, Any]
    latency_ms: float
    fallback_flags: Dict[str, str]
    all_fallback: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：加载模型 + Redis 连接。"""
    global _engine, _shap, _redis
    _engine = MLScoringEngine()
    _shap = ShapExplainer()

    try:
        if os.getenv("REDIS_URL"):
            import redis.asyncio as aioredis  # type: ignore

            _redis = aioredis.from_url(settings.redis.url, decode_responses=True)
            await _redis.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ml.main.redis.unavailable", error=str(exc))
        _redis = None

    await _engine.load(_redis)
    await _shap.init_redis(_redis)
    logger.info("ml.main.started", port=settings.server.port)
    yield
    if _redis is not None:
        await _redis.close()
    logger.info("ml.main.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="FRD ML Scoring Service",
        description="三模态并行评分 + SHAP（ADR-011）",
        version="1.1.0",
        lifespan=lifespan,
    )

    if settings.server.enable_prometheus:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore

            Instrumentator().instrument(app).expose(app, include_in_schema=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ml.main.prometheus.disabled", error=str(exc))

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "ml-scoring",
            "version": "1.1.0",
            "engine_loaded": _engine is not None,
        }

    @app.post("/v1/score", response_model=ScoreResponse)
    async def score(req: ScoreRequest) -> ScoreResponse:
        if _engine is None:
            raise HTTPException(status_code=503, detail="engine_not_loaded")
        scores: ModalityScores = await _engine.predict(
            structured_features=req.structured_features,
            text_content=req.text_content,
            behavior_series=req.behavior_series,
            tenant_id=req.tenant_id,
        )
        return ScoreResponse(
            transaction_id=req.transaction_id,
            risk_score=scores.fused_score,
            risk_band=scores.risk_band,
            modality_scores=scores.to_dict(),
            latency_ms=scores.latency_ms,
            fallback_flags=scores.fallback_flags,
            all_fallback=scores.all_fallback,
        )

    @app.get("/v1/shap/{prediction_id}", response_model=Optional[ShapExplanation])
    async def shap_explain(prediction_id: str) -> Optional[ShapExplanation]:
        # 实际场景下应从 DB 反查 features；这里仅占位返回 None
        if _shap is None:
            raise HTTPException(status_code=503, detail="shap_not_loaded")
        return None

    return app


app = create_app()


def main() -> None:
    """uvicorn 入口（端口 8501）。"""
    import uvicorn  # type: ignore

    uvicorn.run(
        "ml.scoring.main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        log_config=None,
    )


if __name__ == "__main__":
    main()
