"""GNN 服务配置（D03 §4.4）。

技术栈（D03 §1.3）：
- PyTorch Geometric (PyG) 2.5
- Neo4j driver 5.23
- python-louvain 0.16

性能目标（D03 §7.2）：
- GNN 查询 P99 < 2s
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
class Neo4jConfig:
    uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    database: str = field(default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j"))
    max_connection_pool_size: int = field(
        default_factory=lambda: int(os.getenv("NEO4J_POOL_SIZE", "50"))
    )


@dataclass(frozen=True)
class GraphSAGEConfig:
    """GraphSAGE 模型配置（D03 §4.4）。"""

    in_channels: int = 64  # 输入节点特征维度
    hidden_channels: list[int] = field(default_factory=lambda: [256, 128])
    num_layers: int = 2  # SAGEConv 层数（与 hidden_channels 长度一致）
    dropout: float = 0.2
    out_channels: int = 128  # 输出 embedding 维度


@dataclass(frozen=True)
class CommunityConfig:
    """团伙检测配置（D03 §4.4）。"""

    algorithm: str = "louvain"  # louvain | label_propagation
    fraud_rate_threshold: float = 0.3  # 社区欺诈率 > 30% → 标记为欺诈团伙
    min_community_size: int = 3
    resolution: float = 1.0  # Louvain 分辨率


@dataclass(frozen=True)
class RedisConfig:
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/1"))
    embedding_cache_ttl_seconds: int = 3600  # 节点 embedding 缓存 1h


@dataclass(frozen=True)
class ServerConfig:
    host: str = field(default_factory=lambda: os.getenv("GNN_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("GNN_PORT", "8502")))
    workers: int = field(default_factory=lambda: int(os.getenv("GNN_WORKERS", "2")))
    enable_prometheus: bool = field(
        default_factory=lambda: _env_bool("GNN_ENABLE_PROMETHEUS", True)
    )
    # 服务间鉴权 API Key（backend 通过 X-Api-Key 透传，须与 GNN_API_KEY 一致；
    # 未配置时鉴权关闭并告警，生产必须配置）
    api_key: str = field(default_factory=lambda: os.getenv("GNN_API_KEY", ""))


@dataclass(frozen=True)
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    graphsage: GraphSAGEConfig = field(default_factory=GraphSAGEConfig)
    community: CommunityConfig = field(default_factory=CommunityConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    # 模型工件路径
    model_path: str = field(
        default_factory=lambda: os.getenv("GNN_MODEL_PATH", "models/graphsage.pt")
    )
    # 查询 P99 目标 2s（D03 §7.2）
    query_timeout_seconds: float = 2.0


settings = Settings()
