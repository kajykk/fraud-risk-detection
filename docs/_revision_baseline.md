# FRD 跨文档修订基准（V1.1）

| 项 | 值 |
|---|---|
| 文档编号 | FRD-BASELINE-V1.1 |
| 编制日期 | 2026-07-27 |
| 文档状态 | 修订基准（所有 D01-D11 修订必须以此为准） |
| 用途 | 解决 11 份文档间的根因性矛盾，建立单一事实源 |

> 本文件不替代任何正式文档，仅作为 D01-D11 修订期间的统一基准。所有 subagent 修订文档时必须严格遵循本基准，不得自行假设。

---

## 1. 项目定位：1 真人 + 11 AI Agent 团队模式

### 1.1 团队配置

| 角色 | 承担者 | 投入 | 职责 |
|------|--------|------|------|
| 项目负责人 / 全栈工程师 / 终审决策 | **邝振华（真人）** | 100% | 架构终审、关键决策、代码 review、对外沟通、QSA/法律/业务顾问对接 |
| 项目经理（PM Agent） | AI Agent | 100% | WBS 跟踪、EVM 挣值、风险登记、进度报告 |
| 需求分析师（REQ Agent） | AI Agent | 100% | 需求调研、SRS 维护、RTM 矩阵、用例补充 |
| 架构师（ARCH Agent） | AI Agent | 100% | C4 模型、ADR、技术选型、架构评审 |
| 后端开发 1（BE-1 Agent） | AI Agent | 100% | API 网关、评分引擎、规则引擎 |
| 后端开发 2（BE-2 Agent） | AI Agent | 100% | 案件管理、报表中心、模型治理、Webhook |
| 前端开发（FE Agent） | AI Agent | 100% | 5 端 UI、实时监控、图谱可视化、PWA |
| ML 工程师（ML Agent） | AI Agent | 100% | XGBoost、BERT、多模态融合、漂移检测 |
| GNN 工程师（GNN Agent） | AI Agent | 100% | PyG、Neo4j、GraphSAGE、团伙检测 |
| DevOps（DevOps Agent） | AI Agent | 100% | Docker、K8s、CI/CD、可观测性、运维 |
| 测试工程师（QA Agent） | AI Agent | 100% | 单元/集成/契约/E2E/性能/安全/UAT |
| 安全合规（SEC Agent） | AI Agent | 100% | PCI-DSS、PIPL、反洗钱、等保 2.0 三级 |
| QSA 顾问（外聘真人） | 待定 | 10% | PCI-DSS 评估 + 整改指导 |
| 法律顾问（外聘真人） | 待定 | 5% | 反洗钱合规审阅 |
| 金融业务顾问（外聘真人） | 待定 | 5% | 反欺诈业务咨询 |

### 1.2 协作工具

- **AI 协作工具**：Trae（主）+ Cursor + Claude Code（备）
- **LLM API**：通义千问 / 文心一言 / DeepSeek（国内合规，避免 OpenAI 数据出境风险）
- **代码托管**：GitHub（私有仓库）
- **项目管理**：GitHub Projects + 本地 Markdown

### 1.3 人力成本

- **真人人力成本**：0 元（个人项目）
- **AI Agent 成本**：已纳入 AI 工具订阅 + LLM API 调用预算
- **外聘顾问**：QSA + 法律 + 金融业务（按 D01 §6.1 估算）

### 1.4 关键原则

- 11 AI Agent 是"分工角色"，不是"11 个真人"
- 邝振华是唯一的真人决策者，对所有 AI Agent 产出负终审责任
- AI Agent 产出必须经邝振华 review 后才能合入主线
- 关键决策（架构、合规、商业）由邝振华拍板，AI Agent 提供建议

---

## 2. 统一关键参数（跨文档单一事实源）

### 2.1 性能与质量目标

