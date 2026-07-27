# FRD 金融反欺诈系统 API 接口规范文档

| 项 | 值 |
|---|---|
| 文档编号 | FRD-D05-V1.1 |
| 文档状态 | 修订版 |
| 编制日期 | 2026-07-27 |
| 编制人 | 邝振华 + AI 协作 |
| 依据基准 | FRD-BASELINE-V1.1 |

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| V1.0 | 2026-07-27 | 邝振华 | 初版发布 |
| V1.1 | 2026-07-27 | 邝振华 + AI 协作 | 依据 FRD-BASELINE-V1.1 修订：① 新增 §13 PIPL 数据主体权利接口（`/api/v1/pipl/*` 8 个）；② §5 规则补齐 CRUD 闭环（POST/GET/PUT/DELETE + `/versions`/`/promote`/`/rollback`）；③ §6 模型补齐 CRUD 闭环（POST/GET/PUT/DELETE + `/canary`/`/promote`/`/rollback`/`/retire`）；④ §4 SHAP 改异步（`POST /scores/{id}/shap` + `/status` + `/result` + WebSocket 推送）；⑤ §7 GNN 接口分流到 `/api/v1/gnn/*` 命名空间（`/related`/`/embedding`/`/community-detection`/`/community`）；⑥ §11 Webhook CRUD 补齐 `/test`/`/deliveries`，签名算法明确（HMAC-SHA256，防重放 5min，重试 1m/5m/30m/2h/12h 入死信队列）；⑦ §3.4 新增角色到 Scope 矩阵（6 个角色）；⑧ 枚举/字段/幂等/限流统一对齐基准；⑨ 错别字修正（弔进→演进） |

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
13. [PIPL 数据主体权利接口](#13-pipl-数据主体权利接口)

---

## 1. 概述

### 1.1 设计目标

- **RESTful 风格**：资源导向，HTTP 谓词语义化，幂等设计
- **RESTful + WebSocket 双通道**：实时评分走 HTTP，长耗时异步任务（SHAP、深度分析、报表导出）通过 WebSocket 推送完成事件，亦可轮询
- **多租户隔离**：所有接口基于 `tenant_id` 进行行级隔离
- **低延迟**：评分接口 P99 < 200ms，规则接口 P99 < 50ms
- **可观测**：全链路 traceId，Prometheus 指标埋点
- **合规**：PCI-DSS v4.0 卡数据脱敏、PIPL 个人信息最小化、反洗钱 7 年审计保留

### 1.2 演进策略

- API 版本路径：`/api/v1/`、`/api/v2/`（向后兼容 12 个月）
- 字段新增：兼容性扩展，不删除字段
- 字段废弃：先标记 `deprecated`，过渡 6 个月后下线
- 路径命名：V1.1 起统一采用斜杠子资源命名（`/rules/{id}/promote`），V1.0 的冒号动作命名（`/rules/{id}:publish`）标记为 `deprecated`，6 个月后下线

### 1.3 与 V1.0 的兼容性

| 变更类型 | 兼容性 | 说明 |
|----------|--------|------|
| 新增端点 | 完全兼容 | `/pipl/*`、`/gnn/*`、`/scores/{id}/shap*`、`/webhooks/{id}/test` 等 |
| SHAP 改异步 | 行为变更 | V1.0 `POST /models/{model_id}/explain` 保留兼容 6 个月，新调用推荐走 `POST /scores/{id}/shap` |
| 路径命名 | 双轨过渡 | 冒号动作命名 `deprecated`，斜杠子资源为新标准 |
| 枚举值修正 | 兼容 | `model_status` 由 `PRODUCTION` 修正为 `ACTIVE`，服务端做映射兼容 |

---

## 2. 通用约定

### 2.1 基础 URL

| 环境 | Base URL |
|------|----------|
| 生产 | `https://api.fraud-detection.example.com/api/v1` |
| 预发 | `https://staging-api.fraud-detection.example.com/api/v1` |
| 测试 | `https://test-api.fraud-detection.example.com/api/v1` |

WebSocket 端点：`wss://api.fraud-detection.example.com/api/v1/ws`（鉴权：`?access_token={jwt}`）

### 2.2 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Authorization` | 是 | `Bearer {access_token}` 或 `ApiKey {api_key}` |
| `X-Tenant-Id` | 仅 admin scope 跨租户操作 | 租户 ID（UUID）；普通租户调用由服务端从凭据提取，客户端无需传 |
| `X-Request-Id` | 否 | 请求追踪 ID（未提供则服务端生成） |
| `X-Idempotency-Key` | 写接口必填 | 幂等键（UUID v4），有效期 24h |
| `Content-Type` | 是 | `application/json; charset=utf-8` |
| `Accept-Language` | 否 | `zh-CN` / `en-US`，默认 `zh-CN` |

**`tenant_id` 来源优先级**（统一口径）：

1. JWT 内 `tenant_id` 声明优先
2. API Key 绑定的 `tenant_id` 次之
3. `X-Tenant-Id` 请求头**仅**在 `admin:*` scope 跨租户运维操作时使用，且服务端必须校验调用者具备跨租户权限；普通租户调用传该头将被忽略并记录审计日志

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

### 2.6 HTTP 状态码与幂等语义

| 状态码 | 含义 |
|--------|------|
| 200 | 成功（含幂等命中重放） |
| 201 | 资源创建成功 |
| 202 | 异步任务已接受 |
| 204 | 成功无内容 |
| 400 | 请求语法/类型错误（JSON 格式错、字段类型不符） |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 409 | 资源冲突（版本号/唯一约束冲突） |
| 422 | 业务规则校验失败（语义正确但违反业务规则） |
| 429 | 限流 |
| 500 | 服务端错误 |
| 503 | 服务不可用（熔断） |

**400 与 422 边界**：

- `400`：语法/类型错（如非法 JSON、`amount` 传字符串、枚举值拼写错）
- `422`：业务规则错（如 `amount` 为负数、状态机非法迁移、规则 DSL 语义错）

**幂等语义**（统一口径）：

- 基于 `X-Idempotency-Key` + `tenant_id` 幂等，有效期 24h
- 幂等命中：**HTTP 200** + 首次结果原样返回 + 响应头 `X-Idempotent-Replay: true`
- 不再使用 `409 IDEMPOTENT_REPLAY` 错误码

### 2.7 限流与重试

| 租户级别 | QPS | 突发 |
|----------|-----|------|
| STANDARD | 100 | 200 |
| PRO | 500 | 1000 |
| ENTERPRISE | 2000 | 5000 |

> 注：`tenant.plan` 枚举值统一大写（`STANDARD` / `PRO` / `ENTERPRISE`），对齐基准 V1.1 §3.6（`premium` 已改名 `PRO`）。

**限流响应头**（所有 429 响应必含）：

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1722057600
Retry-After: 1
```

**重试语义**：

- 适用场景：`429` 限流、`5xx` 服务端错误、`503` 熔断
- 算法：指数退避 + 抖动（full jitter）
- 最大重试次数：5 次
- 不应重试：`4xx`（除 `429` 外）、`422` 业务校验失败

### 2.8 WebSocket 通道

> ⏳ **规划接口，代码未实现**（截至 2026-07-27）：后端无 WS 端点（前端已有 utils/websocket.ts 客户端）。计划 M5 Beta 交付。

**连接**：`wss://api.fraud-detection.example.com/api/v1/ws?access_token={jwt}`

**消息格式**：

```json
{
  "event_id": "evt_01HXY9K8...",
  "event_type": "transaction.shap_ready",
  "tenant_id": "tenant_001",
  "occurred_at": "2026-07-27T08:00:05Z",
  "data": { "decision_id": "dec_01HXY9K8...", "shap_status": "READY" }
}
```

**订阅过滤**：客户端可在连接后发送 `subscribe` 消息指定 `event_types` 与 `decision_ids`，服务端按租户隔离推送。

**心跳**：30s 一次 ping/pong，60s 无响应服务端主动断开。

**适用事件**：`transaction.shap_ready`、`transaction.analysis_completed`、`report.ready`、`privacy.export.ready`、`privacy.deletion.completed`、`gang.detected`。

---

## 3. 认证与授权

### 3.1 OAuth 2.0 客户端凭证模式

适用于服务端到服务端调用（推荐）。同时支持 API Key（`Authorization: ApiKey {api_key}`）与 JWT Bearer 两种凭据形态。

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
    "expires_in": 1800,
    "scope": "transaction:score rule:read case:read"
  }
}
```

### 3.2 JWT 结构

```json
{
  "sub": "cli_frd_xxxxxxxx",
  "tenant_id": "tenant_001",
  "roles": ["RISK_ANALYST"],
  "scope": "transaction:score rule:read",
  "iat": 1722054000,
  "exp": 1722057600,
  "jti": "jti-uuid"
}
```

### 3.3 Scope 权限矩阵

| Scope | 接口范围 |
|-------|----------|
| `transaction:score` | 交易评分、批量评分、异步评分、SHAP 触发 |
| `transaction:read` | 交易查询、SHAP 状态/结果查询 |
| `rule:read` / `rule:write` | 规则查询 / 规则维护（含 POST/PUT/DELETE/版本/灰度/回滚） |
| `model:read` / `model:write` | 模型查询 / 模型注册、灰度、晋升、回滚、退役 |
| `case:read` / `case:write` | 案件管理 |
| `graph:read` / `graph:write` | GNN 子图查询 / 团伙检测任务、GraphSAGE 嵌入 |
| `report:read` / `report:write` | 报表下载 / 报表导出 |
| `webhook:write` | Webhook 注册、更新、注销、签名验证、测试、投递查询 |
| `governance:write` | 紧急熔断、金丝雀推进/回滚 |
| `consent:write` | 同意授予/撤回/查询 |
| `privacy:write` | 数据导出/删除/更正申请 |
| `admin:*` | 租户管理（跨租户运维） |

### 3.4 角色 → Scope 映射矩阵

> 角色与 Scope 解耦：JWT `roles` 声明用户角色，服务端按角色 → Scope 映射授权。一个用户可兼任多个角色。

| Scope \\ 角色 | TENANT_ADMIN | MERCHANT_ADMIN | RISK_ANALYST | RISK_MANAGER | AUDITOR | COMPLIANCE_OFFICER |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `transaction:score` | ✓ | ✓ | ✓ | ✓ | — | — |
| `transaction:read` | ✓ | ✓ | ✓ | ✓ | ✓（只读） | ✓（只读） |
| `rule:read` | ✓ | — | ✓ | ✓ | ✓（只读） | — |
| `rule:write` | ✓ | — | — | ✓ | — | — |
| `model:read` | ✓ | — | ✓ | ✓ | ✓（只读） | — |
| `model:write` | ✓ | — | — | ✓ | — | — |
| `case:read` | ✓ | ✓（本商户） | ✓ | ✓ | ✓ | ✓ |
| `case:write` | ✓ | — | ✓ | ✓ | — | — |
| `graph:read` | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `graph:write` | ✓ | — | — | ✓ | — | — |
| `report:read` | ✓ | ✓（本商户） | ✓ | ✓ | ✓ | ✓ |
| `report:write` | ✓ | — | ✓ | ✓ | — | — |
| `webhook:write` | ✓ | ✓（本商户） | — | — | — | — |
| `governance:write` | ✓ | — | — | ✓ | — | ✓（仅 kill-switch） |
| `consent:write` | ✓ | — | — | — | — | ✓ |
| `privacy:write` | ✓ | — | — | — | — | ✓ |
| `admin:*` | ✓ | — | — | — | — | — |

**角色职责**：

| 角色 | 职责 |
|------|------|
| `TENANT_ADMIN` | 租户管理员，全权管理本租户资源、密钥、Webhook、模型治理 |
| `MERCHANT_ADMIN` | 商户管理员，仅管理本商户交易与 Webhook，不能管理规则/模型 |
| `RISK_ANALYST` | 风控分析师，可读写案件、查询规则/模型/图谱、生成报表 |
| `RISK_MANAGER` | 风控经理，规则/模型变更审批、灰度推进、紧急熔断 |
| `AUDITOR` | 审计员，全只读权限，可查看审计日志，不可写任何资源 |
| `COMPLIANCE_OFFICER` | 合规官，处理 PIPL 数据主体权利请求、同意管理、合规熔断 |

#### DEVOPS_OPS 角色接入说明

DEVOPS_OPS 角色不通过常规 JWT 用户认证接入 API，而是通过 K8s ServiceAccount + 短期 OAuth2 Client Credentials 授予受限 scope，仅访问运维相关端点：
- `metrics:read` — `GET /api/v1/ops/metrics`
- `health:read` — `GET /api/v1/ops/health`、`GET /api/v1/ops/ready`
- `killswitch:write` — `POST /api/v1/ops/kill-switch/{scope}/{action}`（L1-L4 作用域，需真人二次确认）
- `drift:read` — `GET /api/v1/models/{id}/drift`

DEVOPS_OPS 操作全部记入 audit_logs，Kill Switch 类操作需真人（邝振华）短信二次确认。

### 3.5 失败响应

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

**Scope**：`transaction:score`

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
  "shipping_country": "CN",
  "billing_country": "CN",
  "note_text": "用户备注（脱敏）",
  "metadata": {}
}
```

