# FRD-D04 数据库设计文档

| 项 | 值 |
|---|---|
| 文档编号 | FRD-D04-V1.1 |
| 文档版本 | V1.1 |
| 编制日期 | 2026-07-27 |
| 文档状态 | 修订版 |
| 关系数据库 | PostgreSQL 15 + TimescaleDB |
| 图数据库 | Neo4j 5 Enterprise |

---

## 1. 设计原则与命名规范

### 1.1 设计原则

- 多租户行级隔离：所有业务表含 `tenant_id`，强制启用 PostgreSQL RLS（详见 §9）
- 软删除 + 物理删除：审计期内软删除，到期物理删除
- Tokenization 优先：卡号一律 Token，不存明文 PAN
- 时序分区：交易/评分/审计按月分区
- JSONB 优先：可变结构（SHAP/规则/模型元数据）
- 审计串行写入：audit_logs 使用独立连接池 + 串行写入（不允许并行写），保证审计日志顺序性
- PIPL 合规：同意管理、删除请求、公平性评估独立建表

### 1.2 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 表名 | 蛇形小写复数 | `transactions`、`cases` |
| 字段名 | 蛇形小写 | `tenant_id`、`risk_score` |
| 主键 | `id`（UUID v7） | `01923a5b-...` |
| 外键 | `{引用表单数}_id` | `transaction_id`、`tenant_id` |
| 索引 | `idx_{完整表名}_{字段缩写}` | `idx_transactions_tenant_id` |
| 唯一索引 | `uk_{完整表名}_{字段}` | `uk_merchants_api_key` |
| 全文检索索引 | `ft_{完整表名}_{字段}` | `ft_cases_description` |
| 枚举值 | 大写下划线 | `ALLOW`、`REVIEW`、`DENY`、`CHALLENGE` |

### 1.3 字符集与时区

- 字符集：UTF-8
- 排序规则：`zh_CN.UTF-8`
- 时区：UTC 存储，按用户时区展示
- 时间类型：`TIMESTAMPTZ`

---

## 2. ER 模型

### 2.1 概念模型（PostgreSQL）

```
              ┌────────┐
              │ tenants│
              └───┬────┘
                  │ 1
                  │
       ┌──────────┼──────────┐
       ▼          ▼          ▼
  ┌────────┐ ┌────────┐ ┌──────────┐
  │ users  │ │merchants│ │transactions│
  └────────┘ └────┬───┘ └─────┬────┘
                    │ 1        │ N
                    │          │
                    ▼ N        ▼
              ┌──────────┐ ┌──────────┐
              │ api_keys │ │ scores   │
              └──────────┘ └────┬─────┘
                                  │ 1
                                  │
                                  ▼ N
                            ┌──────────┐
                            │  cases   │
                            └────┬─────┘
                                 │ 1
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
          ┌──────────┐    ┌──────────┐    ┌──────────┐
          │case_events│   │shap_expls│   │ appeals  │
          └──────────┘    └──────────┘    └──────────┘

横切表:
  audit_logs / model_versions / rules / rule_versions
  aml_reports / fairness_reports / consent_records / deletion_requests
```

### 2.2 图数据模型（Neo4j）

```
节点标签:
  (:Account {id, tenant_id, type, created_at})
  (:Merchant {id, tenant_id, name, industry})
  (:Device {fingerprint_hash, tenant_id, first_seen})
  (:IP {address, tenant_id, geo})
  (:Card {token, tenant_id, bin, last4})

关系类型:
  (:Account)-[:USES {first_seen, last_seen}]->(:Device)
  (:Account)-[:PAYS_TO {count, total_amount}]->(:Merchant)
  (:Account)-[:FROM_IP {count}]->(:IP)
  (:Card)-[:BINDS_TO {since}]->(:Account)
  (:Device)-[:SHARES_WITH {count}]->(:Account)

索引:
  :Account(id)          UNIQUE
  :Merchant(id)         UNIQUE
  :Device(fingerprint_hash, tenant_id) UNIQUE
  :IP(address, tenant_id)
  :Card(token)          UNIQUE
```

---

## 3. 表结构详细设计

### 3.1 租户与商户

