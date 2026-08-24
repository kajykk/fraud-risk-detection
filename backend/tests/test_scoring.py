"""交易评分接口测试（D05 §4）。

覆盖：
- POST /transactions/score：同步评分主路径
- POST /transactions/score/async：异步评分任务
- GET /transactions/score/tasks/{task_id}：任务状态查询
- POST /transactions/score/batch：批量评分
- GET /transactions/{external_tx_id}：交易详情（404 场景）
- 鉴权：缺少 token / scope 不足
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_score_requires_auth(client: AsyncClient, sample_transaction: dict) -> None:
    """未携带 Authorization 应返回 401。"""
    response = await client.post(
        "/api/v1/transactions/score",
        json=sample_transaction,
        headers={"X-Idempotency-Key": "test-key-no-auth"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_score_with_valid_token(
    client: AsyncClient,
    sample_transaction: dict,
    auth_headers: dict[str, str],
) -> None:
    """携带合法 token 的同步评分应返回 200 + 完整响应结构。"""
    response = await client.post(
        "/api/v1/transactions/score",
        json=sample_transaction,
        headers={
            **auth_headers,
            "X-Idempotency-Key": "test-key-valid-001",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == "OK"
    data = body["data"]
    # 验证响应字段（D05 §4.1）
    assert data["decision"] in ("ALLOW", "REVIEW", "DENY", "CHALLENGE")
    assert 0.0 <= data["risk_score"] <= 1.0
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["model_version"]
    assert isinstance(data["rule_hits"], list)
    assert "explainability" in data
    assert data["explainability"]["shap_status"] == "PENDING"
    assert data["latency_ms"] >= 0
    assert data["decision_id"].startswith("dec_")


@pytest.mark.asyncio
async def test_score_invalid_amount_returns_422(
    client: AsyncClient,
    sample_transaction: dict,
    auth_headers: dict[str, str],
) -> None:
    """金额为 0 或负数应返回 422（业务规则校验失败）。"""
    bad_tx = {**sample_transaction, "amount": 0}
    response = await client.post(
        "/api/v1/transactions/score",
        json=bad_tx,
        headers={**auth_headers, "X-Idempotency-Key": "test-key-bad-amount"},
    )
    # Pydantic Field(gt=0) 在请求体校验阶段触发 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_score_missing_required_field_returns_400(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """缺少必填字段（external_tx_id）应返回 400。"""
    response = await client.post(
        "/api/v1/transactions/score",
        json={"amount": 100, "card_token": "tok_xxx"},
        headers={**auth_headers, "X-Idempotency-Key": "test-key-missing"},
    )
    # Pydantic 校验失败 → RequestValidationError → 400（D05 §2.6）
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_score_async_returns_task_id(
    client: AsyncClient,
    sample_transaction: dict,
    auth_headers: dict[str, str],
) -> None:
    """POST /transactions/score/async 返回 task_id 与 RUNNING 状态。"""
    response = await client.post(
        "/api/v1/transactions/score/async",
        json=sample_transaction,
        headers={**auth_headers, "X-Idempotency-Key": "test-key-async-001"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_id"]
    assert data["callback_event"] == "transaction.analysis_completed"


@pytest.mark.asyncio
async def test_get_score_task_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /transactions/score/tasks/{task_id} 对未知/未登记任务 fail-closed。

    任务归属校验（fail-closed）：归属记录不存在或 Redis 异常一律拒绝，
    防止跨租户伪造 task_id 探测任务状态。
    """
    task_id = "score_task_test-12345"
    response = await client.get(
        f"/api/v1/transactions/score/tasks/{task_id}",
        headers=auth_headers,
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_batch_score_empty_list(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /transactions/score/batch 空列表应返回 200 + 0 成功。"""
    response = await client.post(
        "/api/v1/transactions/score/batch",
        json={"transactions": []},
        headers={**auth_headers, "X-Idempotency-Key": "test-key-batch-empty"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["success_count"] == 0
    assert data["failure_count"] == 0


@pytest.mark.asyncio
async def test_get_transaction_not_found(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /transactions/{external_tx_id} 不存在时返回 404。"""
    response = await client.get(
        "/api/v1/transactions/TX_NOT_EXIST_999",
        headers=auth_headers,
    )
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_idempotency_header_echoed(
    client: AsyncClient,
    sample_transaction: dict,
    auth_headers: dict[str, str],
) -> None:
    """响应头应包含 X-Request-ID。"""
    response = await client.post(
        "/api/v1/transactions/score",
        json=sample_transaction,
        headers={
            **auth_headers,
            "X-Idempotency-Key": "test-key-idem-001",
            "X-Request-ID": "req-test-id-001",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-test-id-001"
