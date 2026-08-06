"""AuditMiddleware：记录访问日志到 audit_logs（D03 §4.1 / D04 §3.7）。

设计要点：
- 仅记录写操作（POST/PUT/PATCH/DELETE）
- 哈希链：sequence_no（Redis INCR，降级 DB MAX）+ sha256 链，落库 audit_logs
- 审计写入失败仅记日志，不阻塞业务主路径
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
    """记录写操作到审计日志（哈希链落库）。"""

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
        """发送审计日志事件（哈希链落库，失败仅记日志）。"""
        from app.services.audit import record_audit_event

        tenant_id = getattr(request.state, "tenant_id", None)
        request_id = getattr(request.state, "request_id", "-")
        user_id = getattr(request.state, "user_id", None)
        status_code = response.status_code if response else 500

        action = f"{request.method}:{request.url.path}"
        resource_type = _infer_resource_type(request.url.path)
        resource_id = _extract_resource_id(request.url.path)

        current_hash = await record_audit_event(
            tenant_id=str(tenant_id) if tenant_id else "",
            user_id=user_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status_code=status_code,
            request_id=request_id,
            duration_ms=duration_ms,
        )

        # 同步结构化日志兜底（审计详情可查），并记录链哈希便于核验
        logger.info(
            "audit_event",
            tenant_id=tenant_id,
            request_id=request_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status_code=status_code,
            duration_ms=duration_ms,
            audit_hash=current_hash,
        )


def _extract_resource_id(path: str) -> str | None:
    """从路径提取资源 ID（最后一个非空段，排除 /api/v1/ 与操作词）。"""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3:
        return None
    candidate = parts[-1]
    if candidate in {
        "score", "shap", "status", "result", "comments", "close", "timeline",
        "promote", "rollback", "versions", "hits", "canary", "retire", "drift",
        "test", "deliveries", "feedback", "tasks", "community-detection", "login",
        "token", "refresh", "me", "profile", "related", "embedding",
    }:
        candidate = parts[-2] if len(parts) >= 4 else None
    return candidate


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