**字段说明**（对齐基准 §4.1 transactions 表）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| external_tx_id | string | 是 | 外部交易号，唯一 |
| tx_type | enum | 是 | `PURCHASE` / `WITHDRAW` / `REFUND` / `TRANSFER` / `TOPUP` / `PAYMENT` |
| amount | int64 | 是 | 金额（分），必须 > 0 |
| currency | string | 是 | ISO 4217 三字母代码，默认 `CNY` |
| occurred_at | string | 是 | 交易发生时间 |
| card_token | string | 是 | 卡 Token（PCI-DSS 不能传 PAN） |
| card_bin | string(6) | 是 | 卡 BIN |
| card_last4 | string(4) | 是 | 卡末四位 |
| merchant_id | string | 否 | 商户 ID |
| mcc / merchant_category | string | 否 | 商户类别码 / 业务类别 |
| acquirer_id | string(50) | 否 | 收单机构 ID |
| device_fingerprint_hash | string | 否 | 设备指纹哈希 |
| ip_address | string | 否 | IPv4/IPv6 |
| ip_geo | object | 否 | 地理位置 |
| user_id / user_account_id | string | 是 | 持卡人 ID（脱敏存储） |
| user_created_at | string | 否 | 用户注册时间（账户年龄特征） |
| channel | enum | 否 | `WEB` / `APP` / `POS` / `API` / `QR` |
| is_3ds_verified | bool | 否 | 是否通过 3DS 验证 |
| shipping_country | string(2) | 否 | 货运地址国别（ISO 3166-1 alpha-2） |
| billing_country | string(2) | 否 | 账单地址国别 |
| note_text | string | 否 | 备注（落库前脱敏） |
| metadata | object | 否 | 扩展字段（JSONB） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "decision": "ALLOW",
    "risk_score": 0.1820,
    "risk_band": "LOW",
    "model_version": "ml_xgb_v3.2.1",
    "rule_hits": [],
    "explainability": {
      "model_contribution": 0.65,
      "rule_contribution": 0.35,
      "shap_status": "PENDING",
      "shap_task_id": "shap_task_01HXY9K8..."
    },
    "latency_ms": 87,
    "case_id": null,
    "decision_id": "dec_01HXY9K8..."
  }
}
```

> SHAP 异步说明（对齐 D03 ADR-007）：评分响应**不再同步返回** `top_features`，改为返回 `shap_status` 与 `shap_task_id`：
> - `shap_status = PENDING`：SHAP 异步计算中，可通过 `GET /scores/{decision_id}/shap/status` 查询，或订阅 WebSocket `transaction.shap_ready` 事件
> - `shap_status = READY`：SHAP 已就绪，通过 `GET /scores/{decision_id}/shap/result` 拉取

**`decision` 枚举**（对齐基准 §3.1）

| 值 | 含义 | 触发条件 |
|----|------|----------|
| `ALLOW` | 放行 | risk_score < 0.30 且无强阻断规则命中 |
| `REVIEW` | 人工审核 | 0.30 ≤ risk_score < 0.60 或命中复审规则 |
| `DENY` | 拒绝 | risk_score ≥ 0.85 或命中强阻断规则 |
| `CHALLENGE` | 二次验证 | 命中挑战规则（如 OTP/3DS） |

**`risk_band` 与 `risk_score` 类型**（对齐基准 §3.5、§4.2 与 D04）

| 字段 | 类型 | 范围 |
|------|------|------|
| `risk_score` | DECIMAL(5,4) | 0.0000 - 1.0000 |
| `risk_band` | enum | `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` |

**`risk_band` 阈值**：

- `LOW`：< 0.30
- `MEDIUM`：0.30 - 0.60
- `HIGH`：0.60 - 0.85
- `CRITICAL`：≥ 0.85

**幂等性**

- 基于 `X-Idempotency-Key` + `tenant_id` 幂等，有效期 24h
- 幂等命中：HTTP 200 + 首次结果原样返回 + 响应头 `X-Idempotent-Replay: true`

**性能 SLA**

- P50 < 50ms
- P95 < 150ms
- P99 < 200ms

### 4.2 POST /transactions/score/async

异步评分（深度分析路径，对齐 D03 ADR-002）。适用于需要 GNN 团伙检测、跨账户聚合、历史行为深度分析等耗时场景。

**Scope**：`transaction:score`

**请求体**：同 §4.1，可选附加 `analysis_depth` 字段：

```json
{
  "external_tx_id": "TX20260727000001",
  "tx_type": "PURCHASE",
  "amount": 128800,
  "...": "...",
  "analysis_depth": "DEEP"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| analysis_depth | enum | 否 | `STANDARD`（默认）/ `DEEP`（含 GNN 团伙检测 + 历史聚合） |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "task_id": "score_task_01HXY9K8...",
    "status": "RUNNING",
    "estimated_seconds": 30,
    "callback_event": "transaction.analysis_completed"
  }
}
```

> 深度分析完成后，结果通过 Webhook 事件 `transaction.analysis_completed` 或 WebSocket 推送，亦可轮询任务查询接口。

### 4.3 GET /transactions/score/tasks/{task_id}

查询异步评分任务状态。

**Scope**：`transaction:score`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "task_id": "score_task_01HXY9K8...",
    "status": "SUCCEEDED",
    "result": {
      "decision": "DENY",
      "risk_score": 0.9120,
      "risk_band": "CRITICAL",
      "model_version": "ml_xgb_v3.2.1",
      "rule_hits": [{"rule_id": "R005", "rule_name": "团伙账户关联", "severity": "BLOCK"}],
      "explainability": {
        "model_contribution": 0.72,
        "rule_contribution": 0.28,
        "shap_status": "READY",
        "shap_task_id": "shap_task_01HXY9K8..."
      },
      "case_id": "case_01HXY9K8...",
      "decision_id": "dec_01HXY9K8..."
    },
    "created_at": "2026-07-27T08:00:00Z",
    "completed_at": "2026-07-27T08:00:28Z"
  }
}
```

**task status 枚举**：`RUNNING` / `SUCCEEDED` / `FAILED` / `TIMEOUT`

### 4.4 POST /transactions/score/batch

批量评分（最多 100 条/批，同步路径，仅做规则 + ML 主模型评分）。

