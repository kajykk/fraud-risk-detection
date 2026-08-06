"""FastAPI ML 评分推理服务入口（端口 8501）。

对应 D03 §2.2 容器视图：ML Engine (scikit-learn + PyTorch) - 三模态并行评分 + SHAP。
- /health: 健康检查
- /v1/score: 同步评分（三模态并行 + 熔断）
- /v1/shap/{prediction_id}: 异步 SHAP 查询（24h 缓存）
"""

from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .engine import MLScoringEngine, ModalityScores
from .shap_explainer import ShapExplainer, ShapExplanation

logger = structlog.get_logger(__name__)


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> None:
    """服务间鉴权：X-Api-Key 须与 ML_API_KEY 一致（恒定时间比较）。

    未配置 ML_API_KEY 时鉴权关闭（仅开发/本地；生产必须配置）。
    """
    expected = settings.server.api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid_api_key")


_engine: MLScoringEngine | None = None
_shap: ShapExplainer | None = None
_redis: Any | None = None


class ScoreRequest(BaseModel):
    tenant_id: str = Field(..., description="租户 ID")
    transaction_id: str = Field(..., description="交易 ID")
    structured_features: dict[str, Any] = Field(
        default_factory=dict, description="结构化特征（金额/时间/商户/设备/历史）"
    )
    text_content: str = Field(default="", description="文本内容（备注/对话）")
    behavior_series: list[list[float]] = Field(
        default_factory=list, description="行为时序序列"
    )


class ScoreResponse(BaseModel):
    transaction_id: str
    risk_score: float
    risk_band: str
    modality_scores: dict[str, Any]
    latency_ms: float
    fallback_flags: dict[str, str]
    all_fallback: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：加载模型 + Redis 连接 + 挂载 SHAP。"""
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

    # 挂载结构化 XGBoost 模型到 SHAP TreeExplainer（ADR-007）
    structured_model = getattr(_engine.structured, "_model", None)
    if structured_model is not None:
        _shap.attach_tree_model(structured_model, model_version="structured_v1")
        logger.info("ml.main.shap.tree_explainer.attached")
    else:
        logger.warning("ml.main.shap.tree_explainer.skip", reason="structured_model_not_loaded")

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
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ml-scoring",
            "version": "1.1.0",
            "engine_loaded": _engine is not None,
        }

    @app.post("/v1/score", response_model=ScoreResponse, dependencies=[Depends(require_api_key)])
    async def score(req: ScoreRequest) -> ScoreResponse:
        if _engine is None:
            raise HTTPException(status_code=503, detail="engine_not_loaded")
        scores: ModalityScores = await _engine.predict(
            structured_features=req.structured_features,
            text_content=req.text_content,
            behavior_series=req.behavior_series,
            tenant_id=req.tenant_id,
        )
        # 缓存特征供后续 SHAP 查询（TTL 24h，ADR-007）
        if _redis is not None:
            try:
                await _redis.set(
                    f"shap:features:{req.transaction_id}",
                    json.dumps(req.structured_features, default=str),
                    ex=settings.redis.shap_cache_ttl_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ml.main.features.cache_failed", error=str(exc))
        return ScoreResponse(
            transaction_id=req.transaction_id,
            risk_score=scores.fused_score,
            risk_band=scores.risk_band,
            modality_scores=scores.to_dict(),
            latency_ms=scores.latency_ms,
            fallback_flags=scores.fallback_flags,
            all_fallback=scores.all_fallback,
        )

    @app.get("/v1/shap/{prediction_id}", response_model=ShapExplanation | None, dependencies=[Depends(require_api_key)])
    async def shap_explain(prediction_id: str) -> ShapExplanation | None:
        """查询单笔交易 SHAP 解释（从 Redis 反查特征 + 24h 缓存）。"""
        if _shap is None:
            raise HTTPException(status_code=503, detail="shap_not_loaded")

        # 反查评分时缓存的交易特征
        if _redis is None:
            return None
        try:
            raw = await _redis.get(f"shap:features:{prediction_id}")
            if not raw:
                return None
            features: dict[str, Any] = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ml.main.shap.features_missing", prediction_id=prediction_id, error=str(exc))
            return None

        # 按模型 feature_names 顺序构造特征向量
        feature_vector: list[float] | None = None
        feature_names: list[str] | None = None
        model = getattr(_engine, "structured", None)
        if model is not None:
            names = getattr(model, "_feature_names", None)
            if names:
                feature_names = list(names)
                feature_vector = []
                for name in feature_names:
                    try:
                        feature_vector.append(float(features.get(name, 0.0)))
                    except (TypeError, ValueError):
                        feature_vector.append(0.0)
            else:
                # 无 feature_names：按 dict 键序
                feature_names = list(features.keys())
                try:
                    feature_vector = [float(v) for v in features.values()]
                except (TypeError, ValueError):
                    feature_vector = None

        return await _shap.explain(
            prediction_id=prediction_id,
            features=features,
            feature_vector=feature_vector,
            feature_names=feature_names,
        )

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