#### tenants（租户表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| name | VARCHAR(100) | 否 | - | 租户名称 |
| code | VARCHAR(50) | 否 | - | 租户编码（唯一） |
| type | VARCHAR(20) | 否 | 'BANK' | 类型：BANK/PAYMENT/MERCHANT |
| plan | VARCHAR(20) | 否 | 'STANDARD' | 套餐：STANDARD/PRO/ENTERPRISE |
| status | VARCHAR(20) | 否 | 'ACTIVE' | 状态：ACTIVE/INACTIVE |
| encryption_key_id | UUID | 否 | - | Fernet 密钥 ID |
| settings | JSONB | 是 | '{}' | 配置（阈值/通知） |
| pci_scope | VARCHAR(20) | 否 | 'CDE' | PCI 范围：CDE/NON_CDE |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| updated_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_tenants_code`、`idx_tenants_status`

#### merchants（商户表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| merchant_no | VARCHAR(50) | 否 | - | 商户号 |
| name | VARCHAR(200) | 否 | - | 商户名称 |
| industry | VARCHAR(50) | 是 | - | 行业（MCC） |
| size | VARCHAR(20) | 是 | - | 规模 |
| contact_name | VARCHAR(100) | 是 | - | 联系人 |
| contact_phone_encrypted | TEXT | 是 | - | 联系电话（加密） |
| webhook_url | TEXT | 是 | - | Webhook 地址 |
| webhook_secret | TEXT | 是 | - | Webhook 签名密钥 |
| ip_whitelist | JSONB | 是 | '[]' | IP 白名单 |
| rate_limit_qps | INT | 否 | 100 | QPS 限制 |
| status | VARCHAR(20) | 否 | 'ACTIVE' | 状态：ACTIVE/INACTIVE |
| risk_profile | JSONB | 是 | '{}' | 风险画像 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| updated_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_merchants_tenant_merchant_no`、`idx_merchants_status`

#### api_keys（API Key 表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| merchant_id | UUID | 是 | - | 商户 ID（null 表示租户级） |
| key_hash | VARCHAR(64) | 否 | - | API Key SHA256 |
| key_prefix | VARCHAR(10) | 否 | - | Key 前缀（用于识别） |
| name | VARCHAR(50) | 否 | - | Key 名称 |
| scopes | JSONB | 否 | '[]' | 权限范围 |
| ip_whitelist | JSONB | 是 | '[]' | IP 白名单 |
| last_used_at | TIMESTAMPTZ | 是 | - | 最后使用 |
| expires_at | TIMESTAMPTZ | 是 | - | 过期时间 |
| status | VARCHAR(20) | 否 | 'ACTIVE' | 状态：ACTIVE/REVOKED |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| revoked_at | TIMESTAMPTZ | 是 | - | 撤销时间 |

索引：`uk_api_keys_key_hash`、`idx_api_keys_merchant_id`

### 3.2 交易与评分

#### transactions（交易表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键（即交易 ID） |
| tenant_id | UUID | 否 | - | 租户 ID |
| merchant_id | UUID | 是 | - | 商户 ID |
| external_tx_id | VARCHAR(100) | 否 | - | 外部交易号 |
| card_token | VARCHAR(64) | 否 | - | 卡 Token（非明文 PAN） |
| card_bin | VARCHAR(6) | 否 | - | 卡 BIN |
| card_last4 | VARCHAR(4) | 否 | - | 卡后 4 位 |
| amount | BIGINT | 否 | - | 金额（分） |
| currency | VARCHAR(3) | 否 | 'CNY' | 币种 |
| tx_type | VARCHAR(20) | 是 | - | 交易类型：PURCHASE/WITHDRAW/REFUND/TRANSFER/TOPUP/PAYMENT |
| channel | VARCHAR(20) | 是 | - | 渠道：WEB/APP/POS/ATM/API |
| is_3ds_verified | BOOLEAN | 否 | false | 是否 3DS 验证 |
| merchant_city | VARCHAR(50) | 是 | - | 商户城市 |
| merchant_category | VARCHAR(10) | 是 | - | MCC |
| device_fingerprint | VARCHAR(64) | 是 | - | 设备指纹 hash |
| ip_address | INET | 是 | - | IP 地址 |
| user_account_id | VARCHAR(100) | 是 | - | 用户账号（脱敏） |
| note_text | TEXT | 是 | - | 交易备注（脱敏） |
| risk_features | JSONB | 是 | '{}' | 预计算风险特征（避免重复计算） |
| is_recurring | BOOLEAN | 否 | false | 是否循环交易 |
| parent_tx_id | UUID | 是 | - | 关联原交易 ID（退款/撤销场景） |
| occurred_at | TIMESTAMPTZ | 否 | - | 交易发生时间 |
| received_at | TIMESTAMPTZ | 否 | now() | 系统接收时间 |
| metadata | JSONB | 是 | '{}' | 扩展字段 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：
- `uk_transactions_tenant_external_tx`（tenant_id, external_tx_id）
- `idx_transactions_card_token_occurred_at`
- `idx_transactions_merchant_occurred_at`
- `idx_transactions_occurred_at`
- `idx_transactions_parent_tx_id`（关联原交易查询）

分区策略：按 `occurred_at` 月度分区（保留 7 年）

TimescaleDB hypertable：`create_hypertable('transactions', 'occurred_at', chunk_time_interval => interval '1 day')`