**Scope**：`transaction:score`

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
      { "external_tx_id": "TX001", "decision": "ALLOW", "risk_score": 0.1200, "risk_band": "LOW" },
      { "external_tx_id": "TX002", "decision": "DENY", "risk_score": 0.9100, "risk_band": "CRITICAL", "error": null }
    ],
    "success_count": 2,
    "failure_count": 0
  }
}
```

### 4.5 POST /transactions/feedback

反馈真实欺诈标签（用于模型再训练）。

**Scope**：`transaction:score`

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

### 4.6 GET /transactions/{external_tx_id}

查询交易评分详情。

**Scope**：`transaction:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "external_tx_id": "TX20260727000001",
    "decision": "REVIEW",
    "risk_score": 0.7200,
    "risk_band": "HIGH",
    "model_version": "ml_xgb_v3.2.1",
    "rule_hits": [
      {"rule_id": "R001", "rule_name": "大额夜间交易", "severity": "WARN"}
    ],
    "explainability": {
      "model_contribution": 0.65,
      "rule_contribution": 0.35,
      "shap_status": "READY",
      "shap_task_id": "shap_task_01HXY9K8..."
    },
    "tx_type": "PURCHASE",
    "channel": "WEB",
    "is_3ds_verified": true,
    "user_created_at": "2025-01-01T00:00:00Z",
    "acquirer_id": "acq_icbc",
    "shipping_country": "CN",
    "billing_country": "CN",
    "case_id": "case_01HXY9K8...",
    "decision_id": "dec_01HXY9K8...",
    "created_at": "2026-07-27T08:00:00Z"
  }
}
```

### 4.7 POST /scores/{decision_id}/shap

触发 SHAP 异步计算（V1.1 新增，对齐 D03 ADR-007）。原 V1.0 `POST /models/{model_id}/explain` 同步接口标记为 `deprecated`，6 个月后下线。

**Scope**：`transaction:read`

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| decision_id | string | 是 | 评分决策 ID（来自 §4.1 响应） |

**请求体**
```json
{
  "top_k": 10,
  "model_id": "ml_xgb_v3.2.1"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| top_k | int | 否 | 返回前 K 个特征，默认 10，最大 50 |
| model_id | string | 否 | 指定模型版本，默认使用产生该 decision 的模型 |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "shap_task_id": "shap_task_01HXY9K8...",
    "decision_id": "dec_01HXY9K8...",
    "status": "RUNNING",
    "estimated_seconds": 5,
    "websocket_event": "transaction.shap_ready"
  }
}
```

**幂等性**：同一 `decision_id` 重复触发，若已有完成任务则直接返回 `status: READY` + `result_url`，不会重复计算。

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `NOT_FOUND` | 404 | decision_id 不存在 |
| `MODEL_NOT_AVAILABLE` | 422 | 关联模型已 RETIRED 或不可用 |
| `SHAP_COMPUTATION_FAILED` | 500 | SHAP 计算异常（同步错误） |

### 4.8 GET /scores/{decision_id}/shap/status

查询 SHAP 计算状态。

**Scope**：`transaction:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "shap_task_id": "shap_task_01HXY9K8...",
    "decision_id": "dec_01HXY9K8...",
    "status": "READY",
    "progress": 1.0,
    "created_at": "2026-07-27T08:00:00Z",
    "completed_at": "2026-07-27T08:00:05Z",
    "result_url": "/api/v1/scores/dec_01HXY9K8.../shap/result"
  }
}
```

**status 枚举**：`RUNNING` / `READY` / `FAILED` / `EXPIRED`（结果保留 7 天，过期自动清理）

### 4.9 GET /scores/{decision_id}/shap/result

获取 SHAP 计算结果（计算完成后）。

**Scope**：`transaction:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "shap_task_id": "shap_task_01HXY9K8...",
    "decision_id": "dec_01HXY9K8...",
    "model_id": "ml_xgb_v3.2.1",
    "base_value": -2.3,
    "prediction": 0.1820,
    "features": [
      {"name": "amount_to_history_ratio", "value": 0.4, "shap": 0.08},
      {"name": "merchant_risk_score", "value": 0.35, "shap": 0.06},
      {"name": "ip_country_mismatch", "value": 0, "shap": -0.02}
    ],
    "completed_at": "2026-07-27T08:00:05Z"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `NOT_FOUND` | 404 | decision_id 或 shap_task_id 不存在 |
| `SHAP_NOT_READY` | 409 | 计算尚未完成，建议轮询 `/status` 或订阅 WebSocket |
| `SHAP_EXPIRED` | 410 | 结果已过期（保留 7 天） |

**WebSocket 推送**：SHAP 计算就绪后，服务端向已订阅的 WebSocket 客户端推送 `transaction.shap_ready` 事件，payload 含 `decision_id` 与 `shap_task_id`，客户端可凭此直接拉取 `/shap/result`。

---

## 5. 规则引擎接口

> V1.1 补齐 CRUD 闭环：`POST/GET/PUT/DELETE /api/v1/rules` + 版本管理（`/versions`）+ 灰度推进（`/promote`）+ 回滚（`/rollback`）。
> 状态机对齐基准 V1.1 §3.4：`rule_status: DRAFT | CANARY | ACTIVE | RETIRED`；`rule_action: BLOCK | REVIEW`（单条规则动作 2 值，区别于评分最终决策 `decision: ALLOW | REVIEW | DENY | CHALLENGE` 4 值）。

### 5.1 GET /rules

分页查询规则列表。

**Scope**：`rule:read`

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| status | enum | `DRAFT` / `CANARY` / `ACTIVE` / `RETIRED` |
| action | enum | `ALLOW` / `REVIEW` / `DENY` / `CHALLENGE` |
| channel | enum | 渠道过滤 |
| severity | enum | `INFO` / `WARN` / `BLOCK` |

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
        "false_positive_rate": 0.1200,
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

新建规则（创建 `DRAFT` 版本 v1）。

