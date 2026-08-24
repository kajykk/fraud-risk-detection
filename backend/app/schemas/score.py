"""评分 SHAP schemas（D05 §4.7-4.9）。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ShapStatusEnum(StrEnum):
    """SHAP 计算状态。"""

    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ShapTriggerRequest(BaseModel):
    """POST /scores/{decision_id}/shap 请求体（D05 §4.7）。"""

    top_k: int = Field(default=10, ge=1, le=50)
    model_id: str | None = None


class ShapTriggerResponse(BaseModel):
    """POST /scores/{decision_id}/shap 响应。"""

    shap_task_id: str
    decision_id: str
    status: ShapStatusEnum = ShapStatusEnum.RUNNING
    estimated_seconds: int = 5
    websocket_event: str = "transaction.shap_ready"


class ShapStatus(BaseModel):
    """GET /scores/{decision_id}/shap/status 响应（D05 §4.8）。"""

    shap_task_id: str
    decision_id: str
    status: ShapStatusEnum
    progress: float = 0.0
    created_at: datetime | None = None
    completed_at: datetime | None = None
    result_url: str | None = None


class ShapFeature(BaseModel):
    """SHAP 单特征。"""

    name: str
    value: float | str | bool | None = None
    shap: float


class ShapResult(BaseModel):
    """GET /scores/{decision_id}/shap/result 响应（D05 §4.9）。"""

    shap_task_id: str
    decision_id: str
    model_id: str
    base_value: float
    prediction: float
    features: list[ShapFeature]
    completed_at: datetime


__all__ = ["ShapFeature", "ShapResult", "ShapStatus", "ShapStatusEnum", "ShapTriggerRequest", "ShapTriggerResponse"]
