"""FRD 高风险交易种子脚本 — 提交 10 笔不同特征交易。

目标决策分布：ALLOW 5 / REVIEW 3 / DENY 2
调用 POST /api/v1/transactions/score 接口评分并持久化。
"""
import asyncio
import os
import uuid
from datetime import UTC, datetime

import httpx

BASE_URL = "http://127.0.0.1:8000"
API_PREFIX = "/api/v1"

# 登录凭据通过环境变量注入（与 seed_users 保持一致），禁止硬编码默认口令
SEED_USER = os.getenv("FRD_ADMIN_USER", "admin").strip() or "admin"
SEED_PASSWORD = os.environ.get("FRD_ADMIN_PASSWORD", "")

# 10 笔交易，覆盖不同风险等级
TRANSACTIONS = [
    # --- ALLOW（正常小额，5 笔）---
    {"external_tx_id": "TX_NORMAL_001", "tx_type": "PURCHASE", "amount": 5000,   "card_bin": "411111", "card_last4": "1111", "merchant_id": "M001", "user_id": "U001"},
    {"external_tx_id": "TX_NORMAL_002", "tx_type": "PURCHASE", "amount": 12000,  "card_bin": "411111", "card_last4": "2222", "merchant_id": "M001", "user_id": "U002"},
    {"external_tx_id": "TX_NORMAL_003", "tx_type": "TOPUP",    "amount": 3000,   "card_bin": "411111", "card_last4": "3333", "merchant_id": "M001", "user_id": "U003"},
    {"external_tx_id": "TX_NORMAL_004", "tx_type": "PAYMENT",   "amount": 8000,  "card_bin": "411111", "card_last4": "4444", "merchant_id": "M001", "user_id": "U004"},
    {"external_tx_id": "TX_NORMAL_005", "tx_type": "PURCHASE",  "amount": 1500,  "card_bin": "411111", "card_last4": "5555", "merchant_id": "M001", "user_id": "U005"},
    # --- REVIEW（中风险，3 笔）---
    {"external_tx_id": "TX_REVIEW_001", "tx_type": "PURCHASE", "amount": 800000, "card_bin": "542418", "card_last4": "6666", "merchant_id": "M001", "user_id": "U006"},
    {"external_tx_id": "TX_REVIEW_002", "tx_type": "WITHDRAW","amount": 600000, "card_bin": "542418", "card_last4": "7777", "merchant_id": "M001", "user_id": "U007"},
    {"external_tx_id": "TX_REVIEW_003", "tx_type": "TRANSFER", "amount": 500000, "card_bin": "542418", "card_last4": "8888", "merchant_id": "M001", "user_id": "U008"},
    # --- DENY（高风险，2 笔）---
    {"external_tx_id": "TX_DENY_001",   "tx_type": "PURCHASE", "amount": 2000000,"card_bin": "542418", "card_last4": "9999", "merchant_id": "M001", "user_id": "U009"},
    {"external_tx_id": "TX_DENY_002",   "tx_type": "WITHDRAW","amount": 1000000,"card_bin": "542418", "card_last4": "0000", "merchant_id": "M001", "user_id": "U010"},
]


async def main():
    if len(SEED_PASSWORD) < 12:
        raise SystemExit(
            "FRD_ADMIN_PASSWORD 未设置或长度不足 12 位；请先去种用户前的强口令环境再运行。"
        )
    # 1. 登录获取 token
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        login_resp = await client.post(
            f"{API_PREFIX}/auth/login",
            json={
                "username": SEED_USER,
                "password": SEED_PASSWORD,
                "scopes": ["transaction:score", "transaction:read"],
            },
        )
        login_resp.raise_for_status()
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 逐笔评分
        now_iso = datetime.now(UTC).isoformat()
        results = []
        for tx in TRANSACTIONS:
            body = {
                **tx,
                "currency": "CNY",
                "occurred_at": now_iso,
                "card_token": f"tok_{tx['card_bin']}",
            }
            resp = await client.post(
                f"{API_PREFIX}/transactions/score",
                json=body,
                headers={**headers, "X-Idempotency-Key": str(uuid.uuid4())},
            )
            if resp.status_code == 200:
                data = resp.json()["data"]
                results.append((tx["external_tx_id"], data["decision"], data["risk_score"], data["risk_band"]))
                print(f"  {tx['external_tx_id']:>15s}  →  {data['decision']:>10s}  score={data['risk_score']:.2f}  band={data['risk_band']}")
            else:
                print(f"  {tx['external_tx_id']:>15s}  →  ERROR {resp.status_code}: {resp.text[:80]}")

    # 3. 汇总
    print("\n--- 汇总 ---")
    from collections import Counter
    decisions = Counter(r[1] for r in results)
    for d in ["ALLOW", "REVIEW", "CHALLENGE", "DENY"]:
        if d in decisions:
            print(f"  {d:>10s}: {decisions[d]} 笔")


if __name__ == "__main__":
    asyncio.run(main())
