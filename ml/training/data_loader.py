"""数据加载（PostgreSQL + 特征工程）。

数据源（D04）：
- transactions: 交易表（含 risk_features JSONB 预计算特征与人工反馈标签）
- scores: 评分记录表（每笔交易取最新一条，弱标签回退）
- 行为时序：从 transactions.metadata 提取点击流/输入节奏

标签语义（防自证循环）：
- 人工反馈标签（risk_features.is_fraud，来自 /transactions/feedback）
  优先于系统 DENY 决策；DENY 仅作冷启动弱标签回退。
- 每笔交易仅产出一条样本（LATERAL 取最新评分）。

多租户：所有查询显式 tenant_id 过滤（训练侧离线只读）。
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

        # 标签语义（H-2 修复）：
        # 1) 人工反馈标签优先 —— transactions.risk_features.is_fraud 由
        #    POST /transactions/feedback 写入，代表事后确认的真实欺诈标签，
        #    打破"模型学习复刻旧模型 DENY 决策"的自证循环；
        # 2) 无反馈时回退 decision = 'DENY'（弱标签，仅用于冷启动）。
        # 样本去重：LATERAL 每笔交易只取最新一条评分，防止一对多 JOIN
        # 产生重复样本随机泄漏进训练/验证两侧。
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
                COALESCE(
                    CASE
                        WHEN t.risk_features->>'is_fraud' = 'true' THEN true
                        WHEN t.risk_features->>'is_fraud' = 'false' THEN false
                        ELSE NULL
                    END,
                    s.decision = 'DENY',
                    false
                ) AS is_fraud,
                (t.risk_features->>'is_fraud') IS NOT NULL AS has_feedback_label
            FROM transactions t
            LEFT JOIN LATERAL (
                SELECT sc.decision
                FROM scores sc
                WHERE sc.transaction_id = t.id AND sc.tenant_id = t.tenant_id
                ORDER BY sc.created_at DESC
                LIMIT 1
            ) s ON true
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
        n_feedback = 0
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
            if row["has_feedback_label"]:
                n_feedback += 1

        logger.info(
            "data_loader.loaded",
            tenant_id=tenant_id,
            n_samples=len(labels),
            n_positive=sum(labels),
            n_feedback_labels=n_feedback,
            label_semantics="feedback_first_fallback_deny",
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
