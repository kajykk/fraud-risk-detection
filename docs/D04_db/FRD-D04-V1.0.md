# FRD-D04 数据库设计文档

| 项 | 值 |
|---|---|
| 文档编号 | FRD-D04-V1.0 |
| 文档版本 | V1.0 |
| 编制日期 | 2026-07-27 |
| 文档状态 | 草稿 |
| 关系数据库 | PostgreSQL 15 + TimescaleDB |
| 图数据库 | Neo4j 5 Enterprise |

---

## 1. 设计原则与命名规范

### 1.1 设计原则

- 多租户行级隔离：所有业务表含 `tenant_id`
- 软删除 + 物理删除：审计期内软删除，到期物理删除
- Tokenization 优先：卡号一律 Token，不存明文 PAN
- 时序分区：交易/评分/审计按月分区
- JSONB 优先：可变结构（SHAP/规则/模型元数据）

### 1.2 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 表名 | 蛇形小写复数 | `transactions`、`cases` |
| 字段名 | 蛇形小写 | `tenant_id`、`risk_score` |
| 主键 | `id`（UUID v7） | `01923a5b-...` |
| 外键 | `{引用表单数}_id` | `transaction_id`、`tenant_id` |
| 索引 | `idx_{表}_{字段}` | `idx_transactions_tenant_id` |
| 唯一索引 | `uk_{表}_{字段}` | `uk_merchants_api_key` |
| 枚举值 | 大写下划线 | `STATUS_NEW`、`ACTION_BLOCK` |

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
  aml_reports / fairness_reports / consent_records
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
| type | VARCHAR(20) | 否 | 'bank' | 类型：bank/payment/merchant |
| plan | VARCHAR(20) | 否 | 'standard' | 套餐：standard/pro/enterprise |
| status | VARCHAR(20) | 否 | 'active' | 状态 |
| encryption_key_id | UUID | 否 | - | Fernet 密钥 ID |
| settings | JSONB | 是 | '{}' | 配置（阈值/通知） |
| pci_scope | VARCHAR(20) | 否 | 'cde' | PCI 范围：cde/non_cde |
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
| status | VARCHAR(20) | 否 | 'active' | 状态 |
| risk_profile | JSONB | 是 | '{}' | 风险画像 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| updated_at | TIMESTAMPTZ | 否 | now() | - |

索引：`uk_merchants_tenant_no`、`idx_merchants_status`

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
| status | VARCHAR(20) | 否 | 'active' | 状态 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| revoked_at | TIMESTAMPTZ | 是 | - | 撤销时间 |

