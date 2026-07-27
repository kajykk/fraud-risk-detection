# FRD 金融反欺诈系统 API 接口规范文档

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| V1.0 | 2026-07-27 | 邝振华 | 初版发布 |

---

## 目录

1. [概述](#1-概述)
2. [通用约定](#2-通用约定)
3. [认证与授权](#3-认证与授权)
4. [交易反欺诈接口](#4-交易反欺诈接口)
5. [规则引擎接口](#5-规则引擎接口)
6. [ML 模型接口](#6-ml-模型接口)
7. [GNN 团伙检测接口](#7-gnn-团伙检测接口)
8. [案件管理接口](#8-案件管理接口)
9. [报表与统计接口](#9-报表与统计接口)
10. [模型治理接口](#10-模型治理接口)
11. [Webhook 与回调](#11-webhook-与回调)
12. [错误码](#12-错误码)

---

## 1. 概述

### 1.1 设计目标

- **RESTful 风格**：资源导向，HTTP 谓词语义化，幂等设计
- **多租户隔离**：所有接口基于 `tenant_id` 进行行级隔离
- **低延迟**：评分接口 P99 < 200ms，规则接口 P99 < 50ms
- **可观测**：全链路 traceId，Prometheus 指标埋点
- **合规**：PCI-DSS v4.0 卡数据脱敏、PIPL 个人信息最小化

### 1.2 弔进策略

- API 版本路径：`/api/v1/`、`/api/v2/`（向后兼容 12 个月）
- 字段新增：兼容性扩展，不删除字段
- 字段废弃：先标记 `deprecated`，过渡 6 个月后下线

---

## 2. 通用约定

### 2.1 基础 URL

| 环境 | Base URL |
|------|----------|
| 生产 | `https://api.fraud-detection.example.com/api/v1` |
| 预发 | `https://staging-api.fraud-detection.example.com/api/v1` |
| 测试 | `https://test-api.fraud-detection.example.com/api/v1` |

### 2.2 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Authorization` | 是 | `Bearer {access_token}` |
| `X-Tenant-Id` | 是 | 租户 ID（UUID） |
| `X-Request-Id` | 否 | 请求追踪 ID（未提供则服务端生成） |
| `X-Idempotency-Key` | 写接口必填 | 幂等键（UUID v4），有效期 24h |
| `Content-Type` | 是 | `application/json; charset=utf-8` |
| `Accept-Language` | 否 | `zh-CN` / `en-US`，默认 `zh-CN` |

### 2.3 响应格式

```json
{
  "code": "OK",
  "message": "success",
  "data": { },
  "request_id": "01HXY9K8...",
  "trace_id": "trace-abc123",
  "timestamp": "2026-07-27T08:00:00Z"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | 业务状态码，`OK` 表示成功，其他见 §12 |
| message | string | 状态描述 |
| data | object/array/null | 业务数据 |
| request_id | string | 请求追踪 ID（与请求头一致） |
| trace_id | string | 分布式链路追踪 ID |
| timestamp | string | 响应时间（ISO 8601 UTC） |

### 2.4 分页约定

```json
{
  "data": {
    "items": [ ],
    "page": 1,
    "page_size": 20,
    "total": 156
  }
}
```

| 参数 | 默认 | 范围 |
|------|------|------|
| page | 1 | 1-10000 |
| page_size | 20 | 1-200 |
| sort | created_at:desc | 支持 `{field}:{asc|desc}` |

### 2.5 时间格式

- 请求/响应统一使用 **ISO 8601 UTC**（`2026-07-27T08:00:00Z`）
- 内部存储 `TIMESTAMPTZ`
- 报表查询参数支持 `YYYY-MM-DD`（按租户时区解释）

### 2.6 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 资源创建成功 |
| 204 | 成功无内容 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 资源冲突（幂等命中） |
| 422 | 业务校验失败 |
| 429 | 限流 |
| 500 | 服务端错误 |
| 503 | 服务不可用（熔断） |

### 2.7 限流

| 租户级别 | QPS | 突发 |
|----------|-----|------|
| Standard | 100 | 200 |
| Premium | 500 | 1000 |
| Enterprise | 2000 | 5000 |

响应头：
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1722057600
```

超限返回 `429` + `code: RATE_LIMITED`，建议退避重试 `Retry-After: 1`。

---

## 3. 认证与授权

### 3.1 OAuth 2.0 客户端凭证模式

适用于服务端到服务端调用（推荐）。

#### POST /auth/token

获取访问令牌。

**请求体**
```json
{
  "grant_type": "client_credentials",
  "client_id": "cli_frd_xxxxxxxx",
  "client_secret": "sk_xxxxxxxxxxxxxxxx",
  "scope": "transaction:score rule:read case:read"
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "access_token": "eyJhbGciOi...",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "transaction:score rule:read case:read"
  }
}
```

### 3.2 JWT 结构

```json
{
  "sub": "cli_frd_xxxxxxxx",
  "tenant_id": "tenant_001",
  "scope": "transaction:score rule:read",
  "iat": 1722054000,
  "exp": 1722057600,
  "jti": "jti-uuid"
}
```

### 3.3 Scope 权限矩阵

| Scope | 接口范围 |
|-------|----------|
| `transaction:score` | 交易评分、批量评分 |
| `transaction:read` | 交易查询 |
| `rule:read` / `rule:write` | 规则查询/维护 |
| `model:read` / `model:write` | 模型治理 |
| `case:read` / `case:write` | 案件管理 |
| `graph:read` | GNN 团伙查询 |
| `report:read` | 报表下载 |
| `admin:*` | 租户管理 |

### 3.4 失败响应

```json
{
  "code": "UNAUTHORIZED",
  "message": "invalid client credentials",
  "data": null,
  "request_id": "01HXY9K8..."
}
```

---

## 4. 交易反欺诈接口

### 4.1 POST /transactions/score

实时交易评分（核心接口）。

**请求体**
```json
{
  "external_tx_id": "TX20260727000001",
  "tx_type": "PURCHASE",
  "amount": 128800,
  "currency": "CNY",
  "occurred_at": "2026-07-27T08:00:00Z",
  "card_token": "tok_card_xxxxx",
  "card_bin": "622202",
  "card_last4": "1234",
  "merchant_id": "mch_001",
  "mcc": "5411",
  "acquirer_id": "acq_icbc",
  "device_fingerprint_hash": "fp_sha256_xxx",
  "ip_address": "1.2.3.4",
  "ip_geo": {"country": "CN", "city": "Shanghai"},
  "user_id": "user_999",
  "user_created_at": "2025-01-01T00:00:00Z",
  "channel": "WEB",
  "is_3ds_verified": true,
  "merchant_category": "grocery",
  "shipping_address_country": "CN",
  "billing_address_country": "CN"
}
```

**字段说明**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| external_tx_id | string | 是 | 外部交易号，唯一 |
| tx_type | enum | 是 | `PURCHASE`/`WITHDRAW`/`TRANSFER`/`REFUND` |
| amount | int64 | 是 | 金额（分） |
| currency | string | 是 | ISO 4217 三字母代码 |
| occurred_at | string | 是 | 交易发生时间 |
| card_token | string | 是 | 卡 Token（PCI-DSS 不能传 PAN） |
| card_bin / card_last4 | string | 是 | 用于风险判断 |
| merchant_id | string | 是 | 商户 ID |
| mcc | string | 是 | 商户类别码 |
| device_fingerprint_hash | string | 否 | 设备指纹哈希 |
| ip_address | string | 否 | IPv4/IPv6 |
| ip_geo | object | 否 | 地理位置 |
| user_id | string | 是 | 持卡人 ID |
| channel | enum | 否 | `WEB`/`APP`/`POS`/`API` |
| is_3ds_verified | bool | 否 | 是否通过 3DS 验证 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "decision": "ALLOW",
    "risk_score": 0.18,
    "risk_band": "LOW",
    "model_version": "ml_xgb_v3.2.1",
    "rule_hits": [],
    "explainability": {
      "top_features": [
        {"name": "amount_to_history_ratio", "value": 0.4, "shap": 0.08},
        {"name": "ip_country_mismatch", "value": 0, "shap": -0.02}
      ],
      "model_contribution": 0.65,
      "rule_contribution": 0.35
    },
    "latency_ms": 87,
    "case_id": null,
    "decision_id": "dec_01HXY9K8..."
  }
}
```

**decision 枚举**

| 值 | 含义 | 触发条件 |
|----|------|----------|
| `ALLOW` | 放行 | risk_score < 0.6 且无强阻断规则命中 |
| `REVIEW` | 人工审核 | 0.6 ≤ risk_score < 0.85 或命中复审规则 |
| `DENY` | 拒绝 | risk_score ≥ 0.85 或命中强阻断规则 |
| `CHALLENGE` | 二次验证 | 命中挑战规则（如 OTP/3DS） |

**risk_band**

- `LOW`：< 0.3
- `MEDIUM`：0.3 - 0.6
- `HIGH`：0.6 - 0.85
- `CRITICAL`：≥ 0.85

**幂等性**

- 基于 `X-Idempotency-Key` + `tenant_id` 幂等
- 24h 内重复请求返回首次结果（带 `X-Idempotent-Replay: true` 头）

**性能 SLA**

- P50 < 50ms
- P95 < 150ms
- P99 < 200ms

### 4.2 POST /transactions/score/batch

批量评分（最多 100 条/批）。

**请求体**
```json
{
  "transactions": [
    { "external_tx_id": "TX001", "...": "..." },
    { "external_tx_id": "TX002", "...": "..." }
  ]
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "results": [
      { "external_tx_id": "TX001", "decision": "ALLOW", "risk_score": 0.12 },
      { "external_tx_id": "TX002", "decision": "DENY", "risk_score": 0.91, "error": null }
    ],
    "success_count": 2,
    "failure_count": 0
  }
}
```

### 4.3 POST /transactions/feedback

反馈真实欺诈标签（用于模型再训练）。

**请求体**
```json
{
  "external_tx_id": "TX20260727000001",
  "label": "FRAUD",
  "label_source": "CHARGEBACK",
  "labeled_at": "2026-08-10T00:00:00Z",
  "evidence": "chargeback_case_12345"
}
```

**label 枚举**：`FRAUD` / `NOT_FRAUD` / `SUSPECTED`

### 4.4 GET /transactions/{external_tx_id}

查询交易评分详情。

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "external_tx_id": "TX20260727000001",
    "decision": "REVIEW",
    "risk_score": 0.72,
    "risk_band": "HIGH",
    "model_version": "ml_xgb_v3.2.1",
    "rule_hits": [
      {"rule_id": "R001", "rule_name": "大额夜间交易", "severity": "WARN"}
    ],
    "explainability": { "...": "..." },
    "case_id": "case_01HXY9K8...",
    "created_at": "2026-07-27T08:00:00Z"
  }
}
```

---

## 5. 规则引擎接口

### 5.1 GET /rules

分页查询规则列表。

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| status | enum | `DRAFT`/`ACTIVE`/`DISABLED` |
| severity | enum | `INFO`/`WARN`/`BLOCK` |
| channel | enum | 渠道过滤 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "items": [
      {
        "rule_id": "R001",
        "name": "大额夜间交易",
        "description": "单笔金额 > 5万 且 发生在 02:00-05:00",
        "dsl": "amount > 5000000 AND hour_of_day BETWEEN 2 AND 5",
        "severity": "WARN",
        "action": "REVIEW",
        "status": "ACTIVE",
        "version": 3,
        "hit_count_24h": 142,
        "false_positive_rate": 0.12,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z"
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 56
  }
}
```

### 5.2 POST /rules

新建规则。

**请求体**
```json
{
  "name": "新设备首笔大额交易",
  "description": "新设备首次绑卡后 10 分钟内单笔 > 1万",
  "dsl": "device_age_sec < 600 AND amount > 1000000",
  "severity": "BLOCK",
  "action": "DENY",
  "valid_from": "2026-08-01T00:00:00Z",
  "valid_to": null,
  "scope": {"channels": ["WEB", "APP"]}
}
```

**响应 201**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R057",
    "version": 1,
    "status": "DRAFT"
  }
}
```

### 5.3 POST /rules/{rule_id}:validate

DSL 语法校验与试运行（不生效）。

**请求体**
```json
{
  "dsl": "amount > 1000000 AND ip_country != 'CN'",
  "sample_transactions": ["TX001", "TX002"]
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "valid": true,
    "syntax_errors": [],
    "sample_hits": [
      {"external_tx_id": "TX001", "matched": true, "evaluated_at_ms": 2}
    ]
  }
}
```

### 5.4 POST /rules/{rule_id}:publish

发布规则（DRAFT → ACTIVE）。需要 `rule:write` scope 和复核人二次确认。

### 5.5 POST /rules/{rule_id}:disable

下线规则。

### 5.6 GET /rules/{rule_id}/hits

查询规则历史命中。

**查询参数**：`start_time`、`end_time`、`page`、`page_size`

---

## 6. ML 模型接口

### 6.1 GET /models

查询模型版本列表。

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "items": [
      {
        "model_id": "ml_xgb_v3.2.1",
        "name": "XGBoost 多模态融合",
        "version": "3.2.1",
        "type": "XGB",
        "status": "PRODUCTION",
        "auc": 0.942,
        "precision_at_1pct": 0.81,
        "recall_at_1pct": 0.65,
        "trained_at": "2026-07-01T00:00:00Z",
        "promoted_at": "2026-07-05T00:00:00Z",
        "traffic_share": 0.95
      },
      {
        "model_id": "ml_xgb_v3.3.0-canary",
        "status": "CANARY",
        "traffic_share": 0.05,
        "canary_started_at": "2026-07-20T00:00:00Z"
      }
    ]
  }
}
```

### 6.2 POST /models/{model_id}/explain

SHAP 可解释性查询。

**请求体**
```json
{
  "external_tx_id": "TX20260727000001",
  "top_k": 10
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.2.1",
    "base_value": -2.3,
    "prediction": 0.18,
    "features": [
      {"name": "amount_to_history_ratio", "value": 0.4, "shap": 0.08},
      {"name": "merchant_risk_score", "value": 0.35, "shap": 0.06}
    ]
  }
}
```

### 6.3 POST /models/{model_id}:canary

启动金丝雀发布。

**请求体**
```json
{
  "candidate_model_id": "ml_xgb_v3.3.0",
  "traffic_percentage": 5,
  "rollback_thresholds": {
    "precision_drop": 0.02,
    "latency_p99_ms": 250,
    "error_rate": 0.01
  },
  "observation_hours": 24
}
```

### 6.4 POST /models/{model_id}:promote

金丝雀晋升为生产。

### 6.5 POST /models/{model_id}:rollback

紧急回滚到上一稳定版本（带 kill switch）。

### 6.6 GET /models/{model_id}/drift

查询模型漂移指标（PSI / KL）。

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.2.1",
    "drift_status": "HEALTHY",
    "psi_1d": 0.08,
    "psi_7d": 0.15,
    "kl_divergence": 0.12,
    "last_checked_at": "2026-07-27T07:55:00Z",
    "feature_drifts": [
      {"feature": "amount", "psi": 0.21, "status": "WARNING"}
    ]
  }
}
```

---

## 7. GNN 团伙检测接口

### 7.1 POST /graph/detect

触发团伙检测任务（异步）。

**请求体**
```json
{
  "seed_account_id": "acc_001",
  "depth": 3,
  "time_window_hours": 168,
  "min_confidence": 0.6
}
```

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "task_id": "gnn_task_01HXY9K8...",
    "status": "RUNNING"
  }
}
```

### 7.2 GET /graph/tasks/{task_id}

查询团伙检测任务状态。

### 7.3 GET /graph/gangs/{gang_id}

查询团伙详情（节点 + 边）。

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "gang_id": "gang_001",
    "confidence": 0.87,
    "size": 12,
    "total_amount": 158000000,
    "detected_at": "2026-07-27T06:00:00Z",
    "nodes": [
      {"id": "acc_001", "type": "Account", "risk_score": 0.92},
      {"id": "dev_001", "type": "Device", "shared_accounts": 5}
    ],
    "edges": [
      {"from": "acc_001", "to": "dev_001", "type": "USES", "weight": 0.9}
    ],
    "case_id": "case_01HXY9K8..."
  }
}
```

### 7.4 GET /graph/accounts/{account_id}/subgraph

查询账户 N 跳子图。

**查询参数**：`depth`（1-3）、`edge_types`（USES/FROM_IP/...）

---

## 8. 案件管理接口

### 8.1 GET /cases

分页查询案件。

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| status | enum | `OPEN`/`IN_REVIEW`/`CONFIRMED`/`CLOSED`/`FALSE_ALARM` |
| priority | enum | `P0`/`P1`/`P2`/`P3` |
| assignee_id | string | 处理人 |
| created_after / created_before | string | 时间范围 |

### 8.2 POST /cases

手动创建案件。

**请求体**
```json
{
  "external_tx_id": "TX20260727000001",
  "priority": "P1",
  "assignee_id": "analyst_001",
  "description": "持卡人申诉否认交易",
  "tags": ["chargeback", "dispute"]
}
```

### 8.3 GET /cases/{case_id}

查询案件详情（含时间线）。

### 8.4 PATCH /cases/{case_id}

更新案件状态/优先级/处理人。

**请求体**
```json
{
  "status": "IN_REVIEW",
  "assignee_id": "analyst_002",
  "comment": "已联系持卡人核实"
}
```

### 8.5 POST /cases/{case_id}/comments

添加案件备注（含审计）。

### 8.6 POST /cases/{case_id}:close

关闭案件（必须填写结案结论）。

**请求体**
```json
{
  "conclusion": "CONFIRMED_FRAUD",
  "loss_amount": 50000,
  "recovery_amount": 0,
  "reportable_to_aml": true,
  "comment": "已上报反洗钱系统"
}
```

### 8.7 GET /cases/{case_id}/timeline

案件操作时间线（含审计追溯）。

---

## 9. 报表与统计接口

### 9.1 GET /reports/summary

查询租户风险概览。

**查询参数**：`start_date`、`end_date`、`group_by`（`day`/`week`/`month`）

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "summary": {
      "total_transactions": 1280000,
      "blocked_count": 8500,
      "reviewed_count": 15600,
      "confirmed_fraud_count": 230,
      "fraud_loss_prevented_cents": 5680000000,
      "actual_loss_cents": 12000000,
      "fraud_rate_bps": 1.8,
      "model_auc": 0.942
    },
    "trend": [
      {"date": "2026-07-20", "fraud_count": 12, "blocked_count": 1200},
      {"date": "2026-07-21", "fraud_count": 15, "blocked_count": 1180}
    ]
  }
}
```

### 9.2 GET /reports/rules/performance

规则性能排行（命中率、误报率）。

### 9.3 GET /reports/models/performance

模型性能报表（AUC / Precision / Recall / 延迟）。

### 9.4 POST /reports/export

异步导出报表。

**请求体**
```json
{
  "report_type": "TRANSACTION_DETAIL",
  "filters": {"start_date": "2026-07-01", "end_date": "2026-07-31"},
  "format": "CSV",
  "callback_url": "https://client.example.com/webhooks/report"
}
```

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "job_id": "job_export_01HXY9K8...",
    "estimated_seconds": 30
  }
}
```

### 9.5 GET /reports/jobs/{job_id}

查询导出任务状态与下载链接（预签名 URL，有效期 1h）。

---

## 10. 模型治理接口

### 10.1 GET /governance/audit-log

审计日志查询（满足 PIPL/反洗钱合规审计）。

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| actor_id | string | 操作人 |
| action | enum | `LOGIN`/`RULE_PUBLISH`/`MODEL_PROMOTE`/`CASE_CLOSE` 等 |
| resource_type | enum | 资源类型 |
| start_time / end_time | string | 时间范围 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "items": [
      {
        "log_id": "log_01HXY9K8...",
        "actor_id": "analyst_001",
        "actor_ip": "10.0.0.1",
        "action": "RULE_PUBLISH",
        "resource_type": "Rule",
        "resource_id": "R001",
        "before": {"status": "DRAFT"},
        "after": {"status": "ACTIVE"},
        "request_id": "01HXY9K8...",
        "created_at": "2026-07-27T08:00:00Z"
      }
    ],
    "page": 1,
    "page_size": 50,
    "total": 1245
  }
}
```

### 10.2 POST /governance/kill-switch

紧急熔断（关闭 ML 引擎，回退到纯规则模式）。

**请求体**
```json
{
  "reason": "ML engine abnormal",
  "duration_minutes": 60,
  "approver_id": "admin_001"
}
```

### 10.3 GET /governance/canaries

查询金丝雀发布状态。

### 10.4 POST /governance/canaries/{canary_id}:advance

推进金丝雀流量比例（5% → 25% → 100%）。

### 10.5 POST /governance/canaries/{canary_id}:rollback

回滚金丝雀。

---

## 11. Webhook 与回调

### 11.1 注册 Webhook

**POST /webhooks**
```json
{
  "url": "https://client.example.com/webhooks/frd",
  "events": ["transaction.blocked", "case.created", "model.promoted"],
  "secret": "whsec_xxxxx"
}
```

### 11.2 事件推送格式

```json
{
  "event_id": "evt_01HXY9K8...",
  "event_type": "transaction.blocked",
  "tenant_id": "tenant_001",
  "occurred_at": "2026-07-27T08:00:00Z",
  "data": {
    "external_tx_id": "TX20260727000001",
    "decision": "DENY",
    "risk_score": 0.91,
    "rule_hits": [{"rule_id": "R005"}]
  },
  "signature": "hmac-sha256=abcdef..."
}
```

### 11.3 重试策略

- 失败重试 5 次，退避：1s, 5s, 30s, 5min, 30min
- 客户端需返回 2xx 才视为成功
- 24h 内未投递成功则归档到死信队列

### 11.4 支持事件列表

| event_type | 触发场景 |
|------------|----------|
| `transaction.blocked` | 交易被 DENY |
| `transaction.review` | 交易进入人工审核 |
| `case.created` | 案件创建 |
| `case.assigned` | 案件被分配 |
| `case.closed` | 案件关闭 |
| `gang.detected` | GNN 检测到团伙 |
| `model.promoted` | 模型晋升生产 |
| `model.rolled_back` | 模型回滚 |
| `drift.alert` | 漂移告警 |
| `report.ready` | 报表导出完成 |

---

## 12. 错误码

### 12.1 业务错误码

| code | HTTP | 含义 | 重试 |
|------|------|------|------|
| `OK` | 200 | 成功 | - |
| `INVALID_PARAMS` | 400 | 参数错误 | 否 |
| `INVALID_JSON` | 400 | JSON 格式错误 | 否 |
| `UNAUTHORIZED` | 401 | 未认证 | 否 |
| `FORBIDDEN` | 403 | 无权限 | 否 |
| `SCOPE_INSUFFICIENT` | 403 | Scope 不足 | 否 |
| `NOT_FOUND` | 404 | 资源不存在 | 否 |
| `CONFLICT` | 409 | 资源冲突 | 否 |
| `IDEMPOTENT_REPLAY` | 409 | 幂等命中 | 否 |
| `VALIDATION_FAILED` | 422 | 业务校验失败 | 否 |
| `RULE_DSL_INVALID` | 422 | 规则 DSL 语法错误 | 否 |
| `MODEL_NOT_AVAILABLE` | 422 | 模型不可用 | 是 |
| `RATE_LIMITED` | 429 | 限流 | 是 |
| `CIRCUIT_OPEN` | 503 | 熔断 | 是（退避） |
| `INTERNAL_ERROR` | 500 | 服务端错误 | 是 |
| `TENANT_SUSPENDED` | 403 | 租户被冻结 | 否 |

### 12.2 错误响应示例

```json
{
  "code": "VALIDATION_FAILED",
  "message": "amount must be positive",
  "data": {
    "field_violations": [
      {"field": "amount", "rule": "min_value", "value": -100}
    ]
  },
  "request_id": "01HXY9K8...",
  "trace_id": "trace-abc123"
}
```

---

## 附录 A: OpenAPI Schema

完整 OpenAPI 3.1 规范见：`docs/openapi.yaml`（机器可读，可生成 SDK）。

## 附录 B: SDK 与示例

| 语言 | 仓库 | 安装 |
|------|------|------|
| Python | `frd-sdk-python` | `pip install frd-sdk` |
| Java | `frd-sdk-java` | Maven 依赖 |
| Go | `frd-sdk-go` | `go get github.com/frd/sdk-go` |
| Node.js | `frd-sdk-node` | `npm install frd-sdk` |

## 附录 C: 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| V1.0 | 2026-07-27 | 初版发布 |