**Scope**：`rule:write`

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
    "status": "DRAFT",
    "created_at": "2026-07-27T08:00:00Z"
  }
}
```

### 5.3 GET /rules/{rule_id}

查询规则详情（含版本历史）。

**Scope**：`rule:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R001",
    "name": "大额夜间交易",
    "description": "单笔金额 > 5万 且 发生在 02:00-05:00",
    "dsl": "amount > 5000000 AND hour_of_day BETWEEN 2 AND 5",
    "severity": "WARN",
    "action": "REVIEW",
    "status": "ACTIVE",
    "version": 3,
    "valid_from": "2026-01-01T00:00:00Z",
    "valid_to": null,
    "scope": {"channels": ["WEB", "APP", "POS"]},
    "hit_count_24h": 142,
    "false_positive_rate": 0.1200,
    "published_at": "2026-07-01T00:00:00Z",
    "published_by": "analyst_001",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-07-01T00:00:00Z",
    "versions": [
      {"version": 1, "dsl": "...", "status": "RETIRED", "created_at": "2026-01-01T00:00:00Z", "created_by": "analyst_001"},
      {"version": 2, "dsl": "...", "status": "RETIRED", "created_at": "2026-04-15T00:00:00Z", "created_by": "analyst_002"},
      {"version": 3, "dsl": "amount > 5000000 AND hour_of_day BETWEEN 2 AND 5", "status": "ACTIVE", "created_at": "2026-07-01T00:00:00Z", "created_by": "analyst_001"}
    ]
  }
}
```

### 5.4 PUT /rules/{rule_id}

更新规则草稿（仅 `DRAFT` 状态可更新，已发布版本需先调用 `POST /rules/{rule_id}/versions` 创建新草稿版本）。V1.1 起 V1.0 的 `PATCH` 标记为 `deprecated`。

**Scope**：`rule:write`

**请求体**（全量替换语义；未提供字段以默认值/null 处理）
```json
{
  "name": "新设备首笔大额交易（修订）",
  "description": "新设备首次绑卡后 10 分钟内单笔 > 1万",
  "dsl": "device_age_sec < 600 AND amount > 1000000 AND channel IN ('WEB','APP')",
  "severity": "BLOCK",
  "action": "DENY",
  "valid_from": "2026-08-01T00:00:00Z",
  "valid_to": null,
  "scope": {"channels": ["WEB", "APP"]}
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R057",
    "version": 1,
    "status": "DRAFT",
    "updated_at": "2026-07-27T08:00:00Z"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `RULE_NOT_DRAFT` | 422 | 规则非 `DRAFT` 状态，禁止修改 |
| `RULE_DSL_INVALID` | 422 | DSL 语法/语义错误 |
| `NOT_FOUND` | 404 | rule_id 不存在 |

### 5.5 DELETE /rules/{rule_id}

软删除规则（仅 `DRAFT` 状态可删除；已发布规则需先 `/retire` 转入 `RETIRED`）。

**Scope**：`rule:write`

**响应 204**（无内容）

> 软删除：`status` 标记为 `RETIRED` 并设 `deleted_at`，不物理删除；保留审计追溯。

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `RULE_NOT_DELETABLE` | 422 | 规则非 `DRAFT` 状态，禁止删除 |
| `NOT_FOUND` | 404 | rule_id 不存在 |

### 5.6 POST /rules/{rule_id}/versions

基于当前规则创建新版本草稿（`ACTIVE` 规则创建 v(n+1) 草稿，原 ACTIVE 版本保持生效）。

**Scope**：`rule:write`

**请求体**
```json
{
  "dsl": "amount > 6000000 AND hour_of_day BETWEEN 2 AND 5",
  "change_summary": "上调金额阈值至 6 万",
  "severity": "WARN",
  "action": "REVIEW"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dsl | string | 是 | 新版本 DSL |
| change_summary | string | 否 | 变更说明（写入审计日志） |
| severity | enum | 否 | `INFO` / `WARN` / `BLOCK` |
| action | enum | 否 | `ALLOW` / `REVIEW` / `DENY` / `CHALLENGE` |

**响应 201**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R001",
    "version": 4,
    "status": "DRAFT",
    "based_on_version": 3,
    "created_at": "2026-07-27T08:00:00Z"
  }
}
```

### 5.7 POST /rules/{rule_id}/promote

版本灰度推进：`DRAFT` → `CANARY`（灰度）→ `ACTIVE`（全量）。需要 `rule:write` scope 与复核人二次确认。

**Scope**：`rule:write`

**请求体**
```json
{
  "from_status": "CANARY",
  "to_status": "ACTIVE",
  "canary_percentage": 5,
  "approver_id": "risk_mgr_001",
  "observation_hours": 24,
  "rollback_thresholds": {
    "false_positive_rate": 0.15,
    "precision_drop": 0.02
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| from_status | enum | 是 | `DRAFT` / `CANARY` |
| to_status | enum | 是 | `CANARY` / `ACTIVE`（必须比 from_status 推进一档） |
| canary_percentage | int | CANARY 必填 | 灰度流量百分比（1-100），转入 ACTIVE 时忽略 |
| approver_id | string | 是 | 复核人 ID（不可与创建人相同） |
| observation_hours | int | CANARY 必填 | 灰度观察时长（默认 24h） |
| rollback_thresholds | object | 否 | 自动回滚阈值 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R001",
    "version": 4,
    "from_status": "CANARY",
    "to_status": "ACTIVE",
    "promoted_at": "2026-07-28T08:00:00Z",
    "promoted_by": "analyst_001",
    "previous_version_status": "RETIRED"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `RULE_STATUS_TRANSITION_INVALID` | 422 | 状态机非法迁移（如 DRAFT 直接到 ACTIVE） |
| `APPROVER_REQUIRED` | 422 | 缺少复核人或复核人与创建人相同 |
| `CANARY_THRESHOLD_NOT_MET` | 422 | 灰度指标未达准入门槛 |

### 5.8 POST /rules/{rule_id}/rollback

紧急回滚到上一稳定版本（`ACTIVE`/`CANARY` → 上一 `ACTIVE` 版本，当前版本转 `RETIRED`）。

**Scope**：`rule:write`

**请求体**
```json
{
  "target_version": 3,
  "reason": "误报率突增",
  "approver_id": "risk_mgr_001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_version | int | 否 | 回滚目标版本号；不传则自动选择最近一个 `ACTIVE` 或 `RETIRED` 版本 |
| reason | string | 是 | 回滚原因（写入审计） |
| approver_id | string | 是 | 审批人 ID |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "rule_id": "R001",
    "rolled_back_from_version": 4,
    "rolled_back_to_version": 3,
    "current_status": "ACTIVE",
    "rolled_back_at": "2026-07-27T09:00:00Z",
    "rolled_back_by": "analyst_001"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `NO_ROLLBACK_TARGET` | 422 | 不存在可回滚的历史版本 |
| `TARGET_VERSION_NOT_FOUND` | 404 | 指定的 target_version 不存在 |

### 5.9 POST /rules/{rule_id}/validate

DSL 语法校验与试运行（不生效）。

**Scope**：`rule:write`

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

### 5.10 POST /rules/{rule_id}/retire

下线规则（`ACTIVE`/`CANARY` → `RETIRED`）。

**Scope**：`rule:write`

### 5.11 GET /rules/{rule_id}/hits

查询规则历史命中。

**Scope**：`rule:read`

**查询参数**：`start_time`、`end_time`、`page`、`page_size`

---

## 6. ML 模型接口

> V1.1 补齐 CRUD 闭环：`POST/GET/PUT/DELETE /api/v1/models` + `/canary` + `/promote` + `/rollback` + `/retire`。
> 状态机对齐基准 §3.3：`model_status: REGISTERED | CANARY | ACTIVE | RETIRED`。
> SHAP 接口已迁出至 §4.7-4.9（`/scores/{id}/shap*`），原 `POST /models/{model_id}/explain` 标记 `deprecated`。

### 6.1 GET /models

查询模型版本列表。

**Scope**：`model:read`

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
        "status": "ACTIVE",
        "auc": 0.9420,
        "precision_at_1pct": 0.8100,
        "recall_at_1pct": 0.6500,
        "trained_at": "2026-07-01T00:00:00Z",
        "promoted_at": "2026-07-05T00:00:00Z",
        "traffic_share": 0.9500
      },
      {
        "model_id": "ml_xgb_v3.3.0-canary",
        "status": "CANARY",
        "traffic_share": 0.0500,
        "canary_started_at": "2026-07-20T00:00:00Z"
      }
    ]
  }
}
```

### 6.2 POST /models

注册新模型（上传 artifacts + 元数据）。

**Scope**：`model:write`

**请求体**
```json
{
  "name": "XGBoost 多模态融合 v3.3.0",
  "version": "3.3.0",
  "type": "XGB",
  "artifacts_path": "oss://frd-models/ml_xgb_v3.3.0/",
  "artifacts_sha256": "9f2c1e8d7a4b6c5f3e2d1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d",
  "entrypoint": "predict:predict_proba",
  "runtime": "python3.11",
  "metrics": {
    "auc": 0.9450,
    "precision_at_1pct": 0.8200,
    "recall_at_1pct": 0.6800,
    "psi_7d": 0.18
  },
  "feature_schema_path": "oss://frd-models/ml_xgb_v3.3.0/feature_schema.json",
  "trained_at": "2026-07-15T00:00:00Z",
  "description": "新增设备指纹聚合特征 + BERT 文本特征"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 模型名称 |
| version | string | 是 | 语义化版本号 |
| type | enum | 是 | `XGB` / `BERT` / `MULTIMODAL` / `GNN` |
| artifacts_path | string | 是 | 模型工件 OSS 路径 |
| artifacts_sha256 | string(64) | 是 | 工件 SHA-256 摘要（完整性校验） |
| entrypoint | string | 否 | 推理入口函数 |
| runtime | string | 否 | 运行时（如 `python3.11`） |
| metrics | object | 是 | 离线/验证指标（auc、precision_at_1pct、recall_at_1pct、psi_7d） |
| feature_schema_path | string | 否 | 特征 schema 路径 |
| trained_at | string | 是 | 训练完成时间 |
| description | string | 否 | 模型描述 |

**响应 201**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.3.0",
    "status": "REGISTERED",
    "artifacts_sha256": "9f2c1e8d7a4b6c5f3e2d1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d",
    "registered_at": "2026-07-27T08:00:00Z"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `MODEL_ARTIFACTS_HASH_MISMATCH` | 422 | artifacts_sha256 与服务端校验结果不一致 |
| `MODEL_VERSION_EXISTS` | 409 | 同 name 下 version 已存在 |
| `MODEL_METRICS_INSUFFICIENT` | 422 | metrics 缺失必填指标或未达准入门槛（AUC < 0.92） |

### 6.3 GET /models/{model_id}

查询模型详情。

**Scope**：`model:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.2.1",
    "name": "XGBoost 多模态融合",
    "version": "3.2.1",
    "type": "XGB",
    "status": "ACTIVE",
    "artifacts_path": "oss://frd-models/ml_xgb_v3.2.1/",
    "artifacts_sha256": "abcd1234...",
    "entrypoint": "predict:predict_proba",
    "runtime": "python3.11",
    "metrics": {
      "auc": 0.9420,
      "precision_at_1pct": 0.8100,
      "recall_at_1pct": 0.6500,
      "psi_7d": 0.15
    },
    "feature_schema_path": "oss://frd-models/ml_xgb_v3.2.1/feature_schema.json",
    "trained_at": "2026-07-01T00:00:00Z",
    "registered_at": "2026-07-02T00:00:00Z",
    "promoted_at": "2026-07-05T00:00:00Z",
    "traffic_share": 0.9500,
    "description": "..."
  }
}
```

### 6.4 PUT /models/{model_id}

更新模型元数据（仅 `REGISTERED` 状态可更新；不可修改 artifacts_sha256，否则需重新注册）。

**Scope**：`model:write`

**请求体**
```json
{
  "description": "更新模型描述",
  "feature_schema_path": "oss://frd-models/ml_xgb_v3.3.0/feature_schema_v2.json",
  "entrypoint": "predict:predict_proba_v2"
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.3.0",
    "status": "REGISTERED",
    "updated_at": "2026-07-27T08:00:00Z"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `MODEL_NOT_EDITABLE` | 422 | 模型非 `REGISTERED` 状态，禁止修改 |
| `ARTIFACTS_HASH_IMMUTABLE` | 422 | 试图修改 artifacts_sha256 |

### 6.5 DELETE /models/{model_id}

退役模型（`ACTIVE`/`CANARY` → `RETIRED`）。退役前需先停止流量分配。

**Scope**：`model:write`

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| reason | string | 是 | 退役原因 |
| approver_id | string | 是 | 审批人 ID |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.2.1",
    "status": "RETIRED",
    "retired_at": "2026-07-27T08:00:00Z",
    "retired_by": "analyst_001"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `MODEL_HAS_TRAFFIC` | 422 | 模型仍承担流量，需先迁移流量 |
| `MODEL_NOT_DELETABLE` | 422 | 模型状态不可退役（如已 `RETIRED`） |

### 6.6 POST /models/{model_id}/canary

启动金丝雀发布（`REGISTERED` → `CANARY`）。

**Scope**：`model:write`

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
  "observation_hours": 24,
  "approver_id": "risk_mgr_001"
}
```

### 6.7 POST /models/{model_id}/promote

金丝雀晋升为生产（`CANARY` → `ACTIVE`，原 `ACTIVE` 模型转 `RETIRED`）。

**Scope**：`model:write`

**请求体**
```json
{
  "approver_id": "risk_mgr_001",
  "promotion_report_ref": "oss://reports/promo_20260728.json"
}
```

### 6.8 POST /models/{model_id}/rollback

紧急回滚到上一稳定版本（带 kill switch）。

**Scope**：`model:write`

**请求体**
```json
{
  "target_model_id": "ml_xgb_v3.2.1",
  "reason": "线上指标劣化",
  "approver_id": "risk_mgr_001"
}
```

### 6.9 POST /models/{model_id}/retire

显式退役模型（与 `DELETE /models/{model_id}` 语义相同，但保留显式动词路径便于审计与权限细粒度控制）。

**Scope**：`model:write`

**请求体**
```json
{
  "reason": "被新版本替代",
  "approver_id": "risk_mgr_001",
  "data_retention_days": 90
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "model_id": "ml_xgb_v3.2.1",
    "status": "RETIRED",
    "artifacts_retained_until": "2026-10-25T00:00:00Z",
    "retired_at": "2026-07-27T08:00:00Z"
  }
}
```

### 6.10 GET /models/{model_id}/drift

查询模型漂移指标（PSI / KL / KS / Wasserstein）。

**Scope**：`model:read`

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

> `drift_severity` 枚举（对齐基准 §3.12）：`LOW` / `MEDIUM` / `HIGH` / `CRITICAL`
> `drift_metric` 枚举：`PSI` / `KL` / `KS` / `WASSERSTEIN`

---

## 7. GNN 团伙检测接口

> V1.1 起将 GNN 相关接口独立到 `/api/v1/gnn/*` 命名空间（原 `/graph/*` 路径标记 `deprecated`，6 个月后下线）。
> 实时/异步分流（对齐 D03 §4.4）：
> - **评分主路径内 GNN 实时查询**：内部调用，不暴露为 API；P99 < 2s，仅 1-2 跳邻居查询，作为评分特征之一返回
> - **深度团伙检测**：通过 §7.3 异步任务接口暴露，深度可达 3 跳，适用于反洗钱深度调查与案件分析

### 7.1 GET /gnn/related/{node_id}

查询关联节点（k-hop 邻居，实时同步路径，深度 ≤ 3）。

**Scope**：`graph:read`

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 节点 ID（账户/设备/IP/卡 BIN 等） |

**查询参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| k | int | 2 | 跳数（1-3） |
| edge_types | string | 全部 | 边类型过滤，逗号分隔（如 `USES,FROM_IP,SHARED_DEVICE`） |
| time_window_hours | int | 168 | 时间窗口（小时） |
| limit | int | 100 | 每跳返回节点数上限（1-500） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "seed_node": {"id": "acc_001", "type": "Account"},
    "k": 2,
    "nodes": [
      {"id": "dev_001", "type": "Device", "depth": 1, "shared_accounts": 5, "risk_score": 0.6200},
      {"id": "acc_002", "type": "Account", "depth": 2, "risk_score": 0.8100}
    ],
    "edges": [
      {"from": "acc_001", "to": "dev_001", "type": "USES", "weight": 0.9, "first_seen_at": "2026-07-01T00:00:00Z"}
    ],
    "total_nodes": 12,
    "evaluated_at_ms": 187
  }
}
```

### 7.2 POST /gnn/embedding/{node_id}

计算 GraphSAGE 嵌入向量（用于相似度检索、聚类等下游任务）。

**Scope**：`graph:write`

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 节点 ID |

**请求体**
```json
{
  "model_id": "gnn_graphsage_v1.2.0",
  "dimension": 128,
  "context_hops": 2
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model_id | string | 否 | GNN 模型版本，默认使用 `ACTIVE` 模型 |
| dimension | int | 否 | 嵌入维度（默认 128，对齐模型输出） |
| context_hops | int | 否 | 聚合上下文跳数（1-3，默认 2） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "node_id": "acc_001",
    "model_id": "gnn_graphsage_v1.2.0",
    "embedding": [0.123, -0.045, 0.678, "..."],
    "dimension": 128,
    "computed_at": "2026-07-27T08:00:00Z",
    "latency_ms": 95
  }
}
```

> 性能 SLA：单节点嵌入 P99 < 200ms；批量嵌入走异步任务。

### 7.3 POST /gnn/community-detection

触发团伙检测异步任务（深度 1-3 跳，反洗钱深度调查场景）。

**Scope**：`graph:write`

**请求体**
```json
{
  "seed_account_id": "acc_001",
  "depth": 3,
  "time_window_hours": 168,
  "min_confidence": 0.6,
  "edge_types": ["USES", "FROM_IP", "SHARED_DEVICE"],
  "algorithm": "LOUVAIN",
  "callback_event": "gang.detected"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| seed_account_id | string | 是 | 种子账户 ID |
| depth | int | 否 | 跳数（1-3，默认 3） |
| time_window_hours | int | 否 | 时间窗口（默认 168h = 7 天） |
| min_confidence | float | 否 | 最小置信度阈值 |
| edge_types | array | 否 | 边类型过滤 |
| algorithm | enum | 否 | `LOUVAIN`（默认）/ `LABEL_PROP` / `WALKTRAP` |
| callback_event | string | 否 | 完成后推送的 Webhook 事件名 |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "task_id": "gnn_task_01HXY9K8...",
    "status": "RUNNING",
    "estimated_seconds": 60,
    "callback_event": "gang.detected"
  }
}
```

> 完成后通过 Webhook 事件 `gang.detected` 或 WebSocket 推送。

### 7.4 GET /gnn/community-detection/{task_id}

查询团伙检测任务状态。

**Scope**：`graph:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "task_id": "gnn_task_01HXY9K8...",
    "status": "SUCCEEDED",
    "communities": ["community_001", "community_002"],
    "progress": 1.0,
    "created_at": "2026-07-27T06:00:00Z",
    "completed_at": "2026-07-27T06:01:00Z"
  }
}
```

**task status 枚举**：`RUNNING` / `SUCCEEDED` / `FAILED` / `TIMEOUT`

### 7.5 GET /gnn/community/{community_id}

查询团伙详情（节点 + 边）。

**Scope**：`graph:read`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "community_id": "community_001",
    "confidence": 0.8700,
    "size": 12,
    "total_amount": 158000000,
    "detected_at": "2026-07-27T06:00:00Z",
    "algorithm": "LOUVAIN",
    "nodes": [
      {"id": "acc_001", "type": "Account", "risk_score": 0.9200, "centrality": 0.85},
      {"id": "dev_001", "type": "Device", "shared_accounts": 5, "centrality": 0.62}
    ],
    "edges": [
      {"from": "acc_001", "to": "dev_001", "type": "USES", "weight": 0.9}
    ],
    "case_id": "case_01HXY9K8...",
    "model_id": "gnn_graphsage_v1.2.0"
  }
}
```