| 参数 | 目标值 | 适用文档 |
|------|--------|----------|
| 评分接口 P99 | < 200ms | D01/D03/D07/D11 |
| 评分接口 P999 | < 500ms（软目标） | D03 |
| 单实例 TPS | ≥ 1000 | D01/D03 |
| 集群 TPS | ≥ 2000（MVP）/ ≥ 10000（生产扩容后） | D03/D07/D11 |
| 系统可用性 SLA | 99.5%（MVP）/ 99.9%（生产稳态） | D08/D10/D11 |
| RTO | ≤ 30min（应用层 5min + 数据库 30min） | D10/D11 |
| RPO | ≤ 1min | D10/D11 |
| 单元测试通过率 | ≥ 99% | D07/D11 |
| 行覆盖率（总体） | ≥ 85% | D07/D11 |
| 行覆盖率（评分/规则引擎核心） | ≥ 90% | D07 |
| 行覆盖率（ML/GNN） | ≥ 75% | D07 |
| 契约测试通过率 | 100%（或 ≥95% 且剩余有书面豁免） | D07/D11 |
| 集成测试通过率 | ≥ 95% | D07/D11 |
| E2E 测试通过率 | ≥ 95% | D07/D11 |
| 安全高危漏洞 | 0 | D07/D11 |
| 模型 AUC | ≥ 0.92 | D01/D02/D11 |
| 模型 Recall@1%FPR | ≥ 0.85 | D01/D11 |
| 误报率 | ≤ 5%（生产）/ ≤ 10%（试运行过渡期） | D01/D11 |
| 模型 PSI 7d | < 0.25 | D01/D03 |

### 2.2 缺陷遗留标准（统一）

| 缺陷等级 | 验收允许遗留数 | 备注 |
|----------|----------------|------|
| P0 阻断 | 0 | 0 容忍 |
| P1 严重 | ≤ 2 | 必须有缓解措施与修复计划 |
| P2 一般 | ≤ 10 | 必须有修复计划 |
| P3 轻微 | ≤ 30 | 可后续修复 |

### 2.3 合规要求

- **PCI-DSS v4.0**：QSA 季度评估，RoC 报告编号 + 日期作为验收证据
- **PIPL**：告知同意、最小必要、数据导出（GET /api/v1/pipl/data-export）、数据删除（POST /api/v1/pipl/deletion）、同意管理（/api/v1/pipl/consent）、自动化决策解释权、数据本地化
- **反洗钱法**：KYC、STR/CTR 上报、7 年审计日志保留；上报通道由客户/第三方提供接口，FRD 完成对接联调（**统一口径**）
- **GB/T 22239 等保 2.0 三级**：物理/网络/主机/应用/数据/管理 6 类控制点；测评机构备案证明编号作为验收证据；M1 即启动备案（周期 3-6 个月）

---

## 3. 统一枚举字典（D04 DB + D05 API 必须遵循）

### 3.1 决策枚举

```
decision: ALLOW | REVIEW | DENY | CHALLENGE
```

### 3.2 案件状态

```
case_status: OPEN | IN_REVIEW | CONFIRMED | CLOSED | FALSE_ALARM
```

### 3.3 模型状态

```
model_status: REGISTERED | CANARY | ACTIVE | RETIRED
```

### 3.4 规则状态

```
rule_status: DRAFT | CANARY | ACTIVE | RETIRED
rule_action: BLOCK | REVIEW
```

> **字段区分说明**：
> - `decision` 字段是评分最终决策（4 值：`ALLOW | REVIEW | DENY | CHALLENGE`），由评分引擎综合多规则 + ML 输出后产生。
> - `rule_action` 字段是单条规则触发时的动作（2 值：`BLOCK | REVIEW`），仅描述该规则自身意图。
> - 两者是不同字段，不冲突：`rule_action=BLOCK` 的规则会贡献到评分最终 `decision=DENY`；`rule_action=REVIEW` 的规则会贡献到 `decision=REVIEW` 或更高。

### 3.5 风险等级

```
risk_band: LOW | MEDIUM | HIGH | CRITICAL
risk_score: DECIMAL(5,4) 范围 0.0000-1.0000
```

阈值：LOW < 0.30 | MEDIUM 0.30-0.60 | HIGH 0.60-0.85 | CRITICAL ≥ 0.85

### 3.6 租户套餐

```
tenant.plan: STANDARD | PRO | ENTERPRISE
tenant.type: BANK | PAYMENT | MERCHANT
tenant_pci_scope: cde | non_cde
```

> 注：`tenant.plan` 枚举值中 `PRO` 对应原 `premium`（统一为大写并改名 PRO，避免与产品命名歧义）。

### 3.7 案件等级

