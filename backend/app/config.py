"""应用配置（pydantic-settings）。

依据根目录 .env.example 与 D03 V1.1 技术栈选型定义所有配置分组。
配置分组：AppConfig / DatabaseConfig / RedisConfig / Neo4jConfig / JWTConfig /
          ScoringConfig / KillSwitchConfig / LLMConfig / TokenizationConfig
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回单例 Settings（lru_cache 缓存）。"""
    return Settings()


settings = get_settings()
