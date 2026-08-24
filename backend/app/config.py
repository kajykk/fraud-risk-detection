"""应用配置（pydantic-settings）。

依据根目录 .env.example 与 D03 V1.1 技术栈选型定义所有配置分组。
配置分组：AppConfig / DatabaseConfig / RedisConfig / Neo4jConfig / JWTConfig /
          ScoringConfig / KillSwitchConfig / LLMConfig / TokenizationConfig
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """应用基础配置。"""

    app_env: Literal["local", "dev", "test", "staging", "prod"] = "local"
    app_name: str = "frd"
    app_port: int = 8000
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    app_secret_key: str = Field(default="change-me", min_length=16)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    prometheus_enabled: bool = True
    jaeger_endpoint: str = ""
    sentry_dsn: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


class DatabaseConfig(BaseSettings):
    """PostgreSQL 配置（asyncpg）。"""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "frd"
    postgres_user: str = "frd"
    postgres_password: str = "frd_dev_password"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20

    @property
    def async_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class RedisConfig(BaseSettings):
    """Redis 配置（redis[asyncio]）。"""

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    @property
    def url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


class Neo4jConfig(BaseSettings):
    """Neo4j 配置。"""

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "frd_neo4j_password"
    neo4j_database: str = "neo4j"


class JWTConfig(BaseSettings):
    """JWT / 认证配置。"""

    jwt_secret_key: str = Field(default="change-me-jwt", min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7


class KafkaConfig(BaseSettings):
    """Kafka 配置（D03 §5.3）。"""

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_transactions: str = "frd.transactions"
    kafka_topic_decisions: str = "frd.decisions"
    kafka_topic_audit: str = "frd.audit_log"
    kafka_consumer_group: str = "frd-scoring"


class CeleryConfig(BaseSettings):
    """Celery 配置。"""

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"


class ScoringConfig(BaseSettings):
    """评分参数（D03 V1.1 §4.1 200ms 预算）。"""

    scoring_p99_budget_ms: int = 200
    scoring_cache_ttl_seconds: int = 300
    scoring_modality_timeout_ms: int = 30
    scoring_shap_cache_hours: int = 24
    # 三模态融合权重（ADR-011）
    fusion_weight_structured: float = 0.6
    fusion_weight_text: float = 0.2
    fusion_weight_behavior: float = 0.2
    # 熔断降权
    fallback_weight_degraded: float = 0.05
    fallback_default_score: float = 0.5


class KillSwitchConfig(BaseSettings):
    """Kill Switch 初始状态（D03 V1.1 §4.8）。"""

    kill_switch_global: bool = False
    kill_switch_ml: bool = False
    kill_switch_rules: bool = False
    kill_switch_gnn: bool = False
    # 状态同步 Redis pubsub channel
    kill_switch_pubsub_channel: str = "frd:kill_switch"


class GNNConfig(BaseSettings):
    """GNN 服务配置（D05 §7，环境变量 GNN_SERVICE_URL 可覆盖）。"""

    gnn_service_url: str = "http://localhost:8502"
    # GNN 服务间鉴权（与 gnn 服务 GNN_API_KEY 保持一致；为空则不携带）
    gnn_api_key: str = ""


class MLRemoteConfig(BaseSettings):
    """ML 远程推理服务（ml-serving :8501）调用配置。

    ML_ENGINE_MODE 三档：
    - remote：仅调用 ml-serving POST /v1/score（三模态真实推理）
    - heuristic：仅本地金额启发式，不发网络请求
    - auto（默认）：先远程，超时/故障自动回退启发式并记录 warning
    """

    ml_engine_mode: Literal["remote", "heuristic", "auto"] = "auto"
    # compose 内由 backend 环境变量注入 http://ml-serving:8501
    ml_service_url: str = "http://localhost:8501"
    # 与 ml-serving 的 ML_API_KEY 保持一致；为空则不携带 X-Api-Key 头
    ml_api_key: str = ""
    ml_connect_timeout_seconds: float = 2.0
    ml_read_timeout_seconds: float = 5.0
    # 远程调用轻量熔断器：连续失败 N 次后打开，冷却 M 秒后半开放行重试
    ml_breaker_failure_threshold: int = 5
    ml_breaker_recovery_seconds: float = 30.0


class LLMConfig(BaseSettings):
    """LLM 配置（ADR-012，国内 API，PIPL 合规）。"""

    llm_provider: Literal["qwen", "deepseek"] = "deepseek"
    qwen_api_key: str = ""
    qwen_model: str = "qwen-max"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 30.0


class TokenizationConfig(BaseSettings):
    """Tokenization 配置（PCI-DSS ADR-005）。"""

    tokenization_provider: Literal["local", "aliyun-kms"] = "local"
    tokenization_local_key: str = "change-me-32-bytes-hex-key"
    aliyun_kms_key_id: str = ""
    aliyun_kms_access_key_id: str = ""
    aliyun_kms_access_key_secret: str = ""
    aliyun_kms_region: str = "cn-hangzhou"


class Settings(
    AppConfig,
    DatabaseConfig,
    RedisConfig,
    Neo4jConfig,
    JWTConfig,
    KafkaConfig,
    CeleryConfig,
    ScoringConfig,
    KillSwitchConfig,
    GNNConfig,
    MLRemoteConfig,
    LLMConfig,
    TokenizationConfig,
):
    """聚合所有配置分组的应用 Settings。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _guard_prod_secrets(self) -> Settings:
        """生产环境拒绝已知默认/弱密钥，防止漏配环境变量后以公开密钥运行。

        默认值均来自 .env.example / config 默认值（公开仓库可见），
        prod 使用它们等于无认证、卡号 Token 可解。
        """
        if self.app_env != "prod":
            return self
        insecure = []
        for name, value in (
            ("app_secret_key", self.app_secret_key),
            ("jwt_secret_key", self.jwt_secret_key),
            ("postgres_password", self.postgres_password),
            ("neo4j_password", self.neo4j_password),
            ("redis_password", self.redis_password),
            ("tokenization_local_key", self.tokenization_local_key),
        ):
            if not value or len(value) < 16:
                insecure.append(f"{name}(too_short)")
            elif value.lower() in {
                "change-me",
                "change-me-jwt",
                "change-me-to-a-long-random-string",
                "change-me-to-a-different-long-random-string",
                "change-me-32-bytes-hex-key",
                "frd_dev_password",
                "frd_neo4j_password",
                "test12345",
            }:
                insecure.append(f"{name}(known_default)")
        if insecure:
            raise ValueError(
                "insecure secrets for prod environment: "
                + ", ".join(insecure)
                + "; set strong values via environment variables"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回单例 Settings（lru_cache 缓存）。"""
    return Settings()


settings = get_settings()
