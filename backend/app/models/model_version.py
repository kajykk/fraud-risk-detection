"""模型治理模型（D04 V1.1 §3.5）。

表：model_versions / drift_alerts
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


class ModelVersion(Base, PKMixin, TenantMixin):
    """模型版本表（D04 §3.5）。

    注：tenant_id 可空（null 表示全局模型，D04 §9.2）。
    model_type: STRUCTURED / TEXT / BEHAVIOR / FUSION / GNN
    status: REGISTERED / CANARY / ACTIVE / RETIRED（基准 §3.3）
    """

    __tablename__ = "model_versions"

    # 覆盖为可空
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(  # type: ignore[assignment]
        UUID(as_uuid=True), nullable=True, index=True
    )
    model_type: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    # status: REGISTERED / CANARY / ACTIVE / RETIRED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REGISTERED")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    training_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_names: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    artifacts_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canary_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observation_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=168)
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class DriftAlert(Base, PKMixin, TenantMixin):
    """漂移告警表（D04 §3.5）。

    metric_type: PSI / KL / KS / WASSERSTEIN（基准 §3.12）
    severity: LOW / MEDIUM / HIGH / CRITICAL（基准 §3.12）
    """

    __tablename__ = "drift_alerts"

    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    # metric_type: PSI / KL / KS / WASSERSTEIN
    metric_type: Mapped[str] = mapped_column(String(10), nullable=False)
    metric_value: Mapped[Any] = mapped_column(Numeric(10, 4), nullable=False)
    threshold: Mapped[Any] = mapped_column(Numeric(10, 4), nullable=False)
    # severity: LOW / MEDIUM / HIGH / CRITICAL
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


__all__ = ["DriftAlert", "ModelVersion"]
