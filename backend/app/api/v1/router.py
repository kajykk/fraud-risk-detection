"""v1 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    cases,
    gnn,
    health,
    models,
    pipl,
    reports,
    rules,
    scores,
    transactions,
    webhooks,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
router.include_router(scores.router, prefix="/scores", tags=["scores"])
router.include_router(cases.router, prefix="/cases", tags=["cases"])
router.include_router(rules.router, prefix="/rules", tags=["rules"])
router.include_router(models.router, prefix="/models", tags=["models"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
router.include_router(gnn.router, prefix="/gnn", tags=["gnn"])
router.include_router(pipl.router, prefix="/pipl", tags=["pipl"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])

__all__ = ["router"]
