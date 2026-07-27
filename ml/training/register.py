"""模型注册到 model_versions 表（D04 §3.5）。

字段对齐：
- model_type: STRUCTURED / TEXT / BEHAVIOR / FUSION / GNN
- status: REGISTERED / CANARY / ACTIVE / RETIRED（baseline §3.3）
- metrics: JSONB（AUC/F1/Recall/FPR）
- training_data_hash: 训练数据 SHA256
- feature_names: JSONB
- artifacts_path: 模型文件路径
- sha256: 模型文件哈希
- canary_percent: 灰度比例
- observation_hours: 观察期（金融场景 168h=7天，ADR-008）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import structlog

logger = structlog.get_logger(__name__)


MODEL_TYPES = {"STRUCTURED", "TEXT", "BEHAVIOR", "FUSION", "GNN"}
MODEL_STATUSES = {"REGISTERED", "CANARY", "ACTIVE", "RETIRED"}


@dataclass
class ModelRegistration:
    """模型注册信息（对应 model_versions 一行）。"""

    tenant_id: Optional[str]
    model_type: str
    version: str
    status: str = "REGISTERED"
    metrics: dict[str, Any] = None
    training_data_hash: str = ""
    feature_names: List[str] = None
    artifacts_path: str = ""
    sha256: str = ""
    canary_percent: int = 0
    observation_hours: int = 168  # ADR-008 金融场景 7 天

    def __post_init__(self) -> None:
        if self.metrics is None:
            self.metrics = {}
        if self.feature_names is None:
            self.feature_names = []
        if self.model_type not in MODEL_TYPES:
            raise ValueError(f"invalid model_type: {self.model_type}")
        if self.status not in MODEL_STATUSES:
            raise ValueError(f"invalid status: {self.status}")


def compute_file_sha256(path: str | Path) -> str:
    """计算模型文件 SHA256。"""
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_data_hash(samples: list[Any]) -> str:
    """计算训练数据 SHA256（用于 model_versions.training_data_hash）。"""
    payload = json.dumps(samples, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ModelRegistry:
    """model_versions 表写入器。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Optional[Any] = None

    async def connect(self) -> None:
        try:
            import asyncpg  # type: ignore

            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=5)
        except Exception as exc:  # noqa: BLE001
            logger.error("registry.connect_failed", error=str(exc))
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def register(self, registration: ModelRegistration) -> Optional[str]:
        """写入 model_versions 表（status=REGISTERED）。

        Returns:
            model_version_id (UUID) 或 None
        """
        if self._pool is None:
            logger.warning("registry.pool_not_ready")
            return None
        sql = """
            INSERT INTO model_versions (
                tenant_id, model_type, version, status, metrics,
                training_data_hash, feature_names, artifacts_path,
                sha256, canary_percent, observation_hours, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
            RETURNING id
        """
        try:
            row = await self._pool.fetchrow(
                sql,
                registration.tenant_id,
                registration.model_type,
                registration.version,
                registration.status,
                json.dumps(registration.metrics, default=str),
                registration.training_data_hash,
                json.dumps(registration.feature_names, ensure_ascii=False),
                registration.artifacts_path,
                registration.sha256,
                registration.canary_percent,
                registration.observation_hours,
            )
            model_id = str(row["id"]) if row else None
            logger.info(
                "registry.registered",
                model_id=model_id,
                model_type=registration.model_type,
                version=registration.version,
                status=registration.status,
            )
            return model_id
        except Exception as exc:  # noqa: BLE001
            logger.error("registry.insert_failed", error=str(exc))
            return None


__all__ = [
    "MODEL_TYPES",
    "MODEL_STATUSES",
    "ModelRegistration",
    "ModelRegistry",
    "compute_file_sha256",
    "compute_data_hash",
]