#### scores（评分记录表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| transaction_id | UUID | 否 | - | 交易 ID |
| model_version | VARCHAR(50) | 否 | - | 模型版本 |
| rule_version | VARCHAR(50) | 否 | - | 规则版本 |
| risk_score | INT | 否 | - | 风险分 0-100 |
| decision | VARCHAR(20) | 否 | - | 决策：ALLOW/REVIEW/DENY/CHALLENGE |
| rule_hits | JSONB | 否 | '[]' | 命中规则列表 |
| modality_scores | JSONB | 否 | '{}' | 各模态分数 |
| feature_values | JSONB | 否 | '{}' | 输入特征 |
| cached | BOOLEAN | 否 | false | 是否缓存命中 |
| scored_at | TIMESTAMPTZ | 否 | now() | 评分时间 |
| latency_ms | INT | 否 | - | 评分耗时 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_scores_tenant_transaction_id`、`idx_scores_model_version`、`idx_scores_decision_scored_at`

分区：按 `scored_at` 月度分区（保留 7 年）

#### shap_explanations（SHAP 解释表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| score_id | UUID | 否 | - | 评分 ID |
| tenant_id | UUID | 否 | - | 租户 ID |
| factors | JSONB | 否 | - | Top5 因子列表 |
| base_value | DECIMAL(10,6) | 否 | - | 基线值 |
| output_value | DECIMAL(10,6) | 否 | - | 输出值 |
| model_version | VARCHAR(50) | 否 | - | 模型版本 |
| computed_at | TIMESTAMPTZ | 否 | now() | 计算时间 |
| expires_at | TIMESTAMPTZ | 否 | - | 缓存过期时间 |

索引：`uk_shap_explanations_score_id`、`idx_shap_explanations_expires_at`

### 3.3 案件与申诉

#### cases（案件表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| transaction_id | UUID | 是 | - | 关联交易 ID |
| score_id | UUID | 是 | - | 关联评分 ID |
| case_no | VARCHAR(50) | 否 | - | 案件编号 |
| type | VARCHAR(30) | 否 | - | 类型：FRAUD/AML/CHARGEBACK |
| level | VARCHAR(10) | 否 | - | 等级：P0/P1/P2 |
| status | VARCHAR(20) | 否 | 'OPEN' | 状态：OPEN/IN_REVIEW/CONFIRMED/CLOSED/FALSE_ALARM |
| assigned_to | UUID | 是 | - | 分配分析师 ID |
| escalated_to | UUID | 是 | - | 升级到 ID |
| amount | BIGINT | 否 | 0 | 涉案金额 |
| description | TEXT | 是 | - | 描述 |
| chargeback_id | VARCHAR(100) | 是 | - | 拒付 ID |
| graph_summary | JSONB | 是 | '{}' | 图关联摘要 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| confirmed_at | TIMESTAMPTZ | 是 | - | 确认时间 |
| closed_at | TIMESTAMPTZ | 是 | - | 关闭时间 |

索引：`idx_cases_tenant_status`、`idx_cases_assigned_to`、`idx_cases_level_created_at`、`idx_cases_chargeback_id`

分区：按 `created_at` 月度分区（保留 10 年）

#### case_events（案件事件表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| case_id | UUID | 否 | - | 案件 ID |
| tenant_id | UUID | 否 | - | 租户 ID |
| action | VARCHAR(30) | 否 | - | 动作 |
| from_status | VARCHAR(20) | 是 | - | 原状态 |
| to_status | VARCHAR(20) | 是 | - | 新状态 |
| operator_id | UUID | 否 | - | 操作人 ID |
| comment | TEXT | 是 | - | 备注 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_case_events_case_id`、`idx_case_events_tenant_created_at`

#### appeals（申诉表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| case_id | UUID | 否 | - | 关联案件 ID |
| appellant_type | VARCHAR(20) | 否 | - | 申诉人类型：MERCHANT/CARDHOLDER |
| appellant_id | VARCHAR(100) | 否 | - | 申诉人 ID |
| reason | VARCHAR(30) | 否 | - | 申诉理由 |
| description | TEXT | 是 | - | 详细描述 |
| llm_analysis | JSONB | 是 | - | LLM 文本分析结果 |
| status | VARCHAR(20) | 否 | 'PENDING' | 状态：PENDING/APPROVED/REJECTED |
| reviewer_id | UUID | 是 | - | 审核人 |
| reviewed_at | TIMESTAMPTZ | 是 | - | 审核时间 |
| review_comment | TEXT | 是 | - | 审核意见 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_appeals_tenant_status`、`idx_appeals_case_id`

### 3.4 规则引擎

#### rules（规则表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 是 | - | 租户 ID（null 表示全局） |
| rule_id | VARCHAR(50) | 否 | - | 规则 ID（如 R001） |
| name | VARCHAR(100) | 否 | - | 规则名称 |
| description | TEXT | 是 | - | 描述 |
| category | VARCHAR(30) | 否 | - | 类别：AMOUNT/GEO/DEVICE/VELOCITY/AML |
| expression | TEXT | 否 | - | DSL 表达式 |
| action | VARCHAR(20) | 否 | - | 动作：BLOCK/REVIEW |
| priority | INT | 否 | 50 | 优先级（0-100） |
| enabled | BOOLEAN | 否 | true | 启用 |
| current_version | VARCHAR(20) | 否 | 'v1' | 当前版本 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| updated_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_rules_tenant_rule_id`、`idx_rules_category_enabled`