---

## 8. 案件管理接口

### 8.1 GET /cases

分页查询案件。

**Scope**：`case:read`

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| status | enum | `OPEN` / `IN_REVIEW` / `CONFIRMED` / `CLOSED` / `FALSE_ALARM` |
| priority | enum | `P0` / `P1` / `P2` / `P3` |
| assignee_id | string | 处理人 |
| created_after / created_before | string | 时间范围 |

### 8.2 POST /cases

手动创建案件。

**Scope**：`case:write`

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

**Scope**：`case:read`

### 8.4 PATCH /cases/{case_id}

更新案件状态/优先级/处理人。

**Scope**：`case:write`

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

**Scope**：`case:write`

### 8.6 POST /cases/{case_id}/close

关闭案件（必须填写结案结论）。

**Scope**：`case:write`

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

> `case_status` 枚举（对齐基准 §3.2）：`OPEN` / `IN_REVIEW` / `CONFIRMED` / `CLOSED` / `FALSE_ALARM`
> `case_level` 枚举（对齐基准 §3.7）：`P0` / `P1` / `P2` / `P3`

### 8.7 GET /cases/{case_id}/timeline

案件操作时间线（含审计追溯）。

**Scope**：`case:read`

---

## 9. 报表与统计接口

> ⏳ **规划接口，代码未实现**（截至 2026-07-27）：后端无 /reports 路由。计划 M6 RC 交付。

### 9.1 GET /reports/summary

查询租户风险概览。

**Scope**：`report:read`

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
      "model_auc": 0.9420
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

**Scope**：`report:read`

### 9.3 GET /reports/models/performance

模型性能报表（AUC / Precision / Recall / 延迟）。

**Scope**：`report:read`

### 9.4 POST /reports/export

异步导出报表。

**Scope**：`report:write`

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

**Scope**：`report:read`

---

## 10. 模型治理接口

> ⏳ **规划接口，代码未实现**（截至 2026-07-27）：无 /governance 路由（Kill Switch 仅 service 层，前端调用 404）。计划 M5 Beta 交付。

### 10.1 GET /governance/audit-log

审计日志查询（满足 PIPL / 反洗钱合规审计）。

**Scope**：`admin:*`

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| actor_id | string | 操作人 |
| action | enum | `LOGIN` / `RULE_PUBLISH` / `MODEL_PROMOTE` / `CASE_CLOSE` / `PIPL_DATA_EXPORT` 等 |
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

> 审计日志保留期：反洗钱合规要求 7 年（基准 §2.3）。

### 10.2 POST /governance/kill-switch

紧急熔断（关闭 ML 引擎，回退到纯规则模式）。

**Scope**：`governance:write`

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

**Scope**：`model:read`

### 10.4 POST /governance/canaries/{canary_id}/advance

推进金丝雀流量比例（5% → 25% → 100%）。

**Scope**：`governance:write`

### 10.5 POST /governance/canaries/{canary_id}/rollback

回滚金丝雀。

**Scope**：`governance:write`

---

## 11. Webhook 与回调

> V1.1 补齐 CRUD 闭环：`POST/GET/PUT/DELETE /api/v1/webhooks` + `/test`（手动触发测试）+ `/deliveries`（投递记录查询）。
> 签名算法明确：HMAC-SHA256，防重放 5 分钟，重试 5 次（1m/5m/30m/2h/12h），失败入死信队列。

### 11.1 POST /webhooks

注册 Webhook。注册时服务端回调一次 challenge 签名验证，确认 URL 可达性与签名校验通过后才正式启用。

**Scope**：`webhook:write`

**请求体**
```json
{
  "url": "https://client.example.com/webhooks/frd",
  "events": ["transaction.blocked", "case.created", "model.promoted"],
  "secret": "whsec_xxxxx",
  "challenge_expected": true
}
```

**响应 201**
```json
{
  "code": "OK",
  "data": {
    "id": "wh_01HXY9K8...",
    "url": "https://client.example.com/webhooks/frd",
    "events": ["transaction.blocked", "case.created", "model.promoted"],
    "status": "PENDING_VERIFICATION",
    "challenge_id": "ch_01HXY9K8...",
    "created_at": "2026-07-27T08:00:00Z"
  }
}
```

**challenge 验证流程**：

1. 服务端生成 `challenge_token`（UUID）与 `timestamp`
2. 以 `HMAC-SHA256(secret, "{timestamp}.{body}")` 计算签名（body 为 challenge payload JSON 字节流）
3. POST 到注册 URL，Header 携带 `X-FRD-Signature: t={timestamp},v1={hmac_hex}`
4. 客户端必须以相同算法验签后返回 2xx + `{"challenge_token": "..."}`
5. 验证通过后 `status` 转为 `ACTIVE`；超时（5 分钟）或验签失败则置 `VERIFICATION_FAILED`

### 11.2 GET /webhooks

分页查询 Webhook 列表。

**Scope**：`webhook:write`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "items": [
      {
        "id": "wh_01HXY9K8...",
        "url": "https://client.example.com/webhooks/frd",
        "events": ["transaction.blocked", "case.created"],
        "status": "ACTIVE",
        "created_at": "2026-07-27T08:00:00Z",
        "last_delivery_at": "2026-07-27T09:00:00Z",
        "last_delivery_status": "SUCCESS"
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 3
  }
}
```

### 11.3 GET /webhooks/{id}

查询 Webhook 详情（含最近投递记录摘要）。

**Scope**：`webhook:write`

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "id": "wh_01HXY9K8...",
    "url": "https://client.example.com/webhooks/frd",
    "events": ["transaction.blocked", "case.created"],
    "secret_hash": "sha256:abcd...",
    "status": "ACTIVE",
    "created_at": "2026-07-27T08:00:00Z",
    "updated_at": "2026-07-27T08:00:00Z",
    "recent_deliveries": [
      {
        "event_id": "evt_01HXY9K8...",
        "event_type": "transaction.blocked",
        "delivered_at": "2026-07-27T09:00:00Z",
        "response_code": 200,
        "attempts": 1,
        "latency_ms": 85
      }
    ]
  }
}
```

### 11.4 PUT /webhooks/{id}

更新 Webhook 事件类型或 URL（全量替换语义）。URL 变更需重新触发 challenge 验证。V1.1 起 V1.0 的 `PATCH` 标记为 `deprecated`。

**Scope**：`webhook:write`