索引：`uk_api_keys_hash`、`idx_api_keys_merchant`

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
| merchant_city | VARCHAR(50) | 是 | - | 商户城市 |
| merchant_category | VARCHAR(10) | 是 | - | MCC |
| device_fingerprint | VARCHAR(64) | 是 | - | 设备指纹 hash |
| ip_address | INET | 是 | - | IP 地址 |
| user_account_id | VARCHAR(100) | 是 | - | 用户账号（脱敏） |
| note_text | TEXT | 是 | - | 交易备注（脱敏） |
| occurred_at | TIMESTAMPTZ | 否 | - | 交易发生时间 |
| received_at | TIMESTAMPTZ | 否 | now() | 系统接收时间 |
| metadata | JSONB | 是 | '{}' | 扩展字段 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：
- `uk_transactions_tenant_external`（tenant_id, external_tx_id）
- `idx_transactions_card_token_time`
- `idx_transactions_merchant_time`
- `idx_transactions_occurred_time`

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
| decision | VARCHAR(20) | 否 | - | 决策：allow/review/block |
| rule_hits | JSONB | 否 | '[]' | 命中规则列表 |
| modality_scores | JSONB | 否 | '{}' | 各模态分数 |
| feature_values | JSONB | 否 | '{}' | 输入特征 |
| cached | BOOLEAN | 否 | false | 是否缓存命中 |
| scored_at | TIMESTAMPTZ | 否 | now() | 评分时间 |
| latency_ms | INT | 否 | - | 评分耗时 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_scores_tenant_tx`、`idx_scores_model_version`、`idx_scores_decision_time`

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

索引：`uk_shap_score`、`idx_shap_expires`

### 3.3 案件与申诉

#### cases（案件表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| transaction_id | UUID | 是 | - | 关联交易 ID |
| score_id | UUID | 是 | - | 关联评分 ID |
| case_no | VARCHAR(50) | 否 | - | 案件编号 |
| type | VARCHAR(30) | 否 | - | 类型：fraud/aml/chargeback |
| level | VARCHAR(10) | 否 | - | 等级 P0/P1/P2 |
| status | VARCHAR(20) | 否 | 'new' | 状态：new/investigating/confirmed/closed |
| assigned_to | UUID | 是 | - | 分配分析师 ID |
| escalated_to | UUID | 是 | - | 升级到 ID |
| amount | BIGINT | 否 | 0 | 涉案金额 |
| description | TEXT | 是 | - | 描述 |
| chargeback_id | VARCHAR(100) | 是 | - | 拒付 ID |
| graph_summary | JSONB | 是 | '{}' | 图关联摘要 |
| created_at | TIMESTAMPTZ | 否 | now() | - |
| confirmed_at | TIMESTAMPTZ | 是 | - | 确认时间 |
| closed_at | TIMESTAMPTZ | 是 | - | 关闭时间 |

索引：`idx_cases_tenant_status`、`idx_cases_assigned`、`idx_cases_level_time`、`idx_cases_chargeback`

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

索引：`idx_events_case`、`idx_events_tenant_time`

#### appeals（申诉表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| case_id | UUID | 否 | - | 关联案件 ID |
| appellant_type | VARCHAR(20) | 否 | - | 申诉人类型：merchant/cardholder |
| appellant_id | VARCHAR(100) | 否 | - | 申诉人 ID |
| reason | VARCHAR(30) | 否 | - | 申诉理由 |
| description | TEXT | 是 | - | 详细描述 |
| llm_analysis | JSONB | 是 | - | LLM 文本分析结果 |
| status | VARCHAR(20) | 否 | 'pending' | pending/approved/rejected |
| reviewer_id | UUID | 是 | - | 审核人 |
| reviewed_at | TIMESTAMPTZ | 是 | - | 审核时间 |
| review_comment | TEXT | 是 | - | 审核意见 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_appeals_tenant_status`、`idx_appeals_case`

### 3.4 规则引擎

#### rules（规则表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 是 | - | 租户 ID（null 表示全局） |
| rule_id | VARCHAR(50) | 否 | - | 规则 ID（如 R001） |
| name | VARCHAR(100) | 否 | - | 规则名称 |
| description | TEXT | 是 | - | 描述 |
| category | VARCHAR(30) | 否 | - | 类别：amount/geo/device/velocity/aml |
| expression | TEXT | 否 | - | DSL 表达式 |
| action | VARCHAR(20) | 否 | - | 动作：block/review |
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
| rule_id | UUID | 否 | - | 规则 ID |
| version | VARCHAR(20) | 否 | - | 版本号 |
| expression | TEXT | 否 | - | DSL 表达式 |
| status | VARCHAR(20) | 否 | 'draft' | draft/canary/active/retired |
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
| tenant_id | UUID | 是 | - | 租户 ID |
| model_type | VARCHAR(30) | 否 | - | 类型：structured/text/behavior/fusion/gnn |
| version | VARCHAR(50) | 否 | - | 版本号 |
| status | VARCHAR(20) | 否 | 'registered' | registered/canary/active/retired |
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

索引：`uk_models_tenant_type_version`、`idx_models_status`

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
| severity | VARCHAR(20) | 否 | - | 严重度 |
| detected_at | TIMESTAMPTZ | 否 | now() | 检测时间 |
| resolved_at | TIMESTAMPTZ | 是 | - | 处理时间 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_drift_tenant_model`、`idx_drift_severity_time`

### 3.6 反洗钱

#### aml_reports（反洗钱报告表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| report_type | VARCHAR(20) | 否 | - | 类型：large/suspicious |
| report_no | VARCHAR(50) | 否 | - | 报告编号 |
| transaction_id | UUID | 是 | - | 关联交易 ID |
| case_id | UUID | 是 | - | 关联案件 ID |
| amount | BIGINT | 否 | - | 金额 |
| content_xml | TEXT | 否 | - | XML 报告内容 |
| status | VARCHAR(20) | 否 | 'pending' | pending/reviewed/submitted |
| reviewer_id | UUID | 是 | - | 复核人 |
| submitted_at | TIMESTAMPTZ | 是 | - | 报送时间 |
| submitted_to | VARCHAR(50) | 是 | - | 报送目标 |
| submission_receipt | TEXT | 是 | - | 报送凭证 |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_aml_tenant_status`、`idx_aml_type_time`

