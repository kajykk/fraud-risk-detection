"""core/exceptions 统一异常响应测试（D05 V1.1 §12）。

覆盖：
- FRDError 默认值与构造参数覆盖语义
- 典型子类的 HTTP 状态码
- FRDError / StarletteHTTPException / RequestValidationError /
  未捕获 Exception 四类全局 handler 的响应包络与错误码映射
- 校验错误序列化安全（errors[].ctx 异常对象不透传）
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Query
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from app.core.exceptions import (
    ForbiddenError,
    FRDError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    register_exception_handlers,
)


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-frd")
    async def boom_frd() -> None:
        raise NotFoundError("rule 42 missing")

    @app.get("/boom-http")
    async def boom_http() -> None:
        raise StarletteHTTPException(status_code=405, detail="GET not allowed")

    @app.get("/boom-http-unknown")
    async def boom_http_unknown() -> None:
        raise StarletteHTTPException(status_code=418)

    @app.get("/boom-unhandled")
    async def boom_unhandled() -> None:
        raise RuntimeError("unexpected")

    @app.get("/validate")
    async def validate(page: int = Query(ge=1)) -> None:
        return None

    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# 异常类属性
# --------------------------------------------------------------------------- #
def test_frd_error_defaults() -> None:
    err = FRDError()
    assert err.code == "INTERNAL_ERROR"
    assert err.http_status == 500
    assert err.message == "internal server error"
    assert err.data is None
    assert str(err) == "internal server error"


def test_frd_error_constructor_overrides_attributes() -> None:
    err = FRDError("custom message", code="CUSTOM", http_status=418, data={"reason": "tea"})
    assert err.message == "custom message"
    assert err.code == "CUSTOM"
    assert err.http_status == 418
    assert err.data == {"reason": "tea"}


@pytest.mark.parametrize(
    ("exc_cls", "status"),
    [
        (NotFoundError, 404),
        (ForbiddenError, 403),
        (RateLimitedError, 429),
        (ServiceUnavailableError, 503),
    ],
)
def test_error_subclass_declares_status_and_code(exc_cls: type[FRDError], status: int) -> None:
    exc = exc_cls()
    assert exc.http_status == status
    assert exc.code


# --------------------------------------------------------------------------- #
# 全局 handler 响应包络
# --------------------------------------------------------------------------- #
def test_frd_error_response_envelope() -> None:
    response = _client().get("/boom-frd")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["message"] == "rule 42 missing"
    assert body["data"] is None
    assert body["request_id"] == "-"  # 无 RequestIdMiddleware 时回退占位符
    assert body["trace_id"] == "-"
    assert body["timestamp"]


def test_starlette_http_exception_maps_to_business_code() -> None:
    response = _client().get("/boom-http")
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["message"] == "GET not allowed"


def test_unmapped_http_status_falls_back_to_internal_error() -> None:
    """未收录状态码（418）回退 INTERNAL_ERROR，detail 非空时原样透出。"""
    response = _client().get("/boom-http-unknown")
    assert response.status_code == 418
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["message"] == "I'm a Teapot"


def test_validation_errors_serialized_safely() -> None:
    """校验错误仅保留 loc/msg/type 可序列化字段，避免 ctx 异常对象导致 500。"""
    response = _client().get("/validate?page=0")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_PARAMS"
    errors = body["data"]["errors"]
    assert errors
    assert all(set(item) == {"loc", "msg", "type"} for item in errors)
    assert all(isinstance(item["msg"], str) for item in errors)
    assert any("page" in str(item["loc"]) for item in errors)


def test_unhandled_exception_returns_500_internal_error() -> None:
    """未捕获异常兜底为统一 500 包络，不泄漏内部错误信息。"""
    response = _client().get("/boom-unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["message"] == "internal server error"
