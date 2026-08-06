"""ML 评分服务配置。

对齐 FRD-D03-V1.1 §1.3 技术栈与 §4.3 三模态并行参数。
所有敏感配置通过环境变量注入，不在代码中硬编码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModalityConfig:
    """单模态配置（ADR-011）。"""

    name: str
    enabled: bool = True
    timeout_ms: float = 30.0  # ADR-011 单模态超时 30ms
    default_score: float = 0.5  # 熔断兜底默认值（中性）
    fallback_weight: float = 0.05  # 熔断后降权至 0.05
    recent_scores_window: int = 100  # Redis 滑动窗口大小


@dataclass(frozen=True)
class FusionConfig:
    """三模态融合配置（ADR-011 §4.3）。"""

    # D03 §4.3 默认权重：struct 0.6 / text 0.2 / behavior 0.2
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "structured": 0.6,
            "text": 0.2,
            "behavior": 0.2,
        }
    )
    # 熔断模态权重降到此值后，其余模态按比例放大
    fallback_weight: float = 0.05
    # 风险等级阈值（baseline §3.5）
    band_thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "LOW": 0.30,
            "MEDIUM": 0.60,
            "HIGH": 0.85,
            # CRITICAL >= 0.85
        }
    )


@dataclass(frozen=True)
class RedisConfig:
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    modality_history_prefix: str = "ml"  # key: ml:{tenant_id}:{modality}:recent_scores
    shap_cache_ttl_seconds: int = 86400  # SHAP 缓存 24h（ADR-007）


@dataclass(frozen=True)
class ModelRegistryConfig:
    """模型工件路径配置（注册表 D04 §3.5 model_versions）。"""

    structured_path: str = field(
        default_factory=lambda: os.getenv("ML_STRUCTURED_MODEL_PATH", "models/structured.xgb")
    )
    text_path: str = field(
        default_factory=lambda: os.getenv("ML_TEXT_MODEL_PATH", "models/text_bert")
    )
    behavior_path: str = field(
        default_factory=lambda: os.getenv("ML_BEHAVIOR_MODEL_PATH", "models/behavior_cnn.pt")
    )
    fusion_path: str = field(
        default_factory=lambda: os.getenv("ML_FUSION_MODEL_PATH", "models/fusion.pt")
    )


@dataclass(frozen=True)
class ServerConfig:
    host: str = field(default_factory=lambda: os.getenv("ML_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("ML_PORT", "8501")))
    workers: int = field(default_factory=lambda: int(os.getenv("ML_WORKERS", "4")))
    enable_prometheus: bool = field(default_factory=lambda: _env_bool("ML_ENABLE_PROMETHEUS", True))
    # 服务间鉴权 API Key（backend 通过 X-Api-Key 透传，须与 ML_API_KEY 一致；
    # 未配置时鉴权关闭并告警，生产必须配置）
    api_key: str = field(default_factory=lambda: os.getenv("ML_API_KEY", ""))


@dataclass(frozen=True)
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    structured: ModalityConfig = field(
        default_factory=lambda: ModalityConfig(name="structured")
    )
    text: ModalityConfig = field(default_factory=lambda: ModalityConfig(name="text"))
    behavior: ModalityConfig = field(default_factory=lambda: ModalityConfig(name="behavior"))
    fusion: FusionConfig = field(default_factory=FusionConfig)
    models: ModelRegistryConfig = field(default_factory=ModelRegistryConfig)
    # 模态连续熔断升级 Kill Switch 阈值（ADR-013 L3）
    modality_failure_window_seconds: int = 300  # 5min
    modality_failure_threshold: int = 50  # 5min 内 > 50 次 → L3


settings = Settings()