#### rule_versions（规则版本表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID（Major 修订：强制非空，支持 RLS） |
| rule_id | UUID | 否 | - | 规则 ID |
| version | VARCHAR(20) | 否 | - | 版本号 |
| expression | TEXT | 否 | - | DSL 表达式 |
| status | VARCHAR(20) | 否 | 'DRAFT' | 状态：DRAFT/CANARY/ACTIVE/RETIRED |
| canary_percent | INT | 否 | 0 | 灰度比例 |
| created_by | UUID | 否 | - | 创建人 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| promoted_at | TIMESTAMPTZ | 是 | - | 全量上线时间 |

索引：`uk_rule_versions_rule_version`、`idx_rule_versions_status`

### 3.5 模型治理

#### model_versions（模型版本表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 是 | - | 租户 ID（null 表示全局模型） |
| model_type | VARCHAR(30) | 否 | - | 类型：STRUCTURED/TEXT/BEHAVIOR/FUSION/GNN |
| version | VARCHAR(50) | 否 | - | 版本号 |
| status | VARCHAR(20) | 否 | 'REGISTERED' | 状态：REGISTERED/CANARY/ACTIVE/RETIRED |
| metrics | JSONB | 否 | '{}' | AUC/F1/Recall/FPR |
| training_data_hash | VARCHAR(64) | 否 | - | 训练数据 SHA256 |
| feature_names | JSONB | 否 | '[]' | 特征列表 |
| artifacts_path | TEXT | 否 | - | 模型文件路径 |
| sha256 | VARCHAR(64) | 否 | - | 模型文件哈希 |
| canary_percent | INT | 否 | 0 | 灰度比例 |
| canary_started_at | TIMESTAMPTZ | 是 | - | 金丝雀开始时间 |
| observation_hours | INT | 否 | 168 | 观察期（小时）|
| promoted_at | TIMESTAMPTZ | 是 | - | 全量上线时间 |
| retired_at | TIMESTAMPTZ | 是 | - | 退役时间 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_model_versions_tenant_type_version`、`idx_model_versions_status`

#### drift_alerts（漂移告警表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| model_version | VARCHAR(50) | 否 | - | 模型版本 |
| modality | VARCHAR(20) | 否 | - | 模态 |
| metric_type | VARCHAR(10) | 否 | - | 指标：PSI/KL |
| metric_value | DECIMAL(10,4) | 否 | - | 数值 |
| threshold | DECIMAL(10,4) | 否 | - | 阈值 |
| severity | VARCHAR(20) | 否 | - | 严重度：LOW/MEDIUM/HIGH/CRITICAL |
| detected_at | TIMESTAMPTZ | 否 | now() | 检测时间 |
| resolved_at | TIMESTAMPTZ | 是 | - | 处理时间 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_drift_alerts_tenant_model`、`idx_drift_alerts_severity_detected_at`

### 3.6 反洗钱

#### aml_reports（反洗钱报告表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| report_type | VARCHAR(20) | 否 | - | 类型：LARGE/SUSPICIOUS |
| report_no | VARCHAR(50) | 否 | - | 报告编号 |
| transaction_id | UUID | 是 | - | 关联交易 ID |
| case_id | UUID | 是 | - | 关联案件 ID |
| amount | BIGINT | 否 | - | 金额 |
| content_xml | TEXT | 否 | - | XML 报告内容 |
| status | VARCHAR(20) | 否 | 'PENDING' | 状态：PENDING/REVIEWED/SUBMITTED |
| reviewer_id | UUID | 是 | - | 复核人 |
| submitted_at | TIMESTAMPTZ | 是 | - | 报送时间 |
| submitted_to | VARCHAR(50) | 是 | - | 报送目标 |
| submission_receipt | TEXT | 是 | - | 报送凭证 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_aml_reports_tenant_status`、`idx_aml_reports_type_created_at`

#### sanction_screenings（制裁名单筛查表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| entity_type | VARCHAR(20) | 否 | - | 实体类型：PERSON/ENTITY |
| entity_name | VARCHAR(200) | 否 | - | 实体名称 |
| entity_id_hash | VARCHAR(64) | 否 | - | 实体 ID hash |
| list_source | VARCHAR(50) | 否 | - | 名单来源：UN/OFAC/PEP |
| match_score | DECIMAL(5,2) | 否 | - | 匹配分（0-100） |
| matched_name | VARCHAR(200) | 是 | - | 匹配到的名单名称 |
| status | VARCHAR(20) | 否 | 'PENDING' | 状态：PENDING/CLEARED/BLOCKED |
| screened_at | TIMESTAMPTZ | 否 | now() | - |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_sanction_screenings_tenant_status`、`idx_sanction_screenings_match_score`

