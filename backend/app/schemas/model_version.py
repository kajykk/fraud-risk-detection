"""模型版本 schemas（D05 §6）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ModelStatus


class ModelRegisterRequest(BaseModel):
    """POST /models 请求体（D05 §6.2）。"""

    name: str
    version: str
    type: str = Field(..., description="XGB / BERT / MULTIMODAL / GNN")
    artifacts_path: str
    artifacts_sha256: str = Field(..., min_length=64, max_length=64)
    entrypoint: str | None = None
    runtime: str | None = None
    metrics: dict[str, Any]
    feature_schema_path: str | None = None
    trained_at: datetime
    description: str | None = None


class ModelOut(BaseModel):
    """模型详情。"""

    id: str
    name: str
    version: str
    type: str
    status: ModelStatus
    artifacts_path: str
    artifacts_sha256: str
    entrypoint: str | None = None
    runtime: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    feature_schema_path: str | None = None
    trained_at: datetime | None = None
    registered_at: datetime | None = None
    promoted_at: datetime | None = None
    traffic_share: float = 0.0
    description: str | None = None


class ModelUpdateRequest(BaseModel):
    """PUT /models/{model_id} 请求体（D05 §6.4）。"""

    description: str | None = None
    feature_schema_path: str | None = None
    entrypoint: str | None = None


class ModelCanaryRequest(BaseModel):
    """POST /models/{model_id}/canary 请求体（D05 §6.6）。"""

    candidate_model_id: str
    traffic_percentage: int = Field(..., ge=1, le=100)
    rollback_thresholds: dict[str, Any] | None = None
    observation_hours: int = 24
    approver_id: str


class ModelPromoteRequest(BaseModel):
    """POST /models/{model_id}/promote 请求体（D05 §6.7）。"""

    approver_id: str
    promotion_report_ref: str | None = None


class ModelRollbackRequest(BaseModel):
    """POST /models/{model_id}/rollback 请求体（D05 §6.8）。"""

    target_model_id: str
    reason: str
    approver_id: str


class ModelRetireRequest(BaseModel):
    """POST /models/{model_id}/retire 请求体（D05 §6.9）。"""

    reason: str
    approver_id: str
    data_retention_days: int = 90


class DriftOut(BaseModel):
    """GET /models/{model_id}/drift 响应（D05 §6.10）。"""

    model_id: str
    drift_status: str = "HEALTHY"
    psi_1d: float | None = None
    psi_7d: float | None = None
    kl_divergence: float | None = None
    last_checked_at: datetime | None = None
    feature_drifts: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "DriftOut",
    "ModelCanaryRequest",
    "ModelOut",
    "ModelPromoteRequest",
    "ModelRegisterRequest",
    "ModelRetireRequest",
    "ModelRollbackRequest",
    "ModelUpdateRequest",
]