**请求体**
```json
{
  "url": "https://client.example.com/webhooks/frd_v2",
  "events": ["transaction.blocked", "transaction.shap_ready", "case.created"],
  "secret": "whsec_new_xxxxx",
  "challenge_expected": true
}
```

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "id": "wh_01HXY9K8...",
    "url": "https://client.example.com/webhooks/frd_v2",
    "events": ["transaction.blocked", "transaction.shap_ready", "case.created"],
    "status": "PENDING_VERIFICATION",
    "challenge_id": "ch_01HXY9K8...",
    "updated_at": "2026-07-27T10:00:00Z"
  }
}
```

### 11.5 DELETE /webhooks/{id}

注销 Webhook（软删除，30 天保留期后物理删除）。

**Scope**：`webhook:write`

**响应 204**（无内容）

### 11.6 POST /webhooks/{id}/test

手动触发测试事件投递（用于验证当前 Webhook 配置可达性与签名校验）。

**Scope**：`webhook:write`

**请求体**
```json
{
  "event_type": "transaction.blocked",
  "test_payload": {
    "external_tx_id": "TEST_TX_001",
    "decision": "DENY",
    "risk_score": 0.9100
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_type | string | 是 | 测试事件类型（必须在 webhook 订阅列表内） |
| test_payload | object | 否 | 自定义测试 payload；不传则使用该 event_type 的样例数据 |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "delivery_id": "dlv_01HXY9K8...",
    "webhook_id": "wh_01HXY9K8...",
    "event_type": "transaction.blocked",
    "status": "PENDING",
    "signature_header": "t=1722057600,v1=abcdef..."
  }
}
```

> 测试投递与生产投递走相同的签名算法、重试策略、死信队列；测试 delivery 在投递记录中标记 `is_test = true`。

### 11.7 GET /webhooks/{id}/deliveries

查询 Webhook 投递记录（含失败重试历史）。

**Scope**：`webhook:write`

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| event_type | string | 事件类型过滤 |
| status | enum | `SUCCESS` / `FAILED` / `RETRYING` / `DEAD_LETTERED` |
| start_time / end_time | string | 时间范围 |
| page / page_size | int | 分页 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "items": [
      {
        "delivery_id": "dlv_01HXY9K8...",
        "event_id": "evt_01HXY9K8...",
        "event_type": "transaction.blocked",
        "webhook_id": "wh_01HXY9K8...",
        "status": "SUCCESS",
        "is_test": false,
        "attempts": [
          {
            "attempt_no": 1,
            "sent_at": "2026-07-27T09:00:00Z",
            "response_code": 200,
            "response_body_snippet": "{\"ok\":true}",
            "latency_ms": 85,
            "next_retry_at": null
          }
        ],
        "delivered_at": "2026-07-27T09:00:00Z",
        "dead_lettered_at": null
      },
      {
        "delivery_id": "dlv_01HXY9K9...",
        "event_id": "evt_01HXY9K9...",
        "event_type": "case.created",
        "status": "DEAD_LETTERED",
        "is_test": false,
        "attempts": [
          {"attempt_no": 1, "sent_at": "2026-07-27T09:01:00Z", "response_code": 500, "next_retry_at": "2026-07-27T09:02:00Z"},
          {"attempt_no": 2, "sent_at": "2026-07-27T09:02:00Z", "response_code": 500, "next_retry_at": "2026-07-27T09:07:00Z"},
          {"attempt_no": 3, "sent_at": "2026-07-27T09:07:00Z", "response_code": 500, "next_retry_at": "2026-07-27T09:37:00Z"},
          {"attempt_no": 4, "sent_at": "2026-07-27T09:37:00Z", "response_code": 500, "next_retry_at": "2026-07-27T11:37:00Z"},
          {"attempt_no": 5, "sent_at": "2026-07-27T11:37:00Z", "response_code": 500, "next_retry_at": "2026-07-27T23:37:00Z"}
        ],
        "delivered_at": null,
        "dead_lettered_at": "2026-07-27T23:37:00Z",
        "dead_letter_reason": "MAX_RETRY_EXCEEDED"
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 56
  }
}
```

### 11.8 签名算法

**算法**：`HMAC-SHA256(webhook_secret, "{timestamp}.{request_body}")`

**Header**：
```
X-FRD-Signature: t={unix_timestamp},v1={hmac_sha256_hex}
X-FRD-Timestamp: {unix_timestamp}
```

| 字段 | 说明 |
|------|------|
| `t` | 服务端发送事件时的 Unix 时间戳（秒） |
| `v1` | `HMAC-SHA256(secret, "{t}.{body}")` 的十六进制摘要，`body` 为原始请求体字节流（UTF-8 编码） |
| `X-FRD-Timestamp` | 时间戳副本，便于客户端提取 |

**签名串构造**：`{timestamp}.{request_body}`，其中 `request_body` 为 HTTP 请求体原始字节流（不可重新序列化，否则签名不一致）。

**验证流程**（接收方）：

1. 从 Header `X-FRD-Signature` 解析 `t` 与 `v1`
2. 计算 `expected = HMAC-SHA256(webhook_secret, "{t}.{request_body}").hexdigest()`
3. 使用恒定时间比较 `hmac.compare_digest(expected, v1)`
4. **防重放**：检查 `|now - t| > 300s`（5 分钟），超过则拒绝并记录安全事件

**时间戳容差**：5 分钟（300 秒）。

**客户端验签示例（Python）**：

```python
import hmac, hashlib, time

def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    parts = dict(p.split("=", 1) for p in signature_header.split(","))
    t = int(parts["t"])
    v1 = parts["v1"]
    # 防重放：时间戳容差 5 分钟
    if abs(int(time.time()) - t) > 300:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{t}.".encode("utf-8") + body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, v1)
```

### 11.9 事件推送格式

```json
{
  "event_id": "evt_01HXY9K8...",
  "event_type": "transaction.blocked",
  "tenant_id": "tenant_001",
  "occurred_at": "2026-07-27T08:00:00Z",
  "delivery_attempt": 1,
  "data": {
    "external_tx_id": "TX20260727000001",
    "decision": "DENY",
    "risk_score": 0.9100,
    "risk_band": "CRITICAL",
    "rule_hits": [{"rule_id": "R005"}]
  }
}
```

> 签名在 HTTP Header 中传递（`X-FRD-Signature`），不在 body 内。

### 11.10 重试策略

- 失败重试 **5 次**，退避间隔：**1m / 5m / 30m / 2h / 12h**（指数级退避）
- 客户端需返回 2xx 才视为成功
- 5 次重试均失败后归档到**死信队列**（Dead Letter Queue），可通过 `GET /webhooks/{id}/deliveries` 查询 `status = DEAD_LETTERED` 的记录
- 死信队列保留 30 天，期间可手动触发 `POST /webhooks/{id}/test` 重新投递

| 重试次数 | 退避间隔 | 累计耗时 |
|----------|----------|----------|
| 1（首次） | 即时 | 0 |
| 2 | 1m | 1m |
| 3 | 5m | 6m |
| 4 | 30m | 36m |
| 5 | 2h | 2h36m |
| 入死信 | 12h | 14h36m |

### 11.11 支持事件列表

| event_type | 触发场景 |
|------------|----------|
| `transaction.blocked` | 交易被 `DENY` |
| `transaction.review` | 交易进入人工审核 |
| `transaction.analysis_completed` | 异步深度分析完成（对齐 §4.2） |
| `transaction.shap_ready` | SHAP 异步计算就绪（对齐 §4.7） |
| `case.created` | 案件创建 |
| `case.assigned` | 案件被分配 |
| `case.closed` | 案件关闭 |
| `gang.detected` | GNN 检测到团伙 |
| `model.promoted` | 模型晋升生产 |
| `model.rolled_back` | 模型回滚 |
| `rule.promoted` | 规则灰度晋升（对齐 §5.7） |
| `rule.rolled_back` | 规则回滚（对齐 §5.8） |
| `drift.alert` | 漂移告警 |
| `report.ready` | 报表导出完成 |
| `privacy.export.ready` | 数据导出包就绪（对齐 §13） |
| `privacy.deletion.completed` | 数据删除完成（对齐 §13） |

---

## 12. 错误码

### 12.1 业务错误码

| code | HTTP | 含义 | 重试 |
|------|------|------|------|
| `OK` | 200 | 成功（含幂等命中重放） | - |
| `INVALID_PARAMS` | 400 | 参数语法/类型错误 | 否 |
| `INVALID_JSON` | 400 | JSON 格式错误 | 否 |
| `UNAUTHORIZED` | 401 | 未认证 | 否 |
| `FORBIDDEN` | 403 | 无权限 | 否 |
| `SCOPE_INSUFFICIENT` | 403 | Scope 不足 | 否 |
| `TENANT_SUSPENDED` | 403 | 租户被冻结 | 否 |
| `NOT_FOUND` | 404 | 资源不存在 | 否 |
| `CONFLICT` | 409 | 资源版本/唯一约束冲突 | 否 |
| `VALIDATION_FAILED` | 422 | 业务规则校验失败 | 否 |
| `RULE_DSL_INVALID` | 422 | 规则 DSL 语法/语义错误 | 否 |
| `RULE_NOT_DRAFT` | 422 | 规则非 DRAFT 状态，禁止修改 | 否 |
| `RULE_NOT_DELETABLE` | 422 | 规则非 DRAFT 状态，禁止删除 | 否 |
| `RULE_STATUS_TRANSITION_INVALID` | 422 | 规则状态机非法迁移 | 否 |
| `APPROVER_REQUIRED` | 422 | 缺少复核人或复核人与创建人相同 | 否 |
| `CANARY_THRESHOLD_NOT_MET` | 422 | 灰度指标未达准入门槛 | 否 |
| `NO_ROLLBACK_TARGET` | 422 | 不存在可回滚的历史版本 | 否 |
| `TARGET_VERSION_NOT_FOUND` | 404 | 指定的回滚目标版本不存在 | 否 |
| `MODEL_NOT_AVAILABLE` | 422 | 模型不可用 | 是 |
| `MODEL_ARTIFACTS_HASH_MISMATCH` | 422 | 模型工件 SHA-256 校验失败 | 否 |
| `MODEL_VERSION_EXISTS` | 409 | 模型版本已存在 | 否 |
| `MODEL_METRICS_INSUFFICIENT` | 422 | 模型指标未达准入门槛 | 否 |
| `MODEL_HAS_TRAFFIC` | 422 | 模型仍承担流量，禁止退役 | 否 |
| `MODEL_NOT_DELETABLE` | 422 | 模型状态不可退役 | 否 |
| `MODEL_NOT_EDITABLE` | 422 | 模型非 REGISTERED 状态，禁止修改 | 否 |
| `ARTIFACTS_HASH_IMMUTABLE` | 422 | 试图修改 artifacts_sha256 | 否 |
| `SHAP_NOT_READY` | 409 | SHAP 计算尚未完成 | 是（轮询） |
| `SHAP_EXPIRED` | 410 | SHAP 结果已过期（保留 7 天） | 否 |
| `SHAP_COMPUTATION_FAILED` | 500 | SHAP 计算异常 | 是 |
| `RATE_LIMITED` | 429 | 限流 | 是 |
| `CIRCUIT_OPEN` | 503 | 熔断 | 是（退避） |
| `INTERNAL_ERROR` | 500 | 服务端错误 | 是 |
| `SUBJECT_NOT_VERIFIED` | 422 | PIPL 数据主体身份核验失败 | 否 |
| `SUBJECT_NOT_FOUND` | 404 | 数据主体不存在或不属于该租户 | 否 |
| `LEGAL_HOLD_CONFLICT` | 422 | 数据涉及未结案件/反洗钱调查，进入法务复核 | 否 |
| `CONSENT_ALREADY_GRANTED` | 409 | 同一 purpose 已存在有效同意 | 否 |
| `CONSENT_NOT_FOUND` | 404 | consent_id 不存在或不属于该数据主体 | 否 |
| `CONSENT_ALREADY_WITHDRAWN` | 422 | 同意已撤回 | 否 |
| `POLICY_VERSION_OUTDATED` | 422 | policy_version 非当前生效版本 | 否 |
| `RECTIFICATION_NOT_ALLOWED` | 422 | 该字段不允许更正（如审计锁定字段） | 否 |