### 3.7 审计

#### audit_logs（审计日志表）

> **串行写入约束**：本表使用独立连接池 + 串行写入（不允许并行写），保证审计日志的全局顺序性。`sequence_no` 基于 `tenant_id` 维度递增，用于跨节点顺序校验与哈希链完整性校验。

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| sequence_no | BIGINT | 否 | - | 租户内递增序列号（保证顺序性） |
| user_id | UUID | 是 | - | 操作人 ID |
| ip | INET | 是 | - | IP |
| user_agent | TEXT | 是 | - | UA |
| action | VARCHAR(50) | 否 | - | 动作 |
| resource_type | VARCHAR(30) | 否 | - | 资源类型 |
| resource_id | UUID | 是 | - | 资源 ID |
| before_value | JSONB | 是 | - | 变更前 |
| after_value | JSONB | 是 | - | 变更后 |
| prev_hash | VARCHAR(64) | 否 | - | 上一条哈希 |
| current_hash | VARCHAR(64) | 否 | - | 当前哈希 |
| cde_zone | BOOLEAN | 否 | false | 是否 CDE 区 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_audit_logs_tenant_created_at`、`idx_audit_logs_user_id`、`idx_audit_logs_resource`、`uk_audit_logs_tenant_sequence`（tenant_id, sequence_no）

分区：按 `created_at` 月度分区（保留 7 年）

**串行写入实现**：
- 独立连接池：与业务连接池隔离，避免业务流量抢占审计写入资源
- 串行化：使用 `pg_advisory_xact_lock(tenant_id::bigint)` 或应用层队列确保单租户内顺序写入
- sequence_no 生成：`next_val` 由应用层基于 Redis INCR（key: `audit_seq:{tenant_id}`）预分配，确保全局唯一递增
- 哈希链：`current_hash = sha256(prev_hash || canonical_json(payload))`，跨节点校验时按 `sequence_no` 排序重放

### 3.8 同意管理（新增 - PIPL 合规）

#### consent_records（同意记录表）

> 用于满足 PIPL 第 14-16 条告知同意要求，记录数据主体的同意授予与撤回。

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| user_id | VARCHAR(100) | 否 | - | 数据主体 ID（脱敏） |
| consent_type | VARCHAR(30) | 否 | - | 同意类型：DATA_PROCESSING/MARKETING/THIRD_PARTY_SHARE |
| consent_status | VARCHAR(20) | 否 | - | 状态：GRANTED/WITHDRAWN |
| granted_at | TIMESTAMPTZ | 是 | - | 授予时间 |
| withdrawn_at | TIMESTAMPTZ | 是 | - | 撤回时间 |
| purpose | VARCHAR(100) | 否 | - | 用途（TRANSACTION_SCORING/FRAUD_DETECTION/AML_REPORT/MARKETING/RESEARCH） |
| legal_basis | VARCHAR(100) | 否 | - | 法律依据（CONSENT/CONTRACT/LEGAL_OBLIGATION） |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_consent_records_tenant_user_type`（tenant_id, user_id, consent_type）、`idx_consent_records_user_id`、`idx_consent_records_consent_status`

### 3.9 数据主体权利（新增 - PIPL 合规）

#### deletion_requests（删除请求表）

> 用于满足 PIPL 第 47 条数据删除权与第 45 条数据更正权、第 46 条数据可携带权。

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| user_id | VARCHAR(100) | 否 | - | 数据主体 ID（脱敏） |
| request_type | VARCHAR(30) | 否 | - | 请求类型：ACCOUNT_DELETION/DATA_PORTABILITY/RECTIFICATION |
| status | VARCHAR(20) | 否 | 'PENDING' | 状态：PENDING/PROCESSING/COMPLETED/REJECTED |
| requested_at | TIMESTAMPTZ | 否 | now() | 申请时间 |
| completed_at | TIMESTAMPTZ | 是 | - | 完成时间 |
| reason | TEXT | 是 | - | 申请原因 |
| operator_id | UUID | 是 | - | 处理操作员 ID |
| verification_method | VARCHAR(30) | 否 | - | 身份验证方式（ID_CARD/PHONE_OTP/EMAIL_OTP/FACE） |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_deletion_requests_tenant_status`、`idx_deletion_requests_requested_at`、`idx_deletion_requests_user_id`

### 3.10 公平性评估（新增 - PIPL 第 24 条自动化决策公平性）

#### fairness_reports（公平性报告表）

> 用于自动化决策公平性评估，监控模型对受保护属性（年龄/性别/地域）的差异化影响，阈值 ≥ 0.8（80% rule）。

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| model_version | VARCHAR(50) | 否 | - | 模型版本 |
| report_period_start | TIMESTAMPTZ | 否 | - | 报告周期开始 |
| report_period_end | TIMESTAMPTZ | 否 | - | 报告周期结束 |
| protected_attribute | VARCHAR(20) | 否 | - | 受保护属性：AGE/GENDER/REGION |
| group_count | INT | 否 | - | 样本组数量 |
| selection_rate | DECIMAL(10,6) | 否 | - | 选择率 |
| disparate_impact_ratio | DECIMAL(10,6) | 否 | - | 差异影响比 |
| threshold | DECIMAL(5,4) | 否 | 0.8000 | 合规阈值（≥ 0.8，80% rule） |
| status | VARCHAR(20) | 否 | - | 状态：PASS/FAIL/REVIEW |
| computed_at | TIMESTAMPTZ | 否 | now() | 计算时间 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_fairness_reports_tenant_model`、`idx_fairness_reports_status`、`idx_fairness_reports_period`

