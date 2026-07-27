"""AuditMiddleware：记录访问日志到 audit_logs（D03 §4.1 / D04 §3.7）。

设计要点：
- 异步 fire-and-forget，不阻塞主路径（< 1ms）
- 仅记录写操作（POST/PUT/PATCH/DELETE）与敏感读（GET /governance/audit-log）
- 审计日志走 Kafka topic frd.audit_log（ADR-014）；Kafka 不可用时降级到 Redis 队列
- sequence_no 由 Redis INCR 预分配（key: audit_seq:{tenant_id}，D04 §3.7）
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

# 触发审计的 HTTP 方法
AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    """记录写操作到审计日志（异步 fire-and-forget）。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method = request.method
        path = request.url.path

        # 健康检查放行
        if path in {"/health", "/ready", "/live", "/metrics"}:
            return await call_next(request)

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if method in AUDITED_METHODS:
                await self._emit_audit_log(request, response, duration_ms)

        return response  # type: ignore[return-value]

    async def _emit_audit_log(self, request: Request, response: Response | None, duration_ms: int) -> None:
        """发送审计日志事件到 Kafka / Redis 队列（fire-and-forget）。

        TODO（M2 实现）：
        1. 从 request.state 获取 tenant_id / user_id
        2. Redis INCR audit_seq:{tenant_id} 得到 sequence_no
        3. 构造哈希链 current_hash = sha256(prev_hash || canonical_json(payload))
        4. 发布到 Kafka topic frd.audit_log（ADR-014）
        5. Kafka Consumer 异步消费写入 audit_logs 表
        """
        tenant_id = getattr(request.state, "tenant_id", None)
        request_id = getattr(request.state, "request_id", "-")
        user_id = getattr(request.state, "user_id", None)
        status_code = response.status_code if response else 500

        audit_event = {
            "tenant_id": tenant_id,
            "user_id": str(user_id) if user_id else None,
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "action": f"{request.method}:{request.url.path}",
            "resource_type": _infer_resource_type(request.url.path),
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_id": request_id,
        }
        # 骨架阶段：仅 log，不写库不写 Kafka
        logger.info("audit_event", **audit_event)


def _infer_resource_type(path: str) -> str:
    """从路径推断资源类型。"""
    if path.startswith("/api/v1/transactions"):
        return "Transaction"
    if path.startswith("/api/v1/scores"):
        return "Score"
    if path.startswith("/api/v1/cases"):
        return "Case"
    if path.startswith("/api/v1/rules"):
        return "Rule"
    if path.startswith("/api/v1/models"):
        return "Model"
    if path.startswith("/api/v1/webhooks"):
        return "Webhook"
    if path.startswith("/api/v1/gnn"):
        return "Graph"
    if path.startswith("/api/v1/pipl"):
        return "PIPL"
    if path.startswith("/api/v1/auth"):
        return "Auth"
    return "Unknown"


__all__ = ["AuditMiddleware"]