```
case.level: P0 | P1 | P2 | P3
```

### 3.8 交易类型与渠道

```
tx_type: PURCHASE | WITHDRAW | REFUND | TRANSFER | TOPUP | PAYMENT
channel: WEB | APP | POS | API | QR
```

### 3.9 上报状态

```
aml_report_type: LARGE | SUSPICIOUS
aml_report_status: PENDING | SUBMITTED | ACCEPTED | REJECTED
```

> 注：API/文档中亦称 `aml_status`，与 DB 列 `aml_report_status` 同义，均取上述 4 值（与 D02/D06 实际值一致）。

### 3.10 申诉状态

```
appeal_status: PENDING | APPROVED | REJECTED | WITHDRAWN
```

> 注：4 值定义，与 D02/D06 申诉章节实际值一致。

### 3.11 同意状态

```
consent_status: GRANTED | WITHDRAWN | EXPIRED
consent_purpose: TRANSACTION_SCORING | FRAUD_DETECTION | AML_REPORT | MARKETING | RESEARCH
```

### 3.12 漂移告警

```
drift_severity: LOW | MEDIUM | HIGH | CRITICAL
drift_metric: PSI | KL | KS | WASSERSTEIN
```

---

## 4. 统一字段映射表（D04 DB + D05 API 必须对齐）

### 4.1 transactions 表（D04 必须包含以下字段）

| 字段 | 类型 | 来源 | 备注 |
|------|------|------|------|
| id | UUID v7 | 主键 | |
| tenant_id | UUID | 多租户隔离 | |
| merchant_id | UUID | 商户 | 可空 |
| external_tx_id | VARCHAR(100) | API | 外部交易号 |
| card_token | VARCHAR(64) | Tokenization | 非明文 PAN |
| card_bin | VARCHAR(6) | API | |
| card_last4 | VARCHAR(4) | API | |
| amount | BIGINT | API | 金额（分） |
| currency | VARCHAR(3) | API | 默认 CNY |
| tx_type | VARCHAR(20) | API | 见枚举 3.8 |
| channel | VARCHAR(20) | API | 见枚举 3.8 |
| is_3ds_verified | BOOLEAN | API | |
| merchant_city | VARCHAR(50) | API | |
| merchant_category | VARCHAR(10) | API | MCC |
| device_fingerprint | VARCHAR(64) | API | |
| ip_address | INET | API | |
| user_account_id | VARCHAR(100) | API | 脱敏 |
| user_created_at | TIMESTAMPTZ | API | 用户注册时间（特征） |
| acquirer_id | VARCHAR(50) | API | 收单机构 |
| shipping_country | VARCHAR(2) | API | 账单地址国别 |
| billing_country | VARCHAR(2) | API | 货运地址国别 |
| note_text | TEXT | API | 脱敏 |
| occurred_at | TIMESTAMPTZ | API | |
| received_at | TIMESTAMPTZ | 系统 | now() |
| metadata | JSONB | API | 扩展字段 |

### 4.2 risk_score 字段类型

```
scores.risk_score: DECIMAL(5,4) NOT NULL  -- 0.0000-1.0000
scores.risk_band: VARCHAR(10) NOT NULL    -- LOW/MEDIUM/HIGH/CRITICAL
scores.decision: VARCHAR(20) NOT NULL     -- ALLOW/REVIEW/DENY/CHALLENGE
```

### 4.3 多租户隔离字段

所有业务表必须包含 `tenant_id UUID NOT NULL`，并启用 PostgreSQL RLS：