CHECK 约束：`CHECK (threshold >= 0.8)`、`CHECK (disparate_impact_ratio >= 0)`

---

## 4. 数据字典

### 4.1 风险等级

| 等级 | 数值范围 | 决策 | 颜色 |
|---|---|---|---|
| LOW | 0-29 | ALLOW | 绿色 |
| MEDIUM | 30-59 | ALLOW | 蓝色 |
| MEDIUM_HIGH | 60-79 | REVIEW | 橙色 |
| HIGH | 80-100 | DENY | 红色 |

### 4.2 决策动作

| 动作 | 含义 | 后续 |
|---|---|---|
| ALLOW | 放行 | 记录评分 |
| REVIEW | 人工审核 | 生成 P1 案件 |
| DENY | 拦截 | 生成 P0 案件 + Webhook |
| CHALLENGE | 挑战（二次验证） | 触发 3DS/OTP 二次验证 |

### 4.3 案件状态

| 状态 | 含义 | 允许的下一状态 |
|---|---|---|
| OPEN | 新建 | IN_REVIEW, CLOSED, FALSE_ALARM |
| IN_REVIEW | 调查中 | CONFIRMED, CLOSED, FALSE_ALARM |
| CONFIRMED | 确认欺诈 | CLOSED |
| CLOSED | 已关闭 | - |
| FALSE_ALARM | 误报 | CLOSED |

### 4.4 模型状态

| 状态 | 含义 |
|---|---|
| REGISTERED | 已注册（未上线） |
| CANARY | 金丝雀灰度中 |
| ACTIVE | 全量上线 |
| RETIRED | 已退役 |

### 4.5 规则版本状态

| 状态 | 含义 |
|---|---|
| DRAFT | 草稿 |
| CANARY | 灰度中 |
| ACTIVE | 全量上线 |
| RETIRED | 已退役 |

### 4.6 申诉状态

| 状态 | 含义 |
|---|---|
| PENDING | 待审核 |
| APPROVED | 已通过 |
| REJECTED | 已驳回 |

### 4.7 同意状态

| 状态 | 含义 |
|---|---|
| GRANTED | 已授予 |
| WITHDRAWN | 已撤回 |

### 4.8 删除请求状态

| 状态 | 含义 |
|---|---|
| PENDING | 待处理 |
| PROCESSING | 处理中 |
| COMPLETED | 已完成 |
| REJECTED | 已拒绝 |

### 4.9 公平性报告状态

| 状态 | 含义 |
|---|---|
| PASS | 通过（disparate_impact_ratio ≥ threshold） |
| FAIL | 未通过（disparate_impact_ratio < threshold） |
| REVIEW | 需人工复核 |

---

## 5. 索引与分区策略

### 5.1 高频查询与索引

| 查询场景 | 表 | 索引 |
|---|---|---|
| 按外部交易号查询 | transactions | uk_transactions_tenant_external_tx |
| 按卡号查询历史 | transactions | idx_transactions_card_token_occurred_at |
| 商户交易分页 | transactions | idx_transactions_merchant_occurred_at |
| 退款关联查询 | transactions | idx_transactions_parent_tx_id |
| 评分历史 | scores | idx_scores_tenant_transaction_id |
| 案件列表分页 | cases | idx_cases_tenant_status + created_at |
| 案件分配 | cases | idx_cases_assigned_to |
| 审计日志查询 | audit_logs | idx_audit_logs_tenant_created_at + user_id |
| 同意记录查询 | consent_records | uk_consent_records_tenant_user_type |
| 删除请求跟踪 | deletion_requests | idx_deletion_requests_tenant_status |
| 公平性报告查询 | fairness_reports | idx_fairness_reports_tenant_model |

### 5.2 分区策略

| 表 | 分区方式 | 保留期 |
|---|---|---|
| transactions | 月度（occurred_at）| 7 年 |
| scores | 月度（scored_at）| 7 年 |
| cases | 月度（created_at）| 10 年 |
| case_events | 月度（created_at）| 10 年 |
| audit_logs | 月度（created_at）| 7 年 |
| aml_reports | 月度（created_at）| 10 年 |
| consent_records | 月度（created_at）| 7 年 |
| deletion_requests | 月度（created_at）| 7 年 |
| fairness_reports | 月度（created_at）| 7 年 |