> 幂等命中不再返回错误码，统一走 HTTP 200 + `X-Idempotent-Replay: true` 响应头。

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

## 13. PIPL 数据主体权利接口

> 实现依据：基准 §7.1 与 §2.3 PIPL 合规要求。V1.1 起统一在 `/api/v1/pipl/*` 命名空间下，覆盖告知同意、最小必要、数据可携带权、删除权、更正权、自动化决策解释权。
> 所有 PIPL 接口均需数据主体身份核验（OTP/人脸/电子签名等），核验通过后颁发 `verification_token` 用于后续请求。
>
> **PIPL 接口对应的数据表**（D04 V1.1）：
> - `consent_records` — 用户同意记录（PIPL §14/§15/§17）
> - `deletion_requests` — 删除/更正请求（PIPL §45/§46/§47）
> - `fairness_reports` — 公平性报告（PIPL §24 自动化决策公平性）
>
> 所有 PIPL 表启用 RLS，仅租户内可访问；`fairness_reports` 含受保护属性（AGE/GENDER/REGION），访问需 `COMPLIANCE_OFFICER` 角色。

### 13.1 POST /pipl/consent

记录用户同意（PIPL §14、§15、§17）。

**Scope**：`consent:write`（数据主体自查）或 `admin:*`（管理员代为操作）

**请求体**
```json
{
  "user_id": "user_999",
  "verification_token": "vt_otp_xxxxxxxx",
  "consent_type": "EXPLICIT",
  "purpose": "TRANSACTION_SCORING",
  "legal_basis": "CONSENT",
  "scope": ["transactions", "scores"],
  "policy_version": "PP_v2.1",
  "expires_at": "2027-01-01T00:00:00Z",
  "evidence": {
    "channel": "WEB",
    "user_agent": "Mozilla/5.0...",
    "ip_address": "1.2.3.4",
    "signed_text_hash": "sha256:abcdef..."
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |
| verification_token | string | 是 | 身份核验令牌（来自前置 OTP/人脸认证） |
| consent_type | enum | 是 | `EXPLICIT`（明示同意）/ `IMPLICIT_BY_ACTION`（行为默示，限 PIPL 允许场景） |
| purpose | enum | 是 | `TRANSACTION_SCORING` / `FRAUD_DETECTION` / `AML_REPORT` / `MARKETING` / `RESEARCH`（对齐基准 §3.11） |
| legal_basis | enum | 是 | `CONSENT` / `CONTRACT` / `LEGAL_OBLIGATION` / `VITAL_INTEREST` / `PUBLIC_TASK` / `LEGITIMATE_INTEREST` |
| scope | array | 是 | 同意覆盖的数据范围 |
| policy_version | string | 是 | 隐私政策版本（同意时的版本快照） |
| expires_at | string | 否 | 同意有效期（不传则默认 2 年） |
| evidence | object | 是 | 同意采集证据（channel、UA、IP、签名文本哈希） |

**响应 201**
```json
{
  "code": "OK",
  "data": {
    "consent_id": "cns_01HXY9K8...",
    "user_id": "user_999",
    "status": "GRANTED",
    "purpose": "TRANSACTION_SCORING",
    "legal_basis": "CONSENT",
    "granted_at": "2026-07-27T08:00:00Z",
    "expires_at": "2027-01-01T00:00:00Z",
    "evidence_ref": "oss://consents/cns_01HXY9K8....pdf"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `SUBJECT_NOT_VERIFIED` | 422 | 身份核验失败或 verification_token 过期 |
| `CONSENT_ALREADY_GRANTED` | 409 | 同一 purpose 已存在有效同意 |
| `POLICY_VERSION_OUTDATED` | 422 | policy_version 非当前生效版本 |
| `LEGAL_BASIS_INVALID` | 422 | legal_basis 与 purpose 不匹配（如 MARKETING 必须为 CONSENT） |

**合规说明**

- 同意证据（证据 PDF、UA/IP/签名）须保留至撤回后 3 年（PIPL §55）
- 同意后服务端在 24h 内完成关联数据范围标记，未标记前不基于该同意处理新数据
- 自动化决策（评分）相关同意单独记录，撤回后将人工复核该数据主体后续交易
- 同意状态变更推送审计日志（不主动推送 Webhook，避免合规事件外泄）

### 13.2 POST /pipl/consent/withdraw

撤回同意（PIPL §16）。

**Scope**：`consent:write`

**请求体**
```json
{
  "user_id": "user_999",
  "verification_token": "vt_otp_xxxxxxxx",
  "consent_id": "cns_01HXY9K8...",
  "withdrawal_reason": "PRIVACY_CONCERN",
  "effective_immediately": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |
| verification_token | string | 是 | 身份核验令牌 |
| consent_id | string | 是 | 要撤回的同意 ID |
| withdrawal_reason | enum | 否 | `NO_LONGER_NEEDED` / `SERVICE_CANCELLED` / `PRIVACY_CONCERN` / `OTHER` |
| effective_immediately | bool | 否 | 是否立即生效（默认 true）；false 则在下一数据处理周期生效 |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "consent_id": "cns_01HXY9K8...",
    "user_id": "user_999",
    "status": "WITHDRAWN",
    "withdrawn_at": "2026-07-27T08:00:00Z",
    "effective_at": "2026-07-27T08:00:00Z",
    "downstream_actions": [
      {"action": "STOP_PROCESSING", "scope": "TRANSACTION_SCORING", "completed": true},
      {"action": "QUEUE_DELETION_REVIEW", "scope": "TRANSACTIONS", "completed": false, "deletion_request_id": "del_req_01HXY9K8..."}
    ]
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `SUBJECT_NOT_VERIFIED` | 422 | 身份核验失败 |
| `CONSENT_NOT_FOUND` | 404 | consent_id 不存在或不属于该 user_id |
| `CONSENT_ALREADY_WITHDRAWN` | 422 | 同意已撤回 |

**合规说明**

- 撤回同意后，相关数据主体的新请求将不再使用对应目的处理其数据
- 撤回不影响撤回前已处理的合法性
- 若撤回 `TRANSACTION_SCORING` 同意，服务端自动创建数据删除复核任务（不直接删除，需考虑反洗钱 7 年保留）
- 撤回事件推送审计日志

### 13.3 GET /pipl/consent/{user_id}

查询用户同意状态（PIPL §44 知情权）。

**Scope**：`consent:write`（数据主体自查）或 `admin:*`（管理员查询）

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| purpose | enum | `TRANSACTION_SCORING` / `FRAUD_DETECTION` / `AML_REPORT` / `MARKETING` / `RESEARCH` |
| status | enum | `GRANTED` / `WITHDRAWN` / `EXPIRED` |
| include_history | bool | 是否包含历史撤回记录（默认 false） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "user_id": "user_999",
    "items": [
      {
        "consent_id": "cns_01HXY9K8...",
        "purpose": "TRANSACTION_SCORING",
        "legal_basis": "CONSENT",
        "consent_type": "EXPLICIT",
        "status": "GRANTED",
        "scope": ["transactions", "scores"],
        "granted_at": "2025-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
        "withdrawn_at": null,
        "policy_version": "PP_v2.1",
        "evidence_ref": "oss://consents/cns_01HXY9K8....pdf"
      }
    ],
    "summary": {
      "active_count": 2,
      "withdrawn_count": 1,
      "expired_count": 0
    },
    "page": 1,
    "page_size": 20,
    "total": 3
  }
}
```

> `consent_status` 枚举（对齐基准 §3.11）：`GRANTED` / `WITHDRAWN` / `EXPIRED`
> `consent_purpose` 枚举：`TRANSACTION_SCORING` / `FRAUD_DETECTION` / `AML_REPORT` / `MARKETING` / `RESEARCH`

### 13.4 GET /pipl/data-export

申请数据可携带权导出（PIPL §45）。触发异步任务，返回 task_id。

**Scope**：`privacy:write`

**查询参数**（GET 形式，便于浏览器跳转）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |
| verification_token | string | 是 | 身份核验令牌 |
| scope | string | 是 | 导出范围，逗号分隔：`TRANSACTIONS,SCORES,CASES,CONSENTS,AUDIT_LOGS` |
| format | enum | 否 | `JSON`（默认）/ `CSV` / `XLSX` |
| start_date | string | 否 | 起始日期（YYYY-MM-DD） |
| end_date | string | 否 | 截止日期（YYYY-MM-DD） |
| delivery_method | enum | 否 | `OSS_PRESIGNED_URL`（默认）/ `WEBHOOK` |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "task_id": "exp_task_01HXY9K8...",
    "user_id": "user_999",
    "status": "PROCESSING",
    "estimated_seconds": 300,
    "expires_at": "2026-07-27T13:00:00Z",
    "callback_event": "privacy.export.ready"
  }
}
```

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `SUBJECT_NOT_VERIFIED` | 422 | 身份核验失败 |
| `SUBJECT_NOT_FOUND` | 404 | 数据主体不存在或不属于该租户 |
| `EXPORT_SCOPE_INVALID` | 422 | scope 取值非法 |

**合规说明**

- 申请后服务端在 15 个工作日内完成（PIPL §45）；MVP 阶段 SLA 为 5 分钟内生成
- 导出包使用租户专属 KMS 密钥加密
- 下载链接有效期 1h，仅可下载 1 次
- 操作全程记录审计日志（含 actor、IP、scope、时间）
- 不导出卡 PAN、CVV 等 PCI-DSS 禁止存储的字段

### 13.5 GET /pipl/data-export/{task_id}/status

查询导出任务状态。

**Scope**：`privacy:write`

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | string | 是 | 导出任务 ID（来自 §13.4 响应） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "task_id": "exp_task_01HXY9K8...",
    "user_id": "user_999",
    "status": "READY",
    "scope": ["TRANSACTIONS", "SCORES"],
    "format": "JSON",
    "download_url": "https://oss.fraud-detection.example.com/exports/exp_task_01HXY9K8...?Expires=...&Signature=...",
    "expires_at": "2026-07-27T09:00:00Z",
    "created_at": "2026-07-27T08:00:00Z",
    "completed_at": "2026-07-27T08:05:00Z"
  }
}
```

