"""漂移告警（写入 drift_alerts 表，D04 §3.5）。

字段对齐：
- tenant_id: 租户 ID（强制）
- model_version: 模型版本
- modality: 模态
- metric_type: PSI | KL | KS | WASSERSTEIN（baseline §3.12）
- metric_value: DECIMAL(10,4)
- threshold: DECIMAL(10,4)
- severity: LOW | MEDIUM | HIGH | CRITICAL
- detected_at: TIMESTAMPTZ
- resolved_at: TIMESTAMPTZ（可空）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .detector import DriftResult

logger = structlog.get_logger(__name__)


@dataclass
class DriftAlertRecord:
    """drift_alerts 一行（D04 §3.5）。"""

    tenant_id: str
    model_version: str
    modality: str
    metric_type: str
    metric_value: float
    threshold: float
    severity: str
    detected_at: datetime
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "model_version": self.model_version,
            "modality": self.modality,
            "metric_type": self.metric_type,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class DriftAlerter:
    """漂移告警写入器。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Optional[Any] = None

    async def connect(self) -> None:
        try:
            import asyncpg  # type: ignore

            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=5)
        except Exception as exc:  # noqa: BLE001
            logger.error("drift.alerter.connect_failed", error=str(exc))
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def emit_alert(
        self,
        tenant_id: str,
        model_version: str,
        modality: str,
        result: DriftResult,
    ) -> Optional[str]:
        """写入 drift_alerts 表（仅在 is_drifted=True 时）。"""
        if not result.is_drifted:
            return None
        if self._pool is None:
            logger.warning("drift.alerter.pool_not_ready")
            return None
        record = DriftAlertRecord(
            tenant_id=tenant_id,
            model_version=model_version,
            modality=modality,
            metric_type=result.metric_type,
            metric_value=result.value,
            threshold=result.threshold,
            severity=result.severity,
            detected_at=datetime.now(timezone.utc),
        )
        sql = """
            INSERT INTO drift_alerts (
                tenant_id, model_version, modality, metric_type,
                metric_value, threshold, severity, detected_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
            RETURNING id
        """
        try:
            row = await self._pool.fetchrow(
                sql,
                record.tenant_id,
                record.model_version,
                record.modality,
                record.metric_type,
                record.metric_value,
                record.threshold,
                record.severity,
                record.detected_at,
            )
            alert_id = str(row["id"]) if row else None
            logger.info(
                "drift.alert.emitted",
                alert_id=alert_id,
                tenant_id=tenant_id,
                model_version=model_version,
                modality=modality,
                severity=record.severity,
                metric_value=record.metric_value,
            )
            # CRITICAL 级别 → 触发 L2 模型级 Kill Switch（ADR-013，由外层控制器处理）
            if record.severity == "CRITICAL":
                logger.error(
                    "drift.alert.critical",
                    tenant_id=tenant_id,
                    model_version=model_version,
                    modality=modality,
                    metric_value=record.metric_value,
                    recommendation="trigger_l2_kill_switch",
                )
            return alert_id
        except Exception as exc:  # noqa: BLE001
            logger.error("drift.alert.insert_failed", error=str(exc))
            return None


__all__ = ["DriftAlertRecord", "DriftAlerter"]