```sql
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {table}
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

例外：`rule_versions` 也必须加 `tenant_id`（Major 修订项）。

---

## 5. 统一时间线（D01/D08/D09/D10/D11 必须遵循）

| 里程碑 | 日期 | 准出条件 |
|--------|------|----------|
| M1 项目启动 | 2026-08-15 | 章程、干系人登记册、启动会纪要；等保备案启动 |
| M2 需求基线 | 2026-09-05 | SRS 评审通过 + 客户签字；PIPL/等保映射完成 |
| M3 设计基线 | 2026-09-30 | SAD + DBD + API 评审通过；PCI-DSS 隔离区方案评审通过 |
| M4 Alpha | 2026-11-15 | 评分 + 规则 + 案件雏形可演示（案件雏形，非完整跑通）；ML/GNN Mock 可演示 |
| M5 Beta | 2026-12-31 | 覆盖 D02 80% 功能；1 家试点接入；等保 2.0 三级备案完成 |
| M6 RC | 2027-01-31 | P0/P1 缺陷关闭；性能/安全达标；ML 真模型接入 |
| M7 生产部署 | 2027-02-28 | K8s 部署完成；灰度 5%→25% 启动且 72h 无 P0 故障；PCI-DSS QSA 评估完成 |
| M8 试运行验收 | 2027-04-30 | 8 周试运行 SLA ≥ 99.5%；客户签署验收；运维移交 |

**注**：M7 准出条件已从"灰度通过"调整为"灰度启动且 72h 无 P0 故障"（与 WBS 4.6.3 灰度任务 02-26~03-02 对齐）。

---

## 6. 统一预算（D01/D08/D09 必须遵循）

### 6.1 首年成本（重算）

| 成本类别 | 金额（元） | 说明 |
|---|---|---|
| 真人人力成本 | 0 | 个人项目 |
| AI 工具订阅 | 12000 | Trae/Cursor/Claude Code 年费 |
| LLM API 调用 | 30000 | 通义千问/DeepSeek（申诉文本 + 代码生成） |
| 云资源（生产） | 120000 | 阿里云 ECS 6 实例 + RDS + Redis + Neo4j Community + OSS |
| 域名 + ICP | 500 | .com + 备案 |
| QSA 顾问 | 250000 | PCI-DSS 评估 + 整改（市价 15-30 万，取中位） |
| 等保 2.0 三级备案 | 100000 | 测评机构费用（市价 8-15 万） |
| 法律顾问 | 10000 | 反洗钱合规审阅 |
| Neo4j Enterprise（生产，第 2 年起） | 0 | MVP/生产首年用社区版；第 2 年评估升级 |
| **合计（首年）** | **522500** | |

### 6.2 ROI 测算（三档）

| 时间 | 悲观 | 中性 | 乐观 |
|------|------|------|------|
| 第 12 月 | 0 家付费 | 1 家付费（50 万） | 2 家付费（100 万） |
| 第 24 月 | 1 家付费（50 万） | 3 家付费（180 万） | 6 家付费（400 万） |
| 第 36 月 | 3 家付费（180 万） | 10 家付费（600 万） | 20 家付费（1400 万） |

**ROI（24 月中性）** = (1800000 - 800000) / 800000 = **125%**（远低于原 620%，但仍为正）

### 6.3 商业模式（保持 D01 §6.3 不变）

- 持牌金融机构：年费 50 万 + 0.05 元/笔
- 商户：年费 12 万/年
- 三方支付：0.10 元/笔
- 试点 PoC：免费 1 个月 + 数据回流

---

## 7. 统一合规口径

### 7.1 PIPL 数据主体权利接口（D05 必须实现，统一 /api/v1/pipl/* 命名空间）

- `POST /api/v1/pipl/consent` — 授予同意
- `POST /api/v1/pipl/consent/withdraw` — 撤回同意
- `GET /api/v1/pipl/consent/{user_id}` — 查询同意记录
- `GET /api/v1/pipl/data-export` — 申请数据导出（异步任务，返回 task_id）
- `GET /api/v1/pipl/data-export/{task_id}/status` — 查询导出状态
- `POST /api/v1/pipl/deletion` — 申请数据删除（被遗忘权）
- `GET /api/v1/pipl/deletion/{request_id}/status` — 查询删除状态
- `POST /api/v1/pipl/rectification` — 数据更正请求

### 7.2 等保 2.0 三级控制点映射（D07/D10 必须实现）

D10 新增"§9.X 等保 2.0 三级合规矩阵"章节，覆盖：
- 物理与环境安全（云等保合规）
- 安全通信网络（VPC + 安全组 + NetworkPolicy）
- 安全区域边界（WAF + IDS/IPS）
- 安全计算环境（堡垒机 + HIDS + 主机加固 + 可信验证）
- 安全管理中心（集中监控 + 审计）
- 剩余信息保护（内存清零 + 磁盘擦除）

D07 新增"§11.3 等保 2.0 三级测试用例"。

### 7.3 反洗钱上报通道（统一口径）

- **范围**：FRD 完成 AML 报告生成与接口对接联调
- **不在范围**：反洗钱上报通道本体（由客户/第三方提供）
- **验收**：D11 §8.3 改为"客户/第三方提供接口，FRD 完成对接联调 + 提供联调报告"

### 7.4 LLM 选型

- **MVP**：通义千问 / 文心一言 / DeepSeek（国内合规）
- **不使用**：OpenAI GPT-4（PIPL 数据出境风险）
- **私有部署备选**：Qwen2.5 / ChatGLM4 自部署（数据不出 CDE）

---

## 8. 统一部署架构（D10 必须遵循）

### 8.1 部署规模（降级，匹配个人项目 + AI 协作）

| 组件 | 部署形态 | 数量 | 备注 |
|------|----------|------|------|
| API 网关 + 评分 + 规则 + 案件 | K8s Deployment | 3 副本 × 1 AZ | 合并部署，降低运维复杂度 |
| ML 推理 | K8s Deployment | 2 副本 × 1 AZ | |
| GNN 服务 | K8s Deployment | 2 副本 × 1 AZ | |
| Celery Worker | K8s Deployment | 2 副本 × 1 AZ | |
| Celery Beat | K8s Deployment | 1 副本 + 1 standby | |
| PostgreSQL | StatefulSet | 1 主 + 1 从（同 AZ） + 异地备份 | |
| Redis | StatefulSet | 1 主 + 1 从（同 AZ） | |
| Neo4j | StatefulSet | 1 主（社区版） + 异地备份 | |
| Prometheus + Grafana + Loki + Jaeger | Deployment | 各 1 副本 | |

**SLA 目标**：99.5%（年宕机 ≤ 43.8h），试运行后视情况升级至 99.9%

### 8.2 灰度发布（统一为 24h + 24h）

- Stage 1：5% 流量，持续 24h，观察 P0 故障 + P99 < 200ms
- Stage 2：25% 流量，持续 24h，观察同上
- Stage 3：100% 流量，观察 72h

### 8.3 RTO（统一）

- 应用层回滚：≤ 5min（镜像回滚）
- 数据库回滚：≤ 30min（pg_dump + alembic downgrade）
- 总体 RTO：≤ 30min

### 8.4 云厂商（统一为阿里云）

- 区域：cn-hangzhou
- Terraform 模块：`aliyun/terraform-alicloud`
- CDN/WAF/DDoS：阿里云 DCDN + WAF + DDoS 高防（不用 Cloudflare）
- KMS：阿里云 KMS（per-tenant key）
- OSS：阿里云 OSS（备份 + 模型工件）

---

## 9. 修订执行约束

所有 subagent 修订文档时必须：

1. **严格遵循本基准**：枚举值、字段类型、参数、时间线、预算不得自行假设
2. **保留原文档结构与编号**：仅在原结构内修订内容，不重排章节
3. **标注修订标记**：在变更记录表新增 V1.1 行，注明"依据 FRD-BASELINE-V1.1 修订"
4. **不删除合规内容**：原文档中的合规要求、安全设计、审计要求不得弱化
5. **修订后版本号**：V1.0 → V1.1
6. **保留原文档优点**：审查报告中"优点"部分不得在修订中丢失

---

## 10. 变更记录

| 版本 | 日期 | 变更人 | 变更内容 |
|---|---|---|---|
| V1.0 | 2026-07-27 | 邝振华 + AI 协作 | 建立跨文档修订基准，统一项目定位、参数、枚举、字段、时间线、预算、合规口径、部署架构 |
| V1.1 | 2026-07-27 | 邝振华 + AI 协作 | 统一枚举字典大写化：§3.6 `tenant.type`→`BANK/PAYMENT/MERCHANT`、`tenant.plan`→`STANDARD/PRO/ENTERPRISE`（premium 改名 PRO）；§3.4 `rule_action` 改为 `BLOCK/REVIEW`（2 值，与 `decision` 4 值字段区分，新增字段区分说明）；明确 `case.level`（P0-P3）、`appeal_status`（4 值）、`aml_status`/`aml_report_status`（4 值）定义。本 V1.1 基准作为 D01-D11 后续修订依据。 |