**status 枚举**：`PROCESSING` / `READY` / `FAILED` / `EXPIRED`

### 13.6 POST /pipl/deletion

申请数据删除（被遗忘权，PIPL §47）。

**Scope**：`privacy:write`

**请求体**
```json
{
  "user_id": "user_999",
  "verification_token": "vt_otp_xxxxxxxx",
  "scope": ["TRANSACTIONS", "SCORES"],
  "reason": "USER_REQUEST",
  "retain_for_aml": true,
  "legal_hold_review": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |
| verification_token | string | 是 | 身份核验令牌 |
| scope | array | 是 | 删除范围 |
| reason | enum | 是 | `USER_REQUEST` / `CONSENT_WITHDRAWN` / `DATA_RETENTION_EXPIRED` / `LEGAL_OBLIGATION_END` |
| retain_for_aml | bool | 否 | 是否保留反洗钱合规所需数据（默认 true，7 年保留期内不物理删除） |
| legal_hold_review | bool | 否 | 是否触发法务复核（涉及未结案件时强制为 true） |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "request_id": "del_req_01HXY9K8...",
    "user_id": "user_999",
    "status": "PENDING_REVIEW",
    "legal_hold_required": false,
    "estimated_seconds": 600,
    "callback_event": "privacy.deletion.completed"
  }
}
```

**status 枚举**：`PENDING_REVIEW` / `APPROVED` / `IN_PROGRESS` / `COMPLETED` / `REJECTED` / `PARTIALLY_COMPLETED`

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `LEGAL_HOLD_CONFLICT` | 422 | 数据涉及未结案件/反洗钱调查，进入法务复核 |
| `SUBJECT_NOT_VERIFIED` | 422 | 身份核验失败 |
| `DELETION_SCOPE_INVALID` | 422 | scope 取值非法 |

**合规说明**

- 反洗钱法 7 年审计日志保留期内不物理删除，采用去标识化/匿名化处理
- PCI-DSS 要求的支付数据按 PCI-DSS v4.0 §10 保留要求处理
- 已结案件数据按 `case_status = CLOSED` 后 90 天方可删除
- 删除完成后推送 `privacy.deletion.completed` Webhook 事件

### 13.7 GET /pipl/deletion/{request_id}/status

查询删除请求状态。

**Scope**：`privacy:write`

**路径参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| request_id | string | 是 | 删除请求 ID（来自 §13.6 响应） |

**响应 200**
```json
{
  "code": "OK",
  "data": {
    "request_id": "del_req_01HXY9K8...",
    "user_id": "user_999",
    "status": "COMPLETED",
    "scope": ["TRANSACTIONS", "SCORES"],
    "deleted_count": 1280,
    "anonymized_count": 56,
    "retained_count": 12,
    "retention_reason": "AML_7Y_RETENTION",
    "legal_hold_review": {
      "required": false,
      "reviewer_id": null,
      "reviewed_at": null
    },
    "created_at": "2026-07-27T08:00:00Z",
    "completed_at": "2026-07-27T08:10:00Z"
  }
}
```

### 13.8 POST /pipl/rectification

数据更正请求（PIPL §46）。

**Scope**：`privacy:write`

**请求体**
```json
{
  "user_id": "user_999",
  "verification_token": "vt_otp_xxxxxxxx",
  "corrections": [
    {
      "resource_type": "TRANSACTION",
      "resource_id": "TX20260727000001",
      "field": "user_account_id",
      "current_value": "user_999_old",
      "corrected_value": "user_999",
      "evidence": "身份证扫描件 + 银行回单"
    },
    {
      "resource_type": "USER_PROFILE",
      "resource_id": "user_999",
      "field": "phone_hash",
      "current_value": "hash_aaaa...",
      "corrected_value": "hash_bbbb...",
      "evidence": "新手机号验证记录"
    }
  ],
  "reason": "DATA_INACCURATE"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 数据主体 ID |
| verification_token | string | 是 | 身份核验令牌 |
| corrections | array | 是 | 更正项列表（至少 1 项） |
| corrections[].resource_type | enum | 是 | `TRANSACTION` / `USER_PROFILE` / `CASE` / `CONSENT` |
| corrections[].resource_id | string | 是 | 资源 ID |
| corrections[].field | string | 是 | 字段名（必须是允许更正的字段白名单内） |
| corrections[].current_value | any | 是 | 当前值（用于乐观锁校验） |
| corrections[].corrected_value | any | 是 | 更正后的值 |
| corrections[].evidence | string | 是 | 更正证据（凭证说明/文件引用） |
| reason | enum | 是 | `DATA_INACCURATE` / `DATA_OUTDATED` / `DATA_INCOMPLETE` / `USER_REQUEST` |

**响应 202**
```json
{
  "code": "OK",
  "data": {
    "request_id": "rect_req_01HXY9K8...",
    "user_id": "user_999",
    "status": "PENDING_REVIEW",
    "correction_count": 2,
    "estimated_seconds": 120,
    "callback_event": "privacy.rectification.completed"
  }
}
```

**status 枚举**：`PENDING_REVIEW` / `APPROVED` / `IN_PROGRESS` / `COMPLETED` / `REJECTED` / `PARTIALLY_COMPLETED`

**错误码**

| code | HTTP | 触发条件 |
|------|------|----------|
| `SUBJECT_NOT_VERIFIED` | 422 | 身份核验失败 |
| `RECTIFICATION_NOT_ALLOWED` | 422 | 该字段不允许更正（如审计锁定字段、PCI-DSS 强制保留字段） |
| `CURRENT_VALUE_MISMATCH` | 409 | 提供的 current_value 与服务端当前值不一致（数据已被他人修改） |
| `EVIDENCE_INSUFFICIENT` | 422 | 更正证据不充分 |

**合规说明**

- 更正请求进入法务/合规复核队列（敏感字段如 phone_hash、id_card_hash 必须经 COMPLIANCE_OFFICER 复核）
- 更正完成后保留前后值快照与审计日志（保留 7 年，对齐反洗钱要求）
- 更正不影响已基于原值作出的评分决策合法性，但可触发受影响案件的复核
- 更正结果通过 Webhook 事件 `privacy.rectification.completed` 或 WebSocket 推送

---

## 附录 A: OpenAPI Schema

完整 OpenAPI 3.1 规范见：`docs/openapi.yaml`（机器可读，可生成 SDK）。V1.1 新增端点（`/pipl/*`、`/gnn/*`、`/scores/{id}/shap*`、`/webhooks/{id}/test`、`/webhooks/{id}/deliveries`、`/rules/{id}/versions` 等）已在 OpenAPI 中描述。

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
| V1.1 | 2026-07-27 | 依据 FRD-BASELINE-V1.1 修订：① 新增 §13 PIPL 数据主体权利接口（`/api/v1/pipl/*` 共 8 个：consent、consent/withdraw、consent/{user_id}、data-export、data-export/{task_id}/status、deletion、deletion/{request_id}/status、rectification）；② §5 规则补齐 CRUD 闭环（POST/GET/PUT/DELETE + `/versions` 创建版本 + `/promote` 灰度推进 + `/rollback` 回滚）；③ §6 模型补齐 CRUD 闭环（POST/GET/PUT/DELETE + `/canary` 金丝雀 + `/promote` 晋升 + `/rollback` 回滚 + `/retire` 显式退役）；④ §4 SHAP 改异步（`POST /scores/{id}/shap` + `/status` + `/result` + WebSocket 推送 `transaction.shap_ready`）；⑤ §7 GNN 接口分流到 `/api/v1/gnn/*` 命名空间（`/related/{node_id}` k-hop 邻居 + `/embedding/{node_id}` GraphSAGE 嵌入 + `/community-detection` 团伙检测 + `/community/{community_id}` 团伙详情）；⑥ §11 Webhook 补齐 CRUD（PUT 替代 PATCH）+ `/test` 手动测试 + `/deliveries` 投递记录查询，签名算法明确（HMAC-SHA256、签名串 `{timestamp}.{body}`、Header `X-FRD-Signature: t=,v1=`、防重放 5 分钟、重试 1m/5m/30m/2h/12h 入死信队列）；⑦ §3.4 新增角色 → Scope 映射矩阵（TENANT_ADMIN / MERCHANT_ADMIN / RISK_ANALYST / RISK_MANAGER / AUDITOR / COMPLIANCE_OFFICER 共 6 个角色 × 17 个 scope）；⑧ §2.8 新增 WebSocket 通道；⑨ §4.1 risk_score 改 DECIMAL(5,4)；⑩ 枚举值统一对齐基准（decision / case_status / model_status / rule_status / consent_status / consent_purpose 大写，tenant_plan 小写）；⑪ §2.6 幂等统一为 200 + `X-Idempotent-Replay`，删除 IDEMPOTENT_REPLAY 409；⑫ §2.2 tenant_id 来源优先级（JWT > API Key > X-Tenant-Id 仅 admin）；⑬ §2.6 400/422 边界明确；⑭ §2.7 限流响应头规范 + 重试指数退避+抖动；⑮ §1.2 错别字修正（弔进→演进）；⑯ §10 治理接口冒号动作改斜杠子资源；⑰ §11.11 新增 `rule.promoted` / `rule.rolled_back` 事件 |
| V1.2 | 2026-07-28 | 依据文档-代码一致性审计修订：冒号端点→斜杠（4处）；SHAP 异步口径确认 |
