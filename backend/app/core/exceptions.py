"""自定义异常 + FastAPI handler（D05 V1.1 §12 错误码）。

提供统一错误响应格式：
    {
      "code": "...",
      "message": "...",
      "data": null,
      "request_id": "...",
      "trace_id": "...",
      "timestamp": "..."
    }
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# 自定义异常基类
# --------------------------------------------------------------------------- #
class FRDError(Exception):
    """FRD 业务异常基类。"""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    message: str = "internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
        data: Any | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.data = data
        super().__init__(self.message)


class NotFoundError(FRDError):
    code = "NOT_FOUND"
    http_status = 404
    message = "resource not found"


class ValidationFailedError(FRDError):
    code = "VALIDATION_FAILED"
    http_status = 422
    message = "validation failed"


class UnauthorizedError(FRDError):
    code = "UNAUTHORIZED"
    http_status = 401
    message = "unauthorized"


class ForbiddenError(FRDError):
    code = "FORBIDDEN"
    http_status = 403
    message = "forbidden"


class ConflictError(FRDError):
    code = "CONFLICT"
    http_status = 409
    message = "conflict"


class RateLimitedError(FRDError):
    code = "RATE_LIMITED"
    http_status = 429
    message = "rate limited"


class CircuitOpenError(FRDError):
    code = "CIRCUIT_OPEN"
    http_status = 503
    message = "circuit breaker open"


class KillSwitchActiveError(FRDError):
    code = "CIRCUIT_OPEN"
    http_status = 503
    message = "kill switch active"


# PIPL 相关错误
class SubjectNotVerifiedError(FRDError):
    code = "SUBJECT_NOT_VERIFIED"
    http_status = 422
    message = "subject identity verification failed"


class SubjectNotFoundError(FRDError):
    code = "SUBJECT_NOT_FOUND"
    http_status = 404
    message = "data subject not found"


class LegalHoldConflictError(FRDError):
    code = "LEGAL_HOLD_CONFLICT"
    http_status = 422
    message = "legal hold conflict"


class ConsentNotFoundError(FRDError):
    code = "CONSENT_NOT_FOUND"
    http_status = 404
    message = "consent not found"


class ConsentAlreadyWithdrawnError(FRDError):
    code = "CONSENT_ALREADY_WITHDRAWN"
    http_status = 422
    message = "consent already withdrawn"


class ConsentAlreadyGrantedError(FRDError):
    code = "CONSENT_ALREADY_GRANTED"
    http_status = 409
    message = "consent already granted"


class RectificationNotAllowedError(FRDError):
    code = "RECTIFICATION_NOT_ALLOWED"
    http_status = 422
    message = "rectification not allowed"


class PolicyVersionOutdatedError(FRDError):
    code = "POLICY_VERSION_OUTDATED"
    http_status = 422
    message = "policy version outdated"


# 规则相关错误
class RuleNotDraftError(FRDError):
    code = "RULE_NOT_DRAFT"
    http_status = 422
    message = "rule is not in DRAFT status"


class RuleNotDeletableError(FRDError):
    code = "RULE_NOT_DELETABLE"
    http_status = 422
    message = "rule is not deletable"


class RuleDSLInvalidError(FRDError):
    code = "RULE_DSL_INVALID"
    http_status = 422
    message = "rule DSL invalid"


class RuleStatusTransitionInvalidError(FRDError):
    code = "RULE_STATUS_TRANSITION_INVALID"
    http_status = 422
    message = "rule status transition invalid"


class ApproverRequiredError(FRDError):
    code = "APPROVER_REQUIRED"
    http_status = 422
    message = "approver required"


class CanaryThresholdNotMetError(FRDError):
    code = "CANARY_THRESHOLD_NOT_MET"
    http_status = 422
    message = "canary threshold not met"


class NoRollbackTargetError(FRDError):
    code = "NO_ROLLBACK_TARGET"
    http_status = 422
    message = "no rollback target"


class TargetVersionNotFoundError(FRDError):
    code = "TARGET_VERSION_NOT_FOUND"
    http_status = 404
    message = "target version not found"


# 模型相关错误
class ModelNotAvailableError(FRDError):
    code = "MODEL_NOT_AVAILABLE"
    http_status = 422
    message = "model not available"


class ModelArtifactsHashMismatchError(FRDError):
    code = "MODEL_ARTIFACTS_HASH_MISMATCH"
    http_status = 422
    message = "model artifacts hash mismatch"


class ModelVersionExistsError(FRDError):
    code = "MODEL_VERSION_EXISTS"
    http_status = 409
    message = "model version already exists"


class ModelMetricsInsufficientError(FRDError):
    code = "MODEL_METRICS_INSUFFICIENT"
    http_status = 422
    message = "model metrics insufficient"


class ModelHasTrafficError(FRDError):
    code = "MODEL_HAS_TRAFFIC"
    http_status = 422
    message = "model still has traffic"


class ModelNotDeletableError(FRDError):
    code = "MODEL_NOT_DELETABLE"
    http_status = 422
    message = "model not deletable"


class ModelNotEditableError(FRDError):
    code = "MODEL_NOT_EDITABLE"
    http_status = 422
    message = "model not editable"


class ArtifactsHashImmutableError(FRDError):
    code = "ARTIFACTS_HASH_IMMUTABLE"
    http_status = 422
    message = "artifacts hash immutable"


# SHAP 相关错误
class ShapNotReadyError(FRDError):
    code = "SHAP_NOT_READY"
    http_status = 409
    message = "shap not ready"


class ShapExpiredError(FRDError):
    code = "SHAP_EXPIRED"
    http_status = 410
    message = "shap expired"


class ShapComputationFailedError(FRDError):
    code = "SHAP_COMPUTATION_FAILED"
    http_status = 500
    message = "shap computation failed"


# --------------------------------------------------------------------------- #
# 统一响应构造
# --------------------------------------------------------------------------- #
def _build_error_response(
    request: Request,
    code: str,
    message: str,
    http_status: int,
    data: Any | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or "-"
    trace_id = getattr(request.state, "trace_id", None) or "-"
    return JSONResponse(
        status_code=http_status,
        content={
            "code": code,
            "message": message,
            "data": data,
            "request_id": request_id,
            "trace_id": trace_id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常 handler 到 FastAPI app。"""

    @app.exception_handler(FRDError)
    async def _frd_error_handler(request: Request, exc: FRDError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.exception("frd_error", code=exc.code, message=exc.message)
        else:
            logger.warning("frd_error", code=exc.code, message=exc.message, http_status=exc.http_status)
        return _build_error_response(request, exc.code, exc.message, exc.http_status, exc.data)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "INVALID_PARAMS",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "VALIDATION_FAILED",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            503: "CIRCUIT_OPEN",
        }
        code = code_map.get(exc.status_code, "INTERNAL_ERROR")
        message = str(exc.detail) if exc.detail else code.lower()
        return _build_error_response(request, code, message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _build_error_response(
            request,
            code="INVALID_PARAMS",
            message="request validation failed",
            http_status=422,
            data={"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return _build_error_response(
            request,
            code="INTERNAL_ERROR",
            message="internal server error",
            http_status=500,
        )


__all__ = [
    "FRDError",
    "ApproverRequiredError",
    "ArtifactsHashImmutableError",
    "CanaryThresholdNotMetError",
    "CircuitOpenError",
    "ConflictError",
    "ConsentAlreadyGrantedError",
    "ConsentAlreadyWithdrawnError",
    "ConsentNotFoundError",
    "ForbiddenError",
    "KillSwitchActiveError",
    "LegalHoldConflictError",
    "ModelArtifactsHashMismatchError",
    "ModelHasTrafficError",
    "ModelMetricsInsufficientError",
    "ModelNotAvailableError",
    "ModelNotDeletableError",
    "ModelNotEditableError",
    "ModelVersionExistsError",
    "NoRollbackTargetError",
    "NotFoundError",
    "PolicyVersionOutdatedError",
    "RateLimitedError",
    "RectificationNotAllowedError",
    "RuleDSLInvalidError",
    "RuleNotDeletableError",
    "RuleNotDraftError",
    "RuleStatusTransitionInvalidError",
    "ShapComputationFailedError",
    "ShapExpiredError",
    "ShapNotReadyError",
    "SubjectNotFoundError",
    "SubjectNotVerifiedError",
    "TargetVersionNotFoundError",
    "UnauthorizedError",
    "ValidationFailedError",
    "register_exception_handlers",
]
