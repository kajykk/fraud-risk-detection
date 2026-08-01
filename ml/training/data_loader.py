"""数据加载（PostgreSQL + 特征工程）。

数据源（D04）：
- transactions: 交易表（含 risk_features JSONB 预计算特征）
- scores: 评分记录表（含 label 反馈）
- 行为时序：从 transactions.metadata 提取点击流/输入节奏

多租户：所有查询 SET LOCAL app.tenant_id（ADR-015）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TrainingDataset:
    """训练数据集。"""

    structured: list[dict[str, Any]]
    texts: list[str]
    behavior_series: list[list[list[float]]]
    labels: list[int]
    tenant_id: str
    period_start: str
    period_end: str


class DataLoader:
    """PostgreSQL 数据加载器。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any | None = None

    async def connect(self) -> None:
        try:
            import asyncpg  # type: ignore

            self._pool = await asyncpg.create_pool(
                dsn=self._dsn, min_size=2, max_size=10
            )
            logger.info("data_loader.connected", dsn=self._dsn)
        except Exception as exc:  # noqa: BLE001
            logger.error("data_loader.connect_failed", error=str(exc))
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def load_training_data(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        limit: int = 100000,
    ) -> TrainingDataset:
        """从 PostgreSQL 加载训练数据。

        Args:
            tenant_id: 租户 ID（RLS 强制）
            period_start: 起始日期（ISO8601）
            period_end: 结束日期（ISO8601）
            limit: 最大样本数
        """
        if self._pool is None:
            logger.warning("data_loader.pool_not_ready")
            return TrainingDataset(
                structured=[], texts=[], behavior_series=[], labels=[],
                tenant_id=tenant_id, period_start=period_start, period_end=period_end,
            )

        sql = """
            SELECT
                t.id,
                t.amount,
                t.tx_type,
                t.channel,
                t.merchant_category,
                t.risk_features,
                COALESCE(t.note_text, '') AS note_text,
                t.metadata->'behavior' AS behavior,
                COALESCE(s.decision = 'DENY', false) AS is_fraud
            FROM transactions t
            LEFT JOIN scores s ON s.transaction_id = t.id AND s.tenant_id = t.tenant_id
            WHERE t.tenant_id = $1
              AND t.occurred_at BETWEEN $2 AND $3
            ORDER BY t.occurred_at DESC
            LIMIT $4
        """
        rows = await self._pool.fetch(sql, tenant_id, period_start, period_end, limit)
        structured = []
        texts: list[str] = []
        behavior_series: list[list[list[float]]] = []
        labels: list[int] = []
        for row in rows:
            features = dict(row["risk_features"] or {})
            features.setdefault("amount", float(row["amount"]))
            features.setdefault("tx_type", row["tx_type"])
            features.setdefault("channel", row["channel"])
            features.setdefault("merchant_category", row["merchant_category"])
            structured.append(features)
            texts.append(row["note_text"] or "")
            behavior_series.append(self._parse_behavior(row["behavior"]))
            labels.append(1 if row["is_fraud"] else 0)

        logger.info(
            "data_loader.loaded",
            tenant_id=tenant_id,
            n_samples=len(labels),
            n_positive=sum(labels),
        )
        return TrainingDataset(
            structured=structured,
            texts=texts,
            behavior_series=behavior_series,
            labels=labels,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
        )

    @staticmethod
    def _parse_behavior(raw: Any) -> list[list[float]]:
        if not raw:
            return []
        try:
            if isinstance(raw, list):
                return [[float(x) for x in frame] for frame in raw]
            if isinstance(raw, dict) and "frames" in raw:
                return [[float(x) for x in frame] for frame in raw["frames"]]
        except (TypeError, ValueError):
            return []
        return []


__all__ = ["DataLoader", "TrainingDataset"]
