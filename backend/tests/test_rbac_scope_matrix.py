"""RBAC 角色×scope×端点 对照测试（D05 §3.2 角色矩阵）。

静态契约校验（仅检查路由声明与角色矩阵，不触达 DB/Redis）：
1. 各端点声明的 scope 与预期一致（防止 consent:write/privacy:write 等
   旧命名回归，统一 pipl:* 命名）；
2. 角色矩阵（auth._default_scopes）为允许访问该端点的角色发放了所需 scope；
3. 未授权角色不持有该 scope（最小权限双向校验）。
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.api.v1.auth import _default_scopes

# (method, path, expected_scope, allowed_roles)
# allowed_roles 不含 TENANT_ADMIN：其持有 admin:*，天然放行所有端点
ENDPOINT_SCOPE_MATRIX: list[tuple[str, str, str, set[str]]] = [
    # ---- PIPL（pipl:* 命名：读=read / 写=write）----
    ("POST", "/api/v1/pipl/consent", "pipl:write", {"COMPLIANCE_OFFICER"}),
    ("POST", "/api/v1/pipl/consent/withdraw", "pipl:write", {"COMPLIANCE_OFFICER"}),
    ("GET", "/api/v1/pipl/consent/{user_id}", "pipl:read", {"COMPLIANCE_OFFICER"}),
    ("GET", "/api/v1/pipl/data-export", "pipl:write", {"COMPLIANCE_OFFICER"}),
    ("GET", "/api/v1/pipl/data-export/{task_id}/status", "pipl:read", {"COMPLIANCE_OFFICER"}),
    ("POST", "/api/v1/pipl/deletion", "pipl:write", {"COMPLIANCE_OFFICER"}),
    ("GET", "/api/v1/pipl/deletion/{request_id}/status", "pipl:read", {"COMPLIANCE_OFFICER"}),
    ("POST", "/api/v1/pipl/rectification", "pipl:write", {"COMPLIANCE_OFFICER"}),
    # ---- GNN 图分析（graph:*）----
    ("POST", "/api/v1/gnn/related", "graph:read", {"RISK_ANALYST", "RISK_MANAGER"}),
    (
        "GET",
        "/api/v1/gnn/community-detection/{task_id}",
        "graph:read",
        {"RISK_ANALYST", "RISK_MANAGER"},
    ),
    ("GET", "/api/v1/gnn/community/{community_id}", "graph:read", {"RISK_ANALYST", "RISK_MANAGER"}),
    ("POST", "/api/v1/gnn/embedding", "graph:write", {"RISK_ANALYST", "RISK_MANAGER"}),
    ("POST", "/api/v1/gnn/community-detection", "graph:write", {"RISK_ANALYST", "RISK_MANAGER"}),
]

ALL_ROLES = [
    "TENANT_ADMIN",
    "MERCHANT_ADMIN",
    "RISK_ANALYST",
    "RISK_MANAGER",
    "AUDITOR",
    "COMPLIANCE_OFFICER",
    "DEVOPS_OPS",
]


def _find_route(app, method: str, path: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    raise AssertionError(f"route not registered: {method} {path}")


def _required_scope(route: APIRoute) -> str | None:
    """从路由依赖中提取 require_scope(...) 声明的 scope。

    require_scope 工厂返回的闭包恰好捕获一个自由变量（scope 字符串），
    据此还原每个端点要求的 scope；未使用 require_scope 的端点返回 None。
    """
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        cells = getattr(dependant.call, "__closure__", None)
        if cells and len(cells) == 1:
            value = cells[0].cell_contents
            if isinstance(value, str) and ":" in value and "/" not in value:
                return value
        stack.extend(dependant.dependencies)
    return None


@pytest.mark.parametrize(
    ("method", "path", "expected_scope", "allowed_roles"),
    ENDPOINT_SCOPE_MATRIX,
)
def test_endpoint_declares_expected_scope(
    app,
    method: str,
    path: str,
    expected_scope: str,
    allowed_roles: set[str],
) -> None:
    """端点声明的 scope 必须与对照表一致。"""
    route = _find_route(app, method, path)
    assert _required_scope(route) == expected_scope, (
        f"{method} {path} 声明的 scope 与预期不符："
        f"expected={expected_scope}"
    )


@pytest.mark.parametrize(
    ("method", "path", "expected_scope", "allowed_roles"),
    ENDPOINT_SCOPE_MATRIX,
)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_matrix_grants_required_scopes(
    app,
    method: str,
    path: str,
    expected_scope: str,
    allowed_roles: set[str],
    role: str,
) -> None:
    """角色矩阵与端点 scope 双向对齐：
    - 允许访问的角色必须持有所需 scope；
    - 未授权的角色不得持有该 scope（TENANT_ADMIN 走 admin:* 放行，跳过）。
    """
    scopes = set(_default_scopes([role]))
    has_admin = "admin:*" in scopes
    if role in allowed_roles:
        assert expected_scope in scopes, f"{role} 应持有 {expected_scope} 以访问 {method} {path}"
    elif not has_admin:
        assert expected_scope not in scopes, (
            f"{role} 不应持有 {expected_scope}（{method} {path} 未授权该角色）"
        )


def test_no_legacy_pipl_scope_names(app) -> None:
    """全路由扫描：不允许出现 consent:* / privacy:* 旧命名。"""
    legacy = {"consent:read", "consent:write", "privacy:read", "privacy:write"}
    for route in app.routes:
        if isinstance(route, APIRoute):
            scope = _required_scope(route)
            assert scope not in legacy, f"{route.methods} {route.path} 仍在使用旧 scope: {scope}"


def test_gnn_scopes_only_on_graph_endpoints(app) -> None:
    """graph:* 只应出现在 /gnn 端点上（避免误挂到其他资源）。"""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        scope = _required_scope(route)
        if scope is not None and scope.startswith("graph:"):
            assert route.path.startswith("/api/v1/gnn"), (
                f"{route.methods} {route.path} 意外要求 {scope}"
            )
