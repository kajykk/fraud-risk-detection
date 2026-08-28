"""RequestIdMiddleware：X-Request-ID 注入（D05 V1.1 §2.2）。

- 从 X-Request-ID header 读取，未提供则生成 UUID
- 注入 request.state.request_id
- 响应头回写 X-Request-ID
- 绑定到 structlog contextvar，日志自动携带
"""

from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_context, get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# 客户端提供的 request_id 消毒：限长 + 字符白名单。
# 原实现直接采信 header，超长/控制字符/注入内容会原样进入日志与响应头
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")


def _sanitize_request_id(raw: str | None) -> str:
    """校验客户端 X-Request-ID；不合法则重新生成。"""
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """注入 X-Request-ID 到 request.state 与响应头。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        # trace_id 暂时复用 request_id（接入 OpenTelemetry 后由 OTel 注入）
        request.state.trace_id = request_id

        bind_request_context(request_id=request_id)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware"]