#### sanction_screenings（制裁名单筛查表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
| entity_type | VARCHAR(20) | 否 | - | 实体类型：person/entity |
| entity_name | VARCHAR(200) | 否 | - | 实体名称 |
| entity_id_hash | VARCHAR(64) | 否 | - | 实体 ID hash |
| list_source | VARCHAR(50) | 否 | - | 名单来源：UN/OFAC/PEP |
| match_score | DECIMAL(5,2) | 否 | - | 匹配分（0-100） |
| matched_name | VARCHAR(200) | 是 | - | 匹配到的名单名称 |
| status | VARCHAR(20) | 否 | 'pending' | pending/cleared/blocked |
| screened_at | TIMESTAMPTZ | 否 | now() | - |
| created_at | TIMESTAMPTZ | 否 | now() | - |

索引：`idx_screenings_tenant_status`、`idx_screenings_score`

### 3.7 审计

#### audit_logs（审计日志表）

| 字段 | 类型 | 可空 | 默认 | 含义 |
|---|---|---|---|---|
| id | UUID | 否 | - | 主键 |
| tenant_id | UUID | 否 | - | 租户 ID |
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

索引：`idx_audit_tenant_time`、`idx_audit_user`、`idx_audit_resource`

分区：按 `created_at` 月度分区（保留 7 年）

---

## 4. 数据字典

### 4.1 风险等级

| 等级 | 数值范围 | 决策 | 颜色 |
|---|---|---|---|
| low | 0-29 | allow | 绿色 |
| medium | 30-59 | allow | 蓝色 |
| medium_high | 60-79 | review | 橙色 |
| high | 80-100 | block | 红色 |

### 4.2 决策动作

| 动作 | 含义 | 后续 |
|---|---|---|
| allow | 放行 | 记录评分 |
| review | 人工审核 | 生成 P1 案件 |
| block | 拦截 | 生成 P0 案件 + Webhook |

### 4.3 案件状态

| 状态 | 含义 | 允许的下一状态 |
|---|---|---|
| new | 新建 | investigating, closed |
| investigating | 调查中 | confirmed, closed |
| confirmed | 确认欺诈 | closed |
| closed | 已关闭 | - |

---

## 5. 索引与分区策略

### 5.1 高频查询与索引

| 查询场景 | 表 | 索引 |
|---|---|---|
| 按外部交易号查询 | transactions | uk_transactions_tenant_external |
| 按卡号查询历史 | transactions | idx_transactions_card_token_time |
| 商户交易分页 | transactions | idx_transactions_merchant_time |
| 评分历史 | scores | idx_scores_tenant_tx |
| 案件列表分页 | cases | idx_cases_tenant_status + created_at |
| 案件分配 | cases | idx_cases_assigned |
| 审计日志查询 | audit_logs | idx_audit_tenant_time + user_id |

### 5.2 分区策略

| 表 | 分区方式 | 保留期 |
|---|---|---|
| transactions | 月度（occurred_at）| 7 年 |
| scores | 月度（scored_at）| 7 年 |
| cases | 月度（created_at）| 10 年 |
| case_events | 月度（created_at）| 10 年 |
| audit_logs | 月度（created_at）| 7 年 |
| aml_reports | 月度（created_at）| 10 年 |

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

---

## 8. 容量规划

### 8.1 数据量测算（单租户，1000 TPS）

| 表 | 日增量 | 月增量 | 年增量 | 7 年总量 |
|---|---|---|---|---|
| transactions | 8640 万 | 26 亿 | 315 亿 | 2205 亿 |
| scores | 8640 万 | 26 亿 | 315 亿 | 2205 亿 |
| cases | 8.6 万 | 260 万 | 3100 万 | 2.17 亿 |
| audit_logs | 100 万 | 3000 万 | 3.65 亿 | 25.5 亿 |

### 8.2 存储估算

- 单租户 7 年：约 500 TB（含索引）
- 10 租户：5 PB
- V2 优化：冷数据归档至 OSS + 按租户分库

---

## 9. 变更记录

| 版本 | 日期 | 变更人 | 变更内容 | 审核人 |
|---|---|---|---|---|
| V1.0 | 2026-07-27 | 邝振华 | 初稿创建 | - |