### 5.3 时序数据优化

`transactions` 表使用 TimescaleDB hypertable：
- chunk_time_interval: 1 day
- 自动压缩 7 天前数据
- 自动归档 7 年前数据至 OSS

### 5.4 大表容量

- 单租户 1000 TPS × 86400s = 8640 万笔/天
- 单笔约 1KB → 86GB/天
- 7 年保留：约 220TB（需分库分表）
- V2 优化：按租户分库 + 冷数据归档

---

## 6. 数据迁移与版本管理

### 6.1 Alembic 迁移规范

- 命名：`{YYYYMMDD}_{HHMM}_{slug}.py`
- 在线 DDL：`CREATE INDEX CONCURRENTLY` + `ALTER TABLE ... NOT VALID` + `VALIDATE CONSTRAINT`
- CDE 区迁移需审计记录
- RLS 策略变更需在迁移脚本中显式声明

### 6.2 Neo4j 数据加载

- 批量导入：`LOAD CSV` + `cypher-shell`
- 增量更新：Kafka Consumer 实时写入
- 全量重建：每日 02:00 从 PostgreSQL 同步

---

## 7. 数据安全设计

### 7.1 PII / PCI 字段加密清单

| 表 | 字段 | 加密方式 |
|---|---|---|
| merchants | contact_phone_encrypted | Fernet |
| transactions | card_token | Tokenization（不存储 PAN） |
| api_keys | key_hash | SHA256（不可逆） |
| audit_logs | before_value/after_value | 脱敏后存储 |
| consent_records | user_id | 脱敏存储 |
| deletion_requests | user_id | 脱敏存储 |

### 7.2 脱敏规则

| 场景 | 字段 | 规则 |
|---|---|---|
| 列表展示 | 卡号 | **** **** **** 1234 |
| 列表展示 | IP | 192.168.*.* |
| 报表导出 | 卡号 | 仅 BIN + Last4 |
| LLM 调用 | 全部 PII | 移除 |
| 日志 | 全部 PII | 移除 |
| CDE 区外 | 卡号 | 不允许 |

### 7.3 备份与恢复

- 数据库：每日全量 + WAL 持续归档 + 跨可用区
- Neo4j：每日全量 + 增量
- Redis：每日 RDB + AOF
- 备份保留：90 天滚动 + 7 年归档（PCI-DSS）
- 加密备份：AES-256
- 恢复演练：每月 1 次

### 7.4 行级安全（RLS）

详见 §9 Row Level Security 策略。所有业务表强制启用 RLS，应用层每次连接设置 `app.tenant_id`。

---

## 8. 容量规划

### 8.1 数据量测算（单租户，1000 TPS）

| 表 | 日增量 | 月增量 | 年增量 | 7 年总量 |
|---|---|---|---|---|
| transactions | 8640 万 | 26 亿 | 315 亿 | 2205 亿 |
| scores | 8640 万 | 26 亿 | 315 亿 | 2205 亿 |
| cases | 8.6 万 | 260 万 | 3100 万 | 2.17 亿 |
| audit_logs | 100 万 | 3000 万 | 3.65 亿 | 25.5 亿 |
| consent_records | 1 万 | 30 万 | 365 万 | 2555 万 |
| deletion_requests | 1 千 | 3 万 | 36.5 万 | 255 万 |
| fairness_reports | 10 | 300 | 3650 | 2.5 万 |

### 8.2 存储估算

- 单租户 7 年：约 500 TB（含索引）
- 10 租户：5 PB
- V2 优化：冷数据归档至 OSS + 按租户分库

---

## 9. Row Level Security 策略

### 9.1 设计目标

强制多租户行级隔离，确保任一租户的数据不会被另一租户访问，即使应用层 SQL 拼接出现遗漏。RLS 是数据库层的最后一道防线，与应用层中间件鉴权共同构成纵深防御。

### 9.2 启用 RLS 的表清单

以下 18 张业务表强制启用 RLS：

| 序号 | 表名 | tenant_id 可空 | 说明 |
|---|---|---|---|
| 1 | merchants | 否 | 商户表 |
| 2 | api_keys | 否 | API Key 表 |
| 3 | transactions | 否 | 交易表 |
| 4 | scores | 否 | 评分记录表 |
| 5 | shap_explanations | 否 | SHAP 解释表 |
| 6 | cases | 否 | 案件表 |
| 7 | case_events | 否 | 案件事件表 |
| 8 | appeals | 否 | 申诉表 |
| 9 | rules | 是 | 规则表（null 表示全局规则） |
| 10 | rule_versions | 否 | 规则版本表（V1.1 新增 tenant_id） |
| 11 | model_versions | 是 | 模型版本表（null 表示全局模型） |
| 12 | drift_alerts | 否 | 漂移告警表 |
| 13 | aml_reports | 否 | 反洗钱报告表 |
| 14 | sanction_screenings | 否 | 制裁名单筛查表 |
| 15 | audit_logs | 否 | 审计日志表 |
| 16 | consent_records | 否 | 同意记录表（V1.1 新增） |
| 17 | deletion_requests | 否 | 删除请求表（V1.1 新增） |
| 18 | fairness_reports | 否 | 公平性报告表（V1.1 新增） |

