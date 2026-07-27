# FRD 金融反欺诈系统 测试计划与测试报告

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| V1.0 | 2026-07-27 | 邝振华 | 初版发布 |
| V1.1 | 2026-07-27 | QA Agent | 依据 FRD-BASELINE-V1.1 修订：删除预填虚假测试结果；补等保 2.0 三级测试用例（§11.3）；补 PIPL 合规测试（§11.2）；覆盖率目标对齐基准（§5.1）；压测改 TPS 控制模式（§9.2）；契约测试口径统一（§7.4/§13.2/§16.1）；缺陷遗留标准统一（P1 ≤ 2）；CI 门禁口径统一；测试数据扩充（§3.3）；脱敏方法明确（§3.3）；审计日志时间戳精度升级毫秒级 P0；E2E 冒烟；渗透频率调整 |

> **文档说明**：本文件为测试计划，所有测试结果待项目执行期间填写。测试报告将在 M6 RC 阶段生成独立的 FRD-D07b-V1.0 文档。

| 项 | 值 |
|---|---|
| 文档状态 | 修订稿 |
| 文档版本 | V1.1 |
| 编制日期 | 2026-07-27 |
| 修订基准 | FRD-BASELINE-V1.1 |

---

## 目录

1. [测试概述](#1-测试概述)
2. [测试策略](#2-测试策略)
3. [测试环境](#3-测试环境)
4. [测试用例设计](#4-测试用例设计)
5. [单元测试](#5-单元测试)
6. [集成测试](#6-集成测试)
7. [API 契约测试](#7-api-契约测试)
8. [端到端测试](#8-端到端测试)
9. [性能与压力测试](#9-性能与压力测试)
10. [安全测试](#10-安全测试)
11. [合规测试](#11-合规测试)
12. [可观测性测试](#12-可观测性测试)
13. [测试自动化与 CI](#13-测试自动化与-ci)
14. [测试报告占位（待 M6 RC 阶段填写）](#14-测试报告占位待-m6-rc-阶段填写)
15. [缺陷管理](#15-缺陷管理)
16. [验收标准与签署](#16-验收标准与签署)

---

## 1. 测试概述

### 1.1 测试目标

- **功能正确性**：100% 满足 FRD-D02 需求规格说明书要求
- **性能达标**：评分接口 P99 < 200ms，并发 2000 QPS
- **安全合规**：通过 PCI-DSS v4.0、PIPL、反洗钱法、GB/T 22239 等保 2.0 三级合规检查
- **可靠性**：MTBF > 720h，故障恢复 < 5min
- **可观测**：关键指标 100% 上报，告警延迟 < 30s

### 1.2 测试范围

| 模块 | 范围 | 备注 |
|------|------|------|
| API 网关 | ✓ | 认证、限流、路由 |
| 评分引擎 | ✓ | 规则 + ML 双轨 |
| 规则引擎 | ✓ | DSL 解析、执行、版本管理 |
| ML 引擎 | ✓ | 模型加载、推理、漂移检测 |
| GNN 服务 | ✓ | 团伙检测、子图查询 |
| 案件管理 | ✓ | 工作流、SLA、审计 |
| 报表中心 | ✓ | 生成、导出、订阅 |
| 模型治理 | ✓ | 金丝雀、回滚、Kill Switch |
| Webhook | ✓ | 投递、重试、签名 |
| 前端 UI | ✓ | 5 端（管理员/分析师/规则员/模型员/合规员） |

### 1.3 不在范围

- 第三方数据源（设备指纹、IP 库）内部实现
- 客户端 SDK 内部逻辑（仅做集成测试）
- 基础设施本身（K8s、PostgreSQL、Redis）的内部测试

---

## 2. 测试策略

### 2.1 测试金字塔

```
            ┌──────────┐
            │   E2E    │  5%   ~120 用例
           ┌┴──────────┴┐
          │  契约 + 集成  │  15%  ~360 用例
         ┌┴──────────────┴┐
        │     单元测试      │  80%  ~1800 用例
       └────────────────────┘
```

### 2.2 测试类型分布

| 类型 | 占比 | 数量 | 工具 |
|------|------|------|------|
| 单元测试 | 80% | ~1800 | pytest + Vitest |
| 集成测试 | 10% | ~240 | pytest + Testcontainers |
| 契约测试 | 5% | ~120 | Schemathesis + OpenAPI |
| E2E 测试 | 3% | ~72 | Playwright |
| 性能测试 | 1% | ~24 | Locust + k6 |
| 安全测试 | 1% | ~24 | OWASP ZAP + Bandit |

> ⏳ **当前实现状态（截至 2026-07-27）**：以上为目标用例数。代码库实际仅有 5 个测试文件（backend: test_health.py + test_scoring.py；ml: test_engine.py + test_modalities.py；gnn: test_graph_service.py），距目标差距甚远。测试体系将在 M4-M6 期间逐步建设。

### 2.3 测试原则

- **左移测试**：需求阶段即编写验收用例
- **TDD**：核心模块（评分、规则、模型）必须 TDD
- **契约优先**：API 变更先改 OpenAPI，再生成 SDK 与测试
- **可重现**：测试数据版本化，环境可一键拉起
- **可观测**：每次测试输出 trace_id、coverage、性能指标

---

## 3. 测试环境

### 3.1 环境矩阵

| 环境 | 用途 | 数据 | 部署 |
|------|------|------|------|
| Local | 开发自测 | 模拟数据 | docker-compose |
| Dev | 联调 | 脱敏样本 | docker-compose |
| Test | 功能测试 | 脱敏样本 | K8s 单节点 |
| Staging | 预发 | 生产快照 | K8s 多节点（与生产一致） |
| Prod | 生产 | 真实数据 | K8s 多 AZ |

### 3.2 Staging 环境配置

| 资源 | 规格 | 数量 |
|------|------|------|
| API 节点 | 4C8G | 3 |
| Worker 节点 | 4C8G | 2 |
| PostgreSQL | 8C32G | 主从 |
| Redis | 4C8G | 主从 |
| Neo4j | 4C16G | 1 |
| Prometheus | 2C4G | 1 |
| Grafana | 1C2G | 1 |

### 3.3 测试数据

- **脱敏样本**：从生产采样 1 万条交易，对 PAN/姓名/手机号脱敏
  - 脱敏算法明确：
    - **FPE（Format-Preserving Encryption，格式保留加密）**：用于需要保持格式的字段（如 PAN、手机号、卡 BIN），保留原字段长度与字符集，便于下游消费与格式校验
    - **SHA-256 + 盐（不可逆哈希）**：用于不可逆字段（如 user_account_id、设备指纹），采用 per-tenant 盐值防止彩虹表攻击
    - **掩码（Masking）**：用于展示场景（如卡号 `**** **** **** 1234`、姓名 `张*`）
  - **不可逆性验证**：通过反向计算测试，验证 SHA-256 + 盐字段无法还原原文；FPE 字段在无密钥条件下无法解密
- **合成数据**：用 Faker 生成 10 万条合成交易，覆盖各种风险场景
- **历史欺诈样本**：≥ 1 万条已确认欺诈交易（来自公开数据集 + 内部积累；不足部分通过 SDV/CTGAN 合成扩充方法补齐，保证标签分布与特征分布一致）
- **图数据**：≥ 10 万节点 / 50 万边（含 ≥ 100 个团伙），用于 GNN 团伙检测性能与准确性测试
- **压测合成数据**：按目标 TPS × 时长准备（如 2000 TPS × 1h = 720 万笔），支持循环生成、不重复回放，覆盖各风险等级与渠道分布

---

## 4. 测试用例设计

### 4.1 设计方法

- **等价类划分**：金额、风险分、QPS 等数值输入
- **边界值分析**：风险分阈值（0.6 / 0.85）、限流阈值
- **决策表**：规则 + ML 联合决策矩阵
- **状态迁移**：案件状态机、规则状态机
- **错误猜测**：基于经验设计异常场景
- **因果图**：复杂业务规则（如反洗钱上报条件）

### 4.2 用例编号规范

```
TC-{模块}-{类型}-{序号}
例: TC-SCORE-UNIT-001  评分模块单元测试第 1 条
   TC-CASE-E2E-012     案件模块 E2E 第 12 条
```

### 4.3 用例模板

```yaml
case_id: TC-SCORE-INT-007
title: 评分接口在 ML 引擎降级时回退到纯规则
priority: P0
preconditions:
  - ML 引擎已启动
  - 规则 R001/R002 已发布
steps:
  - 启动评分请求，risk_score < 0.6
  - 临时关闭 ML 引擎
  - 再次发送相同请求
expected:
  - 第 1 次：decision=ALLOW, model_version=ml_xgb_v3.2.1
  - 第 2 次：decision=ALLOW, model_version=null, rule_hits=[R001]
  - 响应时间 < 200ms
tags: [regression, scoring, fallback]
```

---

## 5. 单元测试

### 5.1 覆盖率与通过率要求

#### 5.1.1 通过率要求（对齐 FRD-BASELINE-V1.1 §2.1）

| 测试类型 | 通过率目标 |
|------|------|
| 单元测试通过率 | ≥ 99% |
| 契约测试通过率 | 100%（或 ≥ 95% 且剩余有书面豁免理由） |
| 集成测试通过率 | ≥ 95% |
| E2E 测试通过率 | ≥ 95% |

#### 5.1.2 行覆盖率要求（对齐 FRD-BASELINE-V1.1 §2.1）

| 模块 | 行覆盖 | 分支覆盖 | 备注 |
|------|--------|----------|------|
| 评分引擎 | ≥ 90% | ≥ 85% | 核心模块 |
| 规则引擎 | ≥ 90% | ≥ 85% | 核心模块 |
| ML 引擎 | ≥ 75% | ≥ 70% | ML/GNN 类 |
| GNN 服务 | ≥ 75% | ≥ 70% | ML/GNN 类 |
| 案件管理 | ≥ 85% | ≥ 80% | - |
| 通用工具 | ≥ 80% | ≥ 75% | - |
| **总体** | **≥ 85%** | **≥ 80%** | - |

### 5.2 后端单元测试（pytest）

#### 5.2.1 示例用例

```python
# tests/unit/test_score_engine.py
class TestScoreEngine:
    def test_low_risk_transaction_returns_allow(self, sample_tx):
        result = score_engine.score(sample_tx)
        assert result.decision == Decision.ALLOW
        assert result.risk_score < 0.3

    def test_high_amount_triggers_rule(self, sample_tx):
        sample_tx.amount = 10_000_00  # 1万
        result = score_engine.score(sample_tx)
        assert any(r.rule_id == "R001" for r in result.rule_hits)

    def test_ml_engine_failure_falls_back_to_rules(self, sample_tx, monkeypatch):
        monkeypatch.setattr(ml_engine, "predict", side_effect=Exception("ML down"))
        result = score_engine.score(sample_tx)
        assert result.model_version is None
        assert result.decision in [Decision.ALLOW, Decision.REVIEW]
```

#### 5.2.2 关键模块用例

| 模块 | 用例数 | 关键场景 |
|------|--------|----------|
| 评分引擎 | 120 | 各种 risk_score 边界、规则 + ML 融合、降级 |
| 规则 DSL 解析 | 80 | 语法错误、聚合函数、嵌套条件 |
| 模型推理 | 60 | 多模态融合、特征缺失、SHAP 输出 |
| GNN 检测 | 40 | 种子选择、深度控制、置信度阈值 |
| 案件工作流 | 50 | 状态转换、SLA 计算、审计日志 |
| 数据访问层 | 80 | 多租户隔离、分页、软删除 |
| 加密/脱敏 | 30 | Fernet 加密、PAN 脱敏、JWT |
| 限流 | 20 | QPS 阈值、突发桶、租户级别 |

### 5.3 前端单元测试（Vitest）

#### 5.3.1 示例用例

```typescript
// src/views/transaction/__tests__/TransactionDetail.spec.ts
describe('TransactionDetail', () => {
  it('renders SHAP explanation when ML model used', async () => {
    const wrapper = mount(TransactionDetail, { props: { tx: mockTxWithML } })
    await flushPromises()
    expect(wrapper.find('.shap-chart').exists()).toBe(true)
  })

  it('shows fallback banner when ML unavailable', async () => {
    const wrapper = mount(TransactionDetail, { props: { tx: mockTxFallback } })
    expect(wrapper.find('.fallback-banner').text()).toContain('规则模式')
  })
})
```

#### 5.3.2 前端用例覆盖

| 模块 | 用例数 | 说明 |
|------|--------|------|
| 通用组件 | 200 | 表单、表格、图表 |
| 业务页面 | 400 | 交易、案件、规则、模型 |
| Store | 100 | Pinia 状态管理 |
| 工具函数 | 150 | 时间、金额、脱敏 |
| 总计 | 850 | - |

---

## 6. 集成测试

### 6.1 测试范围

- API ↔ 数据库（PostgreSQL + Neo4j）
- API ↔ Redis（缓存 + pubsub）
- API ↔ Celery（异步任务）
- API ↔ ML 引擎
- API ↔ GNN 服务
- Webhook 投递
- 第三方数据源（Mock）

### 6.2 工具：Testcontainers

```python
@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15") as pg:
        yield pg

@pytest.fixture(scope="session")
def neo4j_container():
    with Neo4jContainer("neo4j:5.11") as neo:
        yield neo
```

### 6.3 关键集成场景

| 场景 ID | 描述 | 优先级 |
|---------|------|--------|
| INT-001 | 评分请求落库 + 案件自动创建 | P0 |
| INT-002 | 规则发布后 5 分钟内全节点生效 | P0 |
| INT-003 | GNN 任务异步执行 + 结果落库 | P0 |
| INT-004 | Webhook 投递失败 5 次后归档死信 | P1 |
| INT-005 | 模型金丝雀启动后流量切分正确 | P0 |
| INT-006 | 漂移告警触发自动回滚 | P0 |
| INT-007 | Kill Switch 启动后所有评分走纯规则 | P0 |
| INT-008 | 多租户数据隔离（A 租户不能查 B 租户） | P0 |
| INT-009 | 案件状态变更写入审计日志（毫秒级时间戳） | P0 |
| INT-010 | 反洗钱报告生成 + 数字签名 | P1 |

### 6.4 集成用例示例

```python
# tests/integration/test_score_to_case.py
async def test_high_risk_transaction_creates_case(
    async_client, db_session, rule_engine
):
    # 1. 发布规则 R001（大额夜间交易）
    await rule_engine.publish("R001")

    # 2. 发送高分交易
    tx = high_risk_tx_factory()
    resp = await async_client.post("/transactions/score", json=tx)
    assert resp.json()["data"]["decision"] == "REVIEW"

    # 3. 验证案件自动创建
    case_id = resp.json()["data"]["case_id"]
    case = await db_session.get(Case, case_id)
    assert case.status == CaseStatus.OPEN
    assert case.priority == Priority.P1
```

---

## 7. API 契约测试

### 7.1 工具：Schemathesis

基于 OpenAPI 3.1 规范自动生成测试用例，验证 API 实现与契约一致性。

### 7.2 测试范围

- 所有 `/api/v1/*` 端点
- 请求参数边界值
- 响应 schema 一致性
- 状态码覆盖
- 鉴权与权限

### 7.3 配置示例

```yaml
# tests/contract/schemathesis.yaml
base_url: http://localhost:8000
schema_path: docs/openapi.yaml
auth:
  type: bearer
  token: test_token
hypothesis:
  max_examples: 100
  deadline: 5000
checks:
  - status_code_conformance
  - content_type_conformance
  - response_schema_conformance
  - not_a_server_error
```

### 7.4 契约通过率目标

- **目标**：100% 通过率
- **最低要求**：≥ 95% 通过率且 0 失败，剩余 ≤ 5% 必须有书面豁免理由（记录于 `docs/waivers/contract-waivers.md`）

### 7.5 运行命令

```bash
# 后端契约测试
pytest tests/contract/ -v --cov=app/api

# 自动生成测试报告
schemathesis run docs/openapi.yaml --base-url=http://staging \
  --checks all --hypothesis-max-examples=200 \
  --junit-xml=reports/contract.xml
```

---

## 8. 端到端测试

### 8.1 工具：Playwright

### 8.2 关键 E2E 场景

| 场景 ID | 角色 | 流程 | 优先级 |
|---------|------|------|--------|
| E2E-001 | Analyst | 登录 → 查看案件 → 处理 → 结案 | P0 |
| E2E-002 | Rule Operator | 创建规则 → 试运行 → 评审 → 发布 | P0 |
| E2E-003 | ML Engineer | 启动金丝雀 → 推进 → 晋升 | P0 |
| E2E-004 | ML Engineer | 紧急回滚 | P0 |
| E2E-005 | Compliance | 生成反洗钱报告 | P0 |
| E2E-006 | Tenant Admin | 创建用户 → 分配角色 → 禁用 | P0 |
| E2E-007 | Analyst | GNN 检测 → 查看团伙 → 创建案件 | P1 |
| E2E-008 | Analyst | 交易详情 → SHAP 解释 → 反馈标签 | P1 |
| E2E-009 | 所有角色 | MFA 登录、密码重置 | P0 |
| E2E-010 | 所有角色 | 跨角色越权访问全部 403 | P0 |

### 8.3 E2E 用例示例

```typescript
// tests/e2e/case-management.spec.ts
test('Analyst can process and close a case', async ({ page }) => {
  await loginAs(page, 'analyst')
  await page.goto('/cases/123')
  await page.click('text=开始处理')
  await page.fill('[placeholder=备注]', '已联系持卡人核实')
  await page.click('text=提交')
  await page.click('text=结案')
  await page.selectOption('[name=conclusion]', 'CONFIRMED_FRAUD')
  await page.fill('[name=loss_amount]', '50000')
  await page.click('text=确认结案')
  await expect(page.locator('.status')).toHaveText('已关闭')
})
```

---

## 9. 性能与压力测试

### 9.1 性能目标

| 接口 | P50 | P95 | P99 | TPS |
|------|-----|-----|-----|-----|
| POST /transactions/score | < 50ms | < 150ms | < 200ms | 2000 |
| GET /transactions/{id} | < 30ms | < 100ms | < 150ms | 5000 |
| POST /rules | < 100ms | < 300ms | < 500ms | 50 |
| GET /cases | < 50ms | < 200ms | < 500ms | 1000 |
| POST /graph/detect（异步） | < 200ms | < 500ms | < 1000ms | 100 |

### 9.2 工具：Locust + k6（TPS 控制模式）

采用 **TPS 控制模式**（constant-arrival-rate / constant_total_ips），按目标 TPS 恒定速率施压，避免用户数模型导致的实际 TPS 波动。

#### 9.2.1 k6 脚本示例（constant-arrival-rate）

```javascript
// tests/perf/k6-score-constant.js
import { check } from 'k6';
import http from 'k6/http';

const BASE = __ENV.BASE_URL || 'http://staging:8000';
const TOKEN = __ENV.TOKEN || 'test_token';

export const options = {
  scenarios: {
    constant_load: {
      executor: 'constant-arrival-rate',
      rate: __ENV.TARGET_TPS || 1000,   // 目标 TPS
      timeUnit: '1s',
      duration: __ENV.DURATION || '1h',
      preAllocatedVUs: 1500,
      maxVUs: 3000,
    },
  },
};

const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` };

export default function () {
  const res = http.post(`${BASE}/api/v1/transactions/score`, JSON.stringify(txFactory()), { headers });
  check(res, {
    'status 200': r => r.status === 200,
    'latency < 200ms': r => r.timings.duration < 200,
  });
}

function txFactory() {
  // 循环生成交易，覆盖各风险等级与渠道
  return { /* ... */ };
}
```

#### 9.2.2 Locust 脚本示例（constant_total_ips）

```python
# tests/perf/locustfile_constant.py
class FraudDetectionConstantUser(HttpUser):
    wait_time = constant_pacing(0)  # 由 spawn_rate 控制速率

    @task
    def score_transaction(self):
        self.client.post("/api/v1/transactions/score",
            json=tx_factory(),
            headers=self.headers,
        )

# 启动：locust --headless -u 1000 -r 100 -run-time 1h --spawn-rate 控制为恒定 TPS
# 推荐使用 constant_total_ips（每秒恒定新增请求数）模式
```

#### 9.2.3 压测场景（TPS 控制模式）

| 场景 | 目标 TPS | 持续 | 目标 / 关注点 |
|------|----------|------|---------------|
| 日常负载 | 1000 | 1h | P99 < 200ms，资源稳定 |
| 峰值负载 | 2000 | 30min | P99 < 200ms，无错误率上升 |
| 极限压测 | 3000 | 10min | 找瓶颈，记录吞吐拐点与错误率拐点 |
| 持久压测 | 1000 | 24h | 无内存泄漏，GC 暂停正常 |
| 故障注入 | 1000 | 5min | ML 宕机时降级成功，P99 < 200ms |

#### 9.2.4 测试数据准备

- 按 **目标 TPS × 时长** 准备测试数据（如 2000 TPS × 1h = 720 万笔），支持循环生成、不重复回放
- 图数据扩至 **≥ 10 万节点 / 50 万边**（含 ≥ 100 个团伙）
- 历史欺诈样本 **≥ 1 万条**（不足部分用 SDV/CTGAN 合成扩充）

### 9.3 性能监控

压测过程中监控：

- API 响应时间分位数
- 数据库连接池使用率
- Redis 命中率
- CPU / 内存 / IO
- 网络吞吐
- GC 暂停时间

### 9.4 容量规划

| 容量指标 | 当前 | 6个月 | 12个月 |
|---------|------|-------|--------|
| TPS | 500 | 2000 | 5000 |
| 数据库存储 | 500GB | 2TB | 5TB |
| Neo4j 存储 | 50GB | 200GB | 500GB |
| API 节点数 | 3 | 6 | 12 |

---

## 10. 安全测试

### 10.1 测试范围

| 类型 | 工具 | 频率 |
|------|------|------|
| 静态扫描 | Bandit + Semgrep | 每次 PR |
| 依赖扫描 | Safety + pip-audit | 每日 |
| 容器扫描 | Trivy | 每次构建 |
| DAST | OWASP ZAP | 每周 |
| 渗透测试 | 第三方 | **上线前 1 次 + 每年复测** |
| 密钥扫描 | GitLeaks | 每次 PR |

### 10.2 关键安全用例

| 用例 ID | 描述 | 优先级 |
|---------|------|--------|
| SEC-001 | SQL 注入测试（所有查询接口） | P0 |
| SEC-002 | 路径遍历测试（文件上传/下载） | P0 |
| SEC-003 | XSS 测试（备注/案件描述） | P0 |
| SEC-004 | CSRF 测试 | P0 |
| SEC-005 | 越权测试（横向 + 纵向） | P0 |
| SEC-006 | 多租户数据隔离 | P0 |
| SEC-007 | JWT 伪造/过期/重放 | P0 |
| SEC-008 | 限流绕过测试 | P1 |
| SEC-009 | 明文 PAN 上传拦截 | P0 |
| SEC-010 | PII 加密落库验证 | P0 |
| SEC-011 | 审计日志篡改测试（含毫秒级时间戳） | P0 |
| SEC-012 | 敏感字段脱敏（API 响应） | P0 |

### 10.3 越权测试矩阵

```
测试方法：每对（角色A, 资源B）尝试访问，预期 403

        资源 →  案件  规则  模型  GNN  审计  系统管理
Analyst       R     R    R    R    -    -
Rule Op       R     R/W  R    R    -    -
ML Engineer   R     R    R/W  R    -    -
Compliance    R     R    R    R    R/W  -
Tenant Admin  R     R    R    R    R    R/W
```

跨租户测试：租户 A 的用户访问租户 B 的资源，必须返回 404（不能 403，避免暴露资源存在性）。

### 10.4 PCI-DSS 合规测试

| 测试项 | 验证方法 | 频率 |
|--------|----------|------|
| PAN 不存储 | 数据库扫描 + 字段级加密验证 | 每月 |
| PAN 不传输 | 网络流量抓包 + 日志扫描 | 每月 |
| 卡数据加密 | Token 化验证 + 密钥轮换 | 每季度 |
| 访问控制 | 权限矩阵审计 | 每月 |
| 审计日志 | 完整性验证 + 7 年保留 + **毫秒级时间戳（P0）** | 每月 |

> 审计日志时间戳精度升级为毫秒级（P0）。理由：法律取证需要毫秒级精度以厘清事件先后顺序。原 P1 级别提升至 P0。

---

## 11. 合规测试

### 11.1 反洗钱法

| 测试项 | 验证方法 |
|--------|----------|
| STR 上报 | 案件标记可疑 → 自动生成报告 → 数字签名 |
| CTR 上报 | 大额交易（> 5万）自动标记 → 报告生成 |
| 客户身份识别 | KYC 信息完整性校验 |
| 可疑交易监测 | 规则引擎触发反洗钱规则 |
| 报告保留 | 上报凭证保留 7 年 |
| 上报通道对接 | 客户/第三方提供接口，FRD 完成对接联调（统一口径，D11 §8.3） |

### 11.2 PIPL 合规测试

> 对齐 FRD-BASELINE-V1.1 §7.1 PIPL 数据主体权利接口。

#### 11.2.1 测试项概览

| 测试项 | 验证方法 | 优先级 |
|--------|----------|--------|
| 数据导出权 | 用户提交导出请求 → 30 天内响应 | P0 |
| 被遗忘权 | 用户提交删除请求 → 数据删除（保留法律要求最小集） | P0 |
| 数据使用审计 | 查询个人数据被访问记录 | P0 |
| 最小化原则 | 字段必要性评审 | P0 |
| 跨境传输 | 数据本地化存储验证 | P0 |

#### 11.2.2 详细测试用例

**TC-PIPL-001 告知同意管理测试**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-001 |
| 优先级 | P0 |
| 前置条件 | 用户尚未授予 TRANSACTION_SCORING 同意 |
| 步骤 | 1. 调用 `POST /consent` 授予 TRANSACTION_SCORING 同意<br>2. 调用 `GET /consent` 查询同意记录<br>3. 调用 `POST /consent`（withdraw）撤回同意<br>4. 再次调用 `GET /consent` 查询状态 |
| 预期 | 1. 返回 consent_status=GRANTED<br>2. 查询返回 GRANTED + purpose + 时间戳<br>3. 撤回成功<br>4. 返回 consent_status=WITHDRAWN |
| 通过标准 | 全部预期达成；同意/撤回时间戳为毫秒级；撤回后该用户数据不再用于评分 |

**TC-PIPL-002 最小必要字段控制测试**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-002 |
| 优先级 | P0 |
| 前置条件 | 评分接口配置了字段必要性白名单 |
| 步骤 | 1. 提交评分请求，包含非必要字段（如身份证号、住址）<br>2. 检查评分引擎是否消费非必要字段<br>3. 检查落库字段集合 |
| 预期 | 非必要字段在网关层被剥离；评分引擎仅消费白名单字段；数据库不存储非必要 PII |
| 通过标准 | 非必要字段不入库、不进模型；字段必要性评审记录可查 |

**TC-PIPL-003 自动化决策解释权测试（对接 SHAP）**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-003 |
| 优先级 | P0 |
| 前置条件 | ML 引擎在线，SHAP 解释接口可用 |
| 步骤 | 1. 提交评分请求得到 decision=REVIEW/DENY<br>2. 调用解释接口 `GET /scores/{decision_id}/shap/result`<br>3. 校验返回 SHAP 贡献度 Top-N 特征 |
| 预期 | 返回结构化 SHAP 解释，含特征名、贡献度、方向；可被用户理解 |
| 通过标准 | REVIEW/DENY 决策 100% 可解释；SHAP 输出与模型版本一致；纯规则决策返回规则命中解释 |

**TC-PIPL-004 数据可携带权测试（GET /pipl/data-export）**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-004 |
| 优先级 | P0 |
| 前置条件 | 用户存在交易与评分记录 |
| 步骤 | 1. 调用 `POST /pipl/data-export` 申请导出<br>2. 调用 `GET /pipl/data-export/{task_id}/status` 查询状态<br>3. 状态为 READY 后下载导出文件 |
| 预期 | 1. 返回 request_id<br>2. 状态流转 PENDING→PROCESSING→READY<br>3. 导出文件为 JSON/CSV，含该用户全部个人数据 |
| 通过标准 | 30 天内响应；导出数据完整、结构化、可机读；导出操作写入审计日志 |

**TC-PIPL-005 数据删除权测试（POST /pipl/deletion）**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-005 |
| 优先级 | P0 |
| 前置条件 | 用户存在个人数据 |
| 步骤 | 1. 调用 `POST /pipl/deletion` 申请删除<br>2. 调用 `GET /pipl/deletion/{request_id}/status` 查询状态<br>3. 删除完成后查询该用户数据 |
| 预期 | 1. 返回 request_id<br>2. 状态流转 PENDING→PROCESSING→DONE<br>3. 个人数据被删除；保留法律要求最小集（如反洗钱上报记录 7 年） |
| 通过标准 | 个人数据删除；法律保留集明确隔离且不可用于业务；删除操作写入审计日志 |

**TC-PIPL-006 跨境传输评估测试（确认数据本地化）**

| 项 | 内容 |
|---|---|
| 用例 ID | TC-PIPL-006 |
| 优先级 | P0 |
| 前置条件 | 部署于阿里云 cn-hangzhou |
| 步骤 | 1. 检查所有数据存储区域配置<br>2. 检查 OSS/RDS/Neo4j 备份区域<br>3. 检查 LLM API 调用是否走国内合规服务（通义千问/DeepSeek，不走 OpenAI）<br>4. 检查跨境传输日志 |
| 预期 | 所有数据存储于境内；备份区域为境内；LLM 调用不触发数据出境；无跨境传输记录 |
| 通过标准 | 数据本地化 100%；跨境传输评估报告归档；OpenAI 等境外服务零调用 |

### 11.3 等保 2.0 三级测试用例

> 对齐 FRD-BASELINE-V1.1 §7.2 与 GB/T 22239 等保 2.0 三级控制点。覆盖 6 类控制点，每类至少 3 个测试用例。

#### 11.3.1 物理与环境安全（云等保合规机房验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-SEC-001 | 1. 查询阿里云 cn-hangzhou 机房等保备案证明<br>2. 核对备案编号与等级（三级） | 云厂商提供等保 2.0 三级备案证明，编号可查 | 备案证明编号归档；等级 ≥ 三级 |
| TC-EHSS-SEC-002 | 1. 检查云物理环境控制项（电力、温湿度、消防、防雷）<br>2. 核对云厂商合规白皮书 | 云厂商物理环境控制项满足等保 2.0 三级要求 | 合规白皮书归档；控制项全覆盖 |
| TC-EHSS-SEC-003 | 1. 验证云厂商 ISO 27001 / SOC 2 / 等保测评报告<br>2. 核对测评机构资质 | 云厂商持有有效认证且测评机构具备资质 | 认证证书归档；测评机构资质可查 |

#### 11.3.2 安全通信网络（VPC 隔离 + 安全组规则 + NetworkPolicy + 跨 AZ 备份验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-NET-001 | 1. 检查 VPC 划分（CDE / non-CDE / 管理）<br>2. 验证 VPC 间默认隔离<br>3. 仅允许白名单端口互通 | 三类 VPC 隔离；非白名单流量 100% 拦截 | VPC 隔离规则生效；拦截日志可查 |
| TC-EHSS-NET-002 | 1. 检查安全组规则（入站/出站最小化）<br>2. 验证默认拒绝策略<br>3. 测试非授权端口访问 | 安全组最小化开放；非授权端口拒绝 | 安全组规则审计通过；非授权访问被拒 |
| TC-EHSS-NET-003 | 1. 检查 K8s NetworkPolicy（命名空间隔离）<br>2. 验证 Pod 间默认拒绝<br>3. 仅允许标的应用互通 | NetworkPolicy 默认拒绝；仅标的应用互通 | NetworkPolicy 配置审计通过 |
| TC-EHSS-NET-004 | 1. 检查跨 AZ 备份策略（RDS / OSS）<br>2. 验证备份可恢复 | 数据库与对象存储跨 AZ 备份；备份可成功恢复 | 跨 AZ 备份配置生效；恢复演练通过 |

#### 11.3.3 安全区域边界（WAF 规则 + IDS/IPS 告警 + DDoS 防护验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-BND-001 | 1. 检查阿里云 WAF 规则集（OWASP Top 10）<br>2. 注入 SQL/XSS 测试 payload<br>3. 检查拦截日志 | WAF 拦截 OWASP Top 10 攻击；拦截日志含毫秒级时间戳 | 拦截率 100%；日志可查 |
| TC-EHSS-BND-002 | 1. 模拟异常流量（端口扫描、暴力破解）<br>2. 检查 IDS/IPS 告警 | IDS/IPS 触发告警；告警推送至安全管理中心 | 告警延迟 < 30s；告警记录可查 |
| TC-EHSS-BND-003 | 1. 模拟 DDoS 流量（SYN Flood / UDP Flood）<br>2. 验证阿里云 DDoS 高防清洗 | DDoS 高防自动清洗；业务无中断 | 清洗生效；业务 P99 < 200ms |

#### 11.3.4 安全计算环境（堡垒机访问 + HIDS 告警 + 主机加固 + 可信验证 + 剩余信息保护验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-CMP-001 | 1. 直连 SSH 访问生产节点<br>2. 改为堡垒机访问<br>3. 检查堡垒机会话录像与命令审计 | 直连 SSH 被拒；堡垒机访问成功；命令审计完整 | 直连 0 成功；堡垒机会话 100% 录像 |
| TC-EHSS-CMP-002 | 1. 模拟主机异常（异常进程、文件篡改）<br>2. 检查 HIDS 告警 | HIDS 触发告警；告警推送至安全管理中心 | 告警延迟 < 60s；告警记录可查 |
| TC-EHSS-CMP-003 | 1. 检查主机加固基线（CIS Benchmark）<br>2. 验证可信启动（TPM/可信链） | 主机加固基线达标；可信启动通过 | CIS 扫描通过；可信验证通过 |
| TC-EHSS-CMP-004 | 1. 验证剩余信息保护（内存清零、磁盘擦除）<br>2. 释放敏感数据后检查内存/磁盘残留 | 敏感数据释放后内存清零；磁盘擦除后无残留 | 内存/磁盘残留检测为 0 |

#### 11.3.5 安全管理中心（集中监控 + 审计日志集中 + 权限集中验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-MGT-001 | 1. 检查 Prometheus + Grafana 集中监控<br>2. 验证关键指标全量上报<br>3. 触发告警验证通知链路 | 监控覆盖所有节点与组件；告警通知链路畅通 | 监控覆盖率 100%；告警延迟 < 30s |
| TC-EHSS-MGT-002 | 1. 检查审计日志集中收集（Loki / ELK）<br>2. 验证审计日志不可篡改<br>3. 验证审计日志 7 年保留策略 | 审计日志集中存储；不可篡改；保留 7 年 | 集中收集 100%；哈希链完整性通过 |
| TC-EHSS-MGT-003 | 1. 检查权限集中管理（IAM）<br>2. 验证最小权限原则<br>3. 验证权限变更审计 | 权限集中管理；最小权限；变更可审计 | 权限矩阵审计通过；变更记录可查 |

#### 11.3.6 安全审计（审计日志 7 年保留 + 哈希链完整性 + 不可篡改验证）

| 用例 ID | 步骤 | 预期 | 通过标准 |
|---|---|---|---|
| TC-EHSS-AUD-001 | 1. 检查审计日志保留策略（7 年）<br>2. 验证 OSS 生命周期规则<br>3. 抽样历史日志可查询 | 保留策略 7 年；生命周期规则生效；历史日志可查 | 7 年保留配置通过；抽样日志可查 |
| TC-EHSS-AUD-002 | 1. 计算日志块哈希链（前一块哈希嵌入后一块）<br>2. 篡改某条日志<br>3. 重新校验哈希链 | 哈希链校验失败，定位篡改位置 | 正常日志哈希链校验通过；篡改可检测 |
| TC-EHSS-AUD-003 | 1. 尝试以非授权身份修改/删除审计日志<br>2. 验证 WORM（一写多读）存储 | 修改/删除被拒；WORM 存储锁定 | 非授权操作 0 成功；WORM 生效 |
| TC-EHSS-AUD-004 | 1. 校验审计日志时间戳精度<br>2. 对比相邻事件时间戳 | 时间戳精度为毫秒级（ms） | 100% 审计日志时间戳精度 ≤ 1ms |

---

## 12. 可观测性测试

### 12.1 指标上报

| 指标 | 验证 |
|------|------|
| Prometheus metrics | GET /metrics 返回 200，格式正确 |
| 业务指标 | 评分次数、决策分布、规则命中数 |
| 性能指标 | P50/P95/P99 延迟 |
| 模型指标 | AUC、PSI、特征分布 |
| GNN 指标 | 检测任务数、团伙数 |

### 12.2 告警

| 告警 | 触发条件 | 验证方法 |
|------|----------|----------|
| API 错误率 | > 1% | 注入错误 |
| 延迟告警 | P99 > 200ms | 注入延迟 |
| 模型漂移 | PSI > 0.25 | 注入分布偏移 |
| 金丝雀失败 | precision_drop > 阈值 | 注入坏模型 |
| 审计日志中断 | 5min 无日志 | 关闭审计服务 |

### 12.3 分布式追踪

- 所有 API 请求必须有 trace_id
- trace_id 跨服务透传（HTTP Header `X-Trace-Id`）
- Jaeger 可查询完整调用链

---

## 13. 测试自动化与 CI

### 13.1 CI 流水线（GitHub Actions）

| 流水线 | 触发 | 内容 | 时长 |
|--------|------|------|------|
| lint | PR | Ruff + mypy + ESLint | 2min |
| unit-test | PR | 后端 + 前端单元测试 | 5min |
| integration-test | PR | Testcontainers 集成测试 | 10min |
| contract-test | PR | Schemathesis 契约测试 | 8min |
| e2e-smoke | PR（关键路径） | Playwright E2E 冒烟子集（评分/规则/案件） | 5min |
| e2e-test | main 合并 | Playwright E2E 全量 | 15min |
| perf-test | 每日 | k6 / Locust 性能测试（TPS 控制模式） | 20min |
| security-scan | 每日 | Trivy + Bandit + ZAP | 10min |
| coverage-report | main 合并 | 覆盖率上报 Codecov | 3min |

> **E2E 冒烟测试**：e2e-test 不仅在 main 合并触发，PR 阶段也跑 E2E 子集（冒烟）。关键路径 PR（评分/规则/案件）必须跑冒烟，冒烟子集覆盖 E2E-001 / E2E-002 / E2E-009 / E2E-010。

### 13.2 质量门禁

PR 合并必须满足：

- lint 0 error
- **unit-test 0 失败（通过率 100%）** — 明确指"无失败用例"，与验收 ≥ 99% 对齐
- integration-test 0 失败（通过率 ≥ 95%）
- **contract-test ≥ 95% 通过且 0 失败**（剩余 ≤ 5% 必须有书面豁免理由）
- 行覆盖率 ≥ 85%（总体）；评分/规则引擎核心 ≥ 90%；ML/GNN ≥ 75%
- 安全扫描 0 高危漏洞
- 至少 1 名 reviewer approve

---

## 14. 测试报告占位（待 M6 RC 阶段填写）

> **本节为测试报告占位**。所有测试结果（包括测试执行汇总、覆盖率实测值、性能测试实测值、安全测试实测值、合规测试实测值）将在 M6 RC 阶段（2027-01-31）由 QA Agent 执行测试后填写，并生成独立的测试报告文档 **FRD-D07b-V1.0**。
>
> 本测试计划保留以下内容作为执行框架（不含实测值）：
> - 测试目标（§1.1）
> - 测试方法与工具（§2、§5-§12）
> - 通过标准（§5.1、§7.4、§13.2、§16.1）
> - 测试用例模板（§4.3）
>
> 测试报告（FRD-D07b-V1.0）将包含以下章节（待填写）：
> - §14.1 测试执行汇总（计划/执行/通过/失败/阻塞/通过率）
> - §14.2 覆盖率（实测行覆盖/分支覆盖 vs 目标）
> - §14.3 性能测试结果（实测 P50/P95/P99/TPS vs 目标）
> - §14.4 安全测试结果
> - §14.5 合规测试结果（PCI-DSS / PIPL / 反洗钱 / 等保 2.0 三级）

---

## 15. 缺陷管理

### 15.1 缺陷分级

| 等级 | 定义 | SLA |
|------|------|-----|
| P0 阻断 | 核心功能不可用 | 4h 内修复 |
| P1 严重 | 主要功能受影响 | 24h 内修复 |
| P2 一般 | 次要功能受影响 | 7 天内修复 |
| P3 轻微 | 体验问题 | 下个迭代修复 |

### 15.2 缺陷统计（待 M6 RC 阶段填写）

> 缺陷统计将在测试执行期间填写，包含各等级缺陷的发现/已修复/遗留/阻断发布数量。模板如下：

| 等级 | 发现 | 已修复 | 遗留 | 阻断发布 |
|------|------|--------|------|----------|
| P0 | 待填写 | 待填写 | 待填写 | 待填写 |
| P1 | 待填写 | 待填写 | 待填写 | 待填写 |
| P2 | 待填写 | 待填写 | 待填写 | 待填写 |
| P3 | 待填写 | 待填写 | 待填写 | 待填写 |
| **总计** | **待填写** | **待填写** | **待填写** | - |

### 15.3 遗留缺陷清单（待 M6 RC 阶段填写）

> 遗留缺陷清单将在测试执行期间填写，每条包含：缺陷 ID、等级、描述、影响、缓解措施、修复计划。模板如下：

| ID | 等级 | 描述 | 影响 | 缓解措施 | 修复计划 |
|----|------|------|------|----------|----------|
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 |

### 15.4 缺陷流程

```
新建（New） → 确认（Confirmed） → 修复中（Fixing） → 待验证（Pending Review） → 关闭（Closed）
                                            ↓
                                      重新打开（Reopened）
```

> **已知改进项（非缺陷，计划性升级）**：审计日志时间戳精度由秒级升级为毫秒级，优先级由 P1 提升至 P0。理由：法律取证需要毫秒级精度以厘清事件先后顺序。该项为 V1.1 修订计划项，不作为遗留缺陷统计。

---

## 16. 验收标准与签署

### 16.1 验收标准

> 验收标准对齐 FRD-BASELINE-V1.1 §2.1 / §2.2。**D11 为最终验收口径**，本表为 D07 测试验收口径，与 D11 保持一致。

| 项 | 标准 | 备注 |
|----|------|------|
| 功能完整性 | 100% 满足 D02 需求 | RTM 矩阵全覆盖 |
| 单元测试通过率 | ≥ 99% | 0 失败用例 |
| 集成测试通过率 | ≥ 95% | - |
| 契约测试通过率 | 100%（或 ≥ 95% 且剩余有书面豁免理由） | 对齐 §7.4 / §13.2 |
| E2E 测试通过率 | ≥ 95% | - |
| 行覆盖率（总体） | ≥ 85% | 对齐 BASELINE §2.1 |
| 行覆盖率（评分/规则引擎核心） | ≥ 90% | - |
| 行覆盖率（ML/GNN） | ≥ 75% | - |
| 性能 P99（评分接口） | < 200ms | - |
| 安全高危漏洞 | 0 | - |
| 合规 | PCI-DSS / PIPL / 反洗钱 / 等保 2.0 三级 | 四项均需通过测评 |
| P0 缺陷遗留 | 0 | 0 容忍 |
| P1 缺陷遗留 | ≤ 2 | 必须有缓解措施与修复计划 |
| P2 缺陷遗留 | ≤ 10 | 必须有修复计划 |
| P3 缺陷遗留 | ≤ 30 | 可后续修复 |

> 缺陷遗留标准对齐 FRD-BASELINE-V1.1 §2.2 与 D11 最终验收口径。

### 16.2 验收签署

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 项目经理 | 邝振华 | _________ | ___________ |
| 技术负责人 | _________ | __________ | ___________ |
| 测试负责人 | _________ | __________ | ___________ |
| 安全负责人 | _________ | __________ | ___________ |
| 合规负责人 | _________ | __________ | ___________ |
| 业务负责人 | _________ | __________ | ___________ |

---

## 附录 A: 测试工具版本

| 工具 | 版本 |
|------|------|
| pytest | 8.3 |
| Vitest | 2.0 |
| Playwright | 1.45 |
| Locust | 2.29 |
| k6 | 0.51 |
| Schemathesis | 3.36 |
| OWASP ZAP | 2.14 |
| Bandit | 1.7 |
| Trivy | 0.51 |
| Testcontainers | 4.7 |

## 附录 B: 测试用例索引

详见 `tests/` 目录的 README 与 CI 配置 `.github/workflows/`。

## 附录 C: 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| V1.0 | 2026-07-27 | 初版发布 |
| V1.1 | 2026-07-27 | 依据 FRD-BASELINE-V1.1 修订：<br>**Blocker 1**：删除 §14/§15/§16 全部预填虚假测试结果（实测值、通过标记、结论性表述），§14 改为测试报告占位，待 M6 RC 阶段生成 FRD-D07b-V1.0；文档开头新增"测试计划"说明<br>**Blocker 2**：新增 §11.3 等保 2.0 三级测试用例（6 类控制点，每类 ≥3 用例）<br>**Blocker 3**：§5.1 覆盖率目标对齐基准（总体 ≥ 85%、评分/规则 ≥ 90%、ML/GNN ≥ 75%）<br>**Blocker 4**：§9.2 压测改 TPS 控制模式（k6 constant-arrival-rate / Locust constant_total_ips），日常 1000 TPS×1h、峰值 2000 TPS×30min、极限 3000 TPS×10min<br>**Blocker 5**：契约测试口径统一（§7.4 目标 100%/最低 95%、§13.2 门禁 ≥95% 且 0 失败、§16.1 验收 100% 或 ≥95% 含豁免）<br>**Blocker 6**：§16.1 缺陷遗留标准统一（P0=0、P1≤2、P2≤10、P3≤30），注明 D11 为最终验收口径<br>**Blocker 7**：§13.2 CI 门禁 unit-test 改为"0 失败（通过率 100%）"<br>**Major 1**：§3.3 测试数据扩充（图数据 ≥10 万节点/50 万边、历史欺诈 ≥1 万条、压测数据按 TPS×时长）<br>**Major 2**：新增 §11.2 PIPL 合规测试（6 项详细用例）<br>**Major 3**：§3.3 脱敏方法明确（FPE / SHA-256+盐 / 掩码 + 不可逆性验证）<br>**Major 4**：审计日志时间戳精度升级毫秒级，P1→P0（法律取证需要）<br>**Major 5**：§13.1 新增 E2E 冒烟（PR 阶段关键路径必跑）<br>**Major 6**：§10.1 渗透测试频率改为"上线前 1 次 + 每年复测"<br>**Minor**：§11 含等保 2.0 三级 + PIPL；§15.4 时间戳精度毫秒级 |
| V1.2 | 2026-07-28 | 依据文档-代码一致性审计修订：测试用例数加注当前实际状态（5个测试文件） |
