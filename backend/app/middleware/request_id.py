"""RequestIdMiddleware：X-Request-ID 注入（D05 V1.1 §2.2）。

- 从 X-Request-ID header 读取，未提供则生成 UUID
- 注入 request.state.request_id
- 响应头回写 X-Request-ID
- 绑定到 structlog contextvar，日志自动携带
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_context, get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """注入 X-Request-ID 到 request.state 与响应头。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        # trace_id 暂时复用 request_id（接入 OpenTelemetry 后由 OTel 注入）
        request.state.trace_id = request_id

        bind_request_context(request_id=request_id)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware"]