> `tenants` 表本身不含 `tenant_id`（自身即租户），不启用 RLS。

### 9.3 RLS 策略定义

#### 9.3.1 标准策略（tenant_id NOT NULL 的表）

```sql
-- 启用 RLS
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;

-- 创建租户隔离策略
CREATE POLICY tenant_isolation ON {table}
  USING (tenant_id = current_setting('app.tenant_id')::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

#### 9.3.2 全局数据策略（tenant_id 可空的表：rules / model_versions）

```sql
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_or_global ON {table}
  USING (
    tenant_id = current_setting('app.tenant_id')::uuid
    OR tenant_id IS NULL
  )
  WITH CHECK (
    tenant_id = current_setting('app.tenant_id')::uuid
    OR tenant_id IS NULL
  );
```

### 9.4 应用层接入

- 应用层每次获取连接后，必须先执行：`SET app.tenant_id = '{tenant_uuid}';`
- 连接池配置：连接复用前校验 `app.tenant_id` 是否已重置，避免跨租户串号
- 事务结束后：`RESET app.tenant_id;`（连接归还连接池前）

### 9.5 DBA / 运维角色

- 创建专用的 `dba_bypass` 角色，授予 `BYPASSRLS` 属性：
  ```sql
  CREATE ROLE dba_bypass BYPASSRLS;
  ```
- 仅 DBA 与运维账号可加入 `dba_bypass` 角色，业务应用账号严禁继承此属性
- 所有 BYPASSRLS 操作必须记录至 audit_logs

### 9.6 迁移脚本模板

```sql
-- V1.1__enable_rls.sql
DO $$
DECLARE
  tbl TEXT;
  nullable_tables TEXT[] := ARRAY['rules', 'model_versions'];
  standard_tables TEXT[] := ARRAY[
    'merchants','api_keys','transactions','scores','shap_explanations',
    'cases','case_events','appeals','rule_versions','drift_alerts',
    'aml_reports','sanction_screenings','audit_logs',
    'consent_records','deletion_requests','fairness_reports'
  ];
BEGIN
  -- 标准表
  FOREACH tbl IN ARRAY standard_tables LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I;', tbl);
    EXECUTE format($f$
      CREATE POLICY tenant_isolation ON %I
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    $f$, tbl);
  END LOOP;

  -- tenant_id 可空表
  FOREACH tbl IN ARRAY nullable_tables LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
    EXECUTE format('DROP POLICY IF EXISTS tenant_or_global ON %I;', tbl);
    EXECUTE format($f$
      CREATE POLICY tenant_or_global ON %I
        USING (tenant_id = current_setting('app.tenant_id')::uuid OR tenant_id IS NULL)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid OR tenant_id IS NULL);
    $f$, tbl);
  END LOOP;
END $$;
```

---

## 10. 变更记录

| 版本 | 日期 | 变更人 | 变更内容 | 审核人 |
|---|---|---|---|---|
| V1.0 | 2026-07-27 | 邝振华 | 初稿创建 | - |
| V1.1 | 2026-07-27 | 邝振华 + AI 协作 | 依据 FRD-BASELINE-V1.1 修订：1) 枚举值统一大写下划线（decision: ALLOW/REVIEW/DENY/CHALLENGE；case_status: OPEN/IN_REVIEW/CONFIRMED/CLOSED/FALSE_ALARM；rule_action: BLOCK/REVIEW；model_status: REGISTERED/CANARY/ACTIVE/RETIRED；appeal_status: PENDING/APPROVED/REJECTED/WITHDRAWN；aml_status: PENDING/SUBMITTED/ACCEPTED/REJECTED；tenant.type: BANK/PAYMENT/MERCHANT；tenant.plan: STANDARD/PRO/ENTERPRISE；case.type: FRAUD/AML/CHARGEBACK）；2) 索引统一为 `idx_{完整表名}_{字段}` 命名（28 处重命名）；3) 新增 consent_records / deletion_requests / fairness_reports 三张 PIPL 合规表；4) transactions 补充 channel / risk_features / is_recurring / parent_tx_id 字段；5) 新增 §9 Row Level Security 策略章节（18 张表启用 RLS）；6) audit_logs 新增 sequence_no 字段 + 独立连接池串行写入；7) rule_versions 强制增加 tenant_id（Major 修订） | - |
