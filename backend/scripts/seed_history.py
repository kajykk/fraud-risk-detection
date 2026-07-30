"""FRD 7 天历史趋势种子脚本 — 直接写入 DB（不经过评分接口，快速批量插入）。

为过去 7 天每天插入 20-40 笔交易 + 评分记录，制造真实趋势数据。
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random

from app.db.session import get_session_factory
from app.models.transaction import Score, Transaction

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# 每天交易数量 + 决策分布
DAILY_PLAN = [
    {"count": 25, "allow_pct": 0.80, "review_pct": 0.16, "deny_pct": 0.04},
    {"count": 30, "allow_pct": 0.75, "review_pct": 0.20, "deny_pct": 0.05},
    {"count": 35, "allow_pct": 0.70, "review_pct": 0.22, "deny_pct": 0.08},
    {"count": 40, "allow_pct": 0.65, "review_pct": 0.25, "deny_pct": 0.10},
    {"count": 28, "allow_pct": 0.72, "review_pct": 0.21, "deny_pct": 0.07},
    {"count": 32, "allow_pct": 0.78, "review_pct": 0.18, "deny_pct": 0.04},
    {"count": 38, "allow_pct": 0.68, "review_pct": 0.24, "deny_pct": 0.08},
]

CARD_BINS = ["411111", "542418", "453212", "512345"]
TX_TYPES = ["PURCHASE", "WITHDRAW", "REFUND", "TRANSFER", "TOPUP", "PAYMENT"]


def make_decision(r: float, plan: dict) -> tuple[str, float, str]:
    if r < plan["allow_pct"]:
        return "ALLOW", round(random.uniform(0.10, 0.28), 4), "LOW"
    elif r < plan["allow_pct"] + plan["review_pct"]:
        return "REVIEW", round(random.uniform(0.35, 0.58), 4), "MEDIUM"
    else:
        return "DENY", round(random.uniform(0.62, 0.92), 4), "HIGH"


async def seed():
    factory = get_session_factory()
    async with factory() as session:
        total_tx = 0
        total_scores = 0

        for day_offset in range(7, 0, -1):
            day = datetime.now(timezone.utc) - timedelta(days=day_offset)
            plan = DAILY_PLAN[7 - day_offset]

            for i in range(plan["count"]):
                r = random.random()
                decision, risk_score, risk_band = make_decision(r, plan)
                amount = random.choice([3000, 5000, 12000, 50000, 200000, 800000, 2000000])
                tx_id = uuid.uuid4()

                tx = Transaction(
                    id=tx_id,
                    tenant_id=TENANT_ID,
                    external_tx_id=f"HIST_{day_offset:02d}_{i:03d}",
                    card_token=f"tok_{random.choice(CARD_BINS)}",
                    card_bin=random.choice(CARD_BINS),
                    card_last4=f"{random.randint(1000, 9999)}",
                    amount=amount,
                    currency="CNY",
                    tx_type=random.choice(TX_TYPES),
                    channel=random.choice(["WEB", "APP", "POS", "API", "QR"]),
                    is_3ds_verified=random.random() > 0.3,
                    risk_features={},
                    occurred_at=day.replace(hour=random.randint(0, 23), minute=random.randint(0, 59)),
                    received_at=day,
                    metadata_={"amount": amount, "currency": "CNY"},
                )
                session.add(tx)
                await session.flush()

                score = Score(
                    tenant_id=TENANT_ID,
                    transaction_id=tx_id,
                    model_version="ml_xgb_v3.2.1",
                    rule_version="rule_v1",
                    risk_score=Decimal(str(risk_score)),
                    risk_band=risk_band,
                    decision=decision,
                    rule_hits=[],
                    modality_scores={},
                    feature_values={},
                    cached=False,
                    latency_ms=random.randint(8, 45),
                    scored_at=day,
                )
                session.add(score)
                total_tx += 1
                total_scores += 1

            await session.flush()

        await session.commit()
        print(f"Seeded {total_tx} transactions + {total_scores} scores across 7 days")


if __name__ == "__main__":
    random.seed(42)  # 可复现
    asyncio.run(seed())
