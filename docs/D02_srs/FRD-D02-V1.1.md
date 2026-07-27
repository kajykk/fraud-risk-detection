# FRD-D02 需求规格说明书（SRS）

| 项 | 值 |
|---|---|
| 文档编号 | FRD-D02-V1.1 |
| 文档版本 | V1.1 |
| 编制日期 | 2026-07-27 |
| 文档状态 | 修订稿 |
| 修订依据 | FRD-BASELINE-V1.1（跨文档修订基准） |

---

## 1. 引言

### 1.1 目的

本说明书定义 FRD（金融反欺诈与交易风险预警系统）的功能、非功能需求与约束条件，作为设计、开发、测试、验收的基线。本版 V1.1 依据《FRD 跨文档修订基准 V1.0》对 V1.0 进行系统性修订，收敛 P0 范围、补全验收标准、新增 PIPL/名单/计费合规模块，并对齐统一枚举字典与性能基准。

### 1.2 范围

涵盖：用户认证、商户接入、交易实时评分、规则引擎、ML 模型治理、团伙图分析、案件管理、反洗钱报告、黑灰名单管理、计费对账、PIPL 个人信息保护、PCI-DSS 合规审计等全部功能。

不涵盖：支付清算、账户管理、信用卡发卡（由核心业务系统承担）；反洗钱上报通道本体（由客户/第三方提供接口，FRD 完成对接联调）。

### 1.3 术语表

| 术语 | 含义 |
|---|---|
| FRD | Fraud Risk Detection，本项目代号 |
| 风险分（risk_score） | DECIMAL(5,4)，范围 0.0000-1.0000，越高欺诈概率越高 |
| 风险等级（risk_band） | LOW / MEDIUM / HIGH / CRITICAL 四档 |
| 决策动作（decision） | ALLOW（放行）/ REVIEW（人工审核）/ DENY（拦截）/ CHALLENGE（挑战验证） |
| TPS | Transactions Per Second，每秒交易数 |
| GNN | Graph Neural Network，图神经网络 |
| Tokenization | 用 token 替代明文卡号（PAN），降低 CDE 范围 |
| PCI-DSS | Payment Card Industry Data Security Standard，支付卡行业数据安全标准 |
| PIPL | Personal Information Protection Law，《个人信息保护法》 |
| AML | Anti-Money Laundering，反洗钱 |
| STR | Suspicious Transaction Report，可疑交易报告 |
| CTR | Currency Transaction Report，大额交易报告 |
| KYC | Know Your Customer，客户身份识别 |
| KYB | Know Your Business，商户身份识别 |
| PSI | Population Stability Index，群体稳定性指标，衡量特征/模型漂移 |
| KL | Kullback-Leibler Divergence，KL 散度，衡量分布差异 |
| SHAP | SHapley Additive exPlanations，模型可解释性方法 |
| CDE | Cardholder Data Environment，持卡人数据环境 |
| 等保 2.0 | GB/T 22239 信息安全技术 网络安全等级保护基本要求 2.0 版 |
| QSA | Qualified Security Assessor，PCI-DSS 合格安全评估师 |
| SAQ | Self-Assessment Questionnaire，PCI-DSS 自评问卷 |
| Chargeback | 拒付（持卡人对交易提出异议） |
| False Positive | 误报（正常交易被识别为欺诈） |

### 1.4 参考资料

- FRD-D01 项目立项报告 V1.0
- FRD-BASELINE-V1.1 跨文档修订基准
- DWS 系统架构文档（参考）
- PCI-DSS v4.0 标准
- 《个人信息保护法》（PIPL）
- 《反洗钱法》《反电信网络诈骗法》
- GB/T 22239 等保 2.0 三级
- GB/T 9385-2008 软件需求规格说明书规范

---

## 2. 总体描述

### 2.1 产品定位

FRD 是面向持牌金融机构 + 大型商户的实时反欺诈 SaaS 平台，通过「规则引擎 + 多模态 ML + GNN 团伙检测」三层防护，将欺诈识别延迟从 T+1 缩短至 200ms 内。

**性能目标对齐基准 §2.1：**

| 参数 | 目标值 |
|---|---|
| 评分接口 P99 | < 200ms |
| 单实例 TPS | ≥ 1000 |
| 集群 TPS | ≥ 2000（MVP）/ ≥ 10000（生产扩容后） |
| 模型 AUC | ≥ 0.92 |
| 模型 Recall@1%FPR | ≥ 0.85 |
| 误报率 | ≤ 5%（生产）/ ≤ 10%（试运行过渡期） |
| 模型 PSI 7d | < 0.25 |

### 2.2 用户类别画像

| 角色 | 权限范围 | 关键诉求 |
|---|---|---|
| 风控分析师 | 案件处理 + 申诉处理 + 规则查询 | 高效处置 + 准确判断 |
| 风控经理 | 案件分配 + 规则审批 + 报表审阅 + 团队管理 | 战略决策 + KPI 监控 + 团队效能 |
| 模型科学家 | 模型训练 + 特征管理 + 上线申请 + 漂移分析 | 模型迭代 + 实验追踪 + 上线可控 |
| 商户管理员 | 本商户交易查询 + 申诉 | 接入便捷 + 透明可解释 |
| 合规官 | 审计日志 + AML 报告 + PCI-DSS + PIPL + 等保 | 合规可证明 |
| 系统管理员 | 系统配置 + Kill Switch + 租户管理 + 计费 | 系统运维 + 紧急处置 |
| 审计员（只读） | 审计日志查询 + 报表导出 | 独立审计 + 证据留存 |

> 共 7 类角色（含模型科学家、风控经理），RBAC 矩阵见 D03 SAD。

### 2.3 运行环境

- 服务端：Linux x86_64 / Kubernetes 1.28+ / Python 3.12
- 客户端：现代浏览器（Chrome 110+ / Edge 110+ / Safari 16+）
- 部署：阿里云 cn-hangzhou，多可用区 + PCI-DSS 隔离区（CDE）
- 集成：客户系统通过 REST API + Webhook + Kafka 接入
- LLM：通义千问 / 文心一言 / DeepSeek（国内合规，禁止 OpenAI 数据出境）

### 2.4 约束

- 多租户隔离：单实例支持多客户，PCI-DSS 强制物理或行级隔离
- 合规约束：PCI-DSS v4.0 + PIPL + 反洗钱法 + 反电诈法 + 等保 2.0 三级
- 算法约束：模型不可使用种族/宗教/性别作为特征
- 实时约束：评分 P99 < 200ms（同步）/ 异步 Webhook 兜底
- 数据保留：交易 7 年、案件 10 年、审计日志 7 年
- 网络约束：持卡人数据环境（CDE）严格隔离
- 跨境约束：禁止数据出境，LLM 选型用国内合规服务

### 2.5 假设与依赖

- 假设：客户具备 API 网关，可转发交易流
- 依赖：通义千问 / 文心一言 / DeepSeek（国内合规 LLM，申诉文本分析）
- 依赖：阿里云 Kafka / OSS / KMS
- 依赖：Neo4j Community（MVP/生产首年）/ Enterprise（第 2 年起评估升级）
- 依赖：客户/第三方提供反洗钱上报通道接口，FRD 完成对接联调

---

## 3. 功能需求（FR）

### 3.0 MVP 范围声明

依据修订基准 §5 时间线，将需求按交付阶段分为三批，真正 P0 收敛到「评分 + 规则 + 案件 + 审计 + 认证 + PIPL + AML + 名单 + 计费」核心闭环（约 35 条 P0）。

**Alpha（M4，2026-11-15）—— 核心评分闭环雏形：**
- FR-AUTH-001~006（认证与权限基础）
- FR-MERCHANT-001~004（商户接入）
- FR-SCORE-001, 004, 005, 006, 008（同步评分 + 决策 + SHAP + 幂等 + 缓存）
- FR-RULE-001, 003, 004, 005（规则 DSL + 双轨 + 可解释 + 热更新）
- FR-WARN-001, 002（自动预警 + 案件状态机）
- FR-CASE-001, 004（案件详情 + 处置）
- FR-ADMIN-004（系统监控）
- ML/GNN 以 Mock 形式可演示

**Beta（M5，2026-12-31）—— 80% 功能 + 1 家试点：**
- 含 Alpha 全部 +
- FR-SCORE-002, 003, 007（异步 + 批量 + 4 层回退）
- FR-STRUCT-001~005, 003a, 003b（结构化特征 + 设备指纹）
- FR-FUSION-001~004（多模态融合）
- FR-GNN-001, 002, 004（图建模 + 实时查询 + 团伙识别）
- FR-WARN-003~006（案件分配 + SLA + 拒付）
- FR-CASE-002, 003, 006（历史 + 关联 + 申诉）
- FR-MODEL-001~006（模型治理闭环）
- FR-AML-001~004, 006（AML 核心闭环）
- FR-REPORT-001~005（报表）
- FR-AUDIT-001, 002, 007（审计基础）
- FR-ADMIN-001~003, 005（租户/用户/告警/备份）
- FR-PIPL-001~005（PIPL 核心权利）
- FR-LIST-001, 002, 004（名单接入 + CRUD + 命中查询）
- FR-BILLING-001, 002, 004（计量 + 账单 + 停服）

**GA（M7/M8，2027-02-28 ~ 2027-04-30）—— 全 P0 + P1：**
- 含 Beta 全部 +
- 全部 P1 需求
- FR-PIPL-006（跨境传输评估）
- FR-LIST-003, 005（批量导入 + 多租户隔离）
- FR-BILLING-003, 006（对账文件 + 计费规则配置）
- FR-AUDIT-003~006（PCI 扫描 + 渗透 + 漏洞 + Secret）
- FR-TEXT-004, FR-BEHAV-003, 004（文本/行为 P0 模态）

**P2（生产可降级，GA 后迭代）：**
- FR-TEXT-001, 003（BERT 微调 + 实体抽取）
- FR-BEHAV-001, 002（行为时序建模 + 异常检测）
- FR-GNN-003, 005, 006（GraphSAGE 嵌入 + 离线图计算 + 案件关联推荐）
- FR-MODEL-007, 008（A/B 测试 + 影子模式）
- FR-WARN-005（多通道告警/案件协作）
- FR-BILLING-005（退款流程）

> 枚举值统一采用大写下划线格式，详见修订基准 §3 枚举字典。

### 3.1 FR-AUTH 用户认证与权限

#### 3.1.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-AUTH-001 | 用户登录 | P0 | 邮箱+密码+2FA（TOTP）强制 |
| FR-AUTH-002 | 密码策略 | P0 | 长度≥14、含大小写+数字+特殊字符、90 天轮换、历史 5 次不可重用 |
| FR-AUTH-003 | 角色权限 | P0 | RBAC，7 类角色 × 功能矩阵 |
| FR-AUTH-004 | 多租户隔离 | P0 | 行级隔离（PostgreSQL RLS）+ KMS per-tenant key + 审计日志分离 + 租户级配额 + 租户级性能隔离 |
| FR-AUTH-005 | 会话管理 | P0 | JWT 30min + Refresh 7d + 空闲 30min 登出（适配风控分析师案件处理场景） |
| FR-AUTH-006 | 登录审计 | P0 | 登录成功/失败 + IP/UA + 异地告警 |
| FR-AUTH-007 | IP 白名单 | P1 | 商户 API 调用限制 IP |

#### 3.1.2 P0 验收标准

**FR-AUTH-001 用户登录**
验收标准：
- Given 已注册用户且账号未锁定
- When POST /auth/login 提交邮箱+密码+TOTP
- Then 返回 JWT + Refresh Token，HTTP 200
- 性能：P99 < 500ms
- 合规：登录事件写入 audit_logs

**FR-AUTH-002 密码策略**
验收标准：
- Given 用户修改密码
- When 提交长度 < 14 或不含 4 类字符或与最近 5 次重复
- Then 返回 HTTP 400 + 字段级错误提示
- 合规：符合 PCI-DSS 8.3 密码要求

**FR-AUTH-003 角色权限**
验收标准：
- Given 7 类角色已配置 RBAC 矩阵
- When 风控分析师尝试访问租户管理接口
- Then 返回 HTTP 403
- 合规：最小权限原则

**FR-AUTH-004 多租户隔离**
验收标准：
- Given 租户 A 用户登录并设置 app.tenant_id
- When 查询任意业务表
- Then 仅返回租户 A 数据（PostgreSQL RLS 生效）
- Given 跨租户访问尝试
- When 租户 A 用户查询租户 B 数据
- Then 返回 HTTP 403 + 审计日志记录
- 合规：KMS per-tenant key 隔离 + 审计日志按租户分离 + 租户级 QPS 配额生效

**FR-AUTH-005 会话管理**
验收标准：
- Given 用户登录获得 JWT（30min 有效）
- When 空闲 30min 无操作
- Then JWT 失效，需重新登录
- Given Refresh Token 7d 有效
- When 调用 /auth/refresh
- Then 签发新 JWT
- 合规：会话超时符合 PCI-DSS 8.2

**FR-AUTH-006 登录审计**
验收标准：
- Given 用户登录（成功或失败）
- When 登录请求处理完成
- Then audit_logs 记录 user_id + IP + UA + result + timestamp
- Given 同一账号 5min 内 5 次失败
- When 触发异地登录
- Then 账号锁定 15min + 告警通知

### 3.2 FR-MERCHANT 商户接入管理

#### 3.2.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-MERCHANT-001 | 商户注册 | P0 | 资质上传 + 合同签署 + KYB 审核 |
| FR-MERCHANT-002 | API Key 管理 | P0 | 每商户 ≤ 5 个 Key + IP 白名单 |
| FR-MERCHANT-003 | 接入文档 | P0 | SDK + Mock + 沙箱环境 |
| FR-MERCHANT-004 | Webhook 配置 | P0 | 决策结果回调地址 + 重试策略（指数退避） |
| FR-MERCHANT-005 | 流量配额 | P1 | 按套餐限制 QPS |
| FR-MERCHANT-006 | 商户画像 | P1 | 行业/规模/历史欺诈率 |

#### 3.2.2 P0 验收标准

**FR-MERCHANT-001 商户注册**
验收标准：
- Given 商户提交资质材料 + 合同
- When KYB 审核通过
- Then 商户状态置为 ACTIVE，分配 tenant_id
- 合规：KYB 信息保留 7 年

**FR-MERCHANT-002 API Key 管理**
验收标准：
- Given 商户已激活
- When 创建 API Key（≤ 5 个）
- Then 返回 Key 明文仅一次 + 存储 hash + 关联 IP 白名单
- Given IP 白名单外的调用
- When 使用该 Key
- Then 返回 HTTP 403

**FR-MERCHANT-003 接入文档**
验收标准：
- Given 新商户接入
- When 访问开发者门户
- Then 提供 SDK + Mock 服务 + 沙箱环境 + 在线文档
- 性能：沙箱 P99 < 500ms

**FR-MERCHANT-004 Webhook 配置**
验收标准：
- Given 商户配置回调地址
- When 评分决策产生
- Then Webhook 在 5s 内回调 + 签名校验
- Given 回调失败
- When 重试 5 次（指数退避 1s/2s/4s/8s/16s）
- Then 最终失败记入死信队列 + 告警

### 3.3 FR-SCORE 实时交易评分

#### 3.3.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-SCORE-001 | 同步评分 | P0 | POST /transactions/score，P99 < 200ms |
| FR-SCORE-002 | 异步评分 | P0 | POST /transactions/score/async，Webhook 回调 |
| FR-SCORE-003 | 批量回查 | P0 | POST /transactions/score/batch，T+1 复核 |
| FR-SCORE-004 | 决策动作 | P0 | decision ∈ {ALLOW, REVIEW, DENY, CHALLENGE} 四档输出 |
| FR-SCORE-005 | 风险分 + SHAP | P0 | risk_score DECIMAL(5,4) 0.0000-1.0000 + risk_band + Top5 SHAP 归因 |
| FR-SCORE-006 | 幂等性 | P0 | Idempotency-Key 防重 |
| FR-SCORE-007 | 4 层回退 | P0 | 主 ML → 备用 ML → 规则 → 启发式（定义行为，FR-MODEL-006 引用） |
| FR-SCORE-008 | 缓存策略 | P0 | 同卡号+同金额 5min 内复用 |

#### 3.3.2 P0 验收标准

**FR-SCORE-001 同步评分**
验收标准：
- Given IEEE-CIS 数据集 + 200 并发
- When POST /transactions/score
- Then P99 < 200ms（采样窗口 5min，统计方法 p99）+ 返回 decision + risk_score + risk_band
- 性能：单实例 TPS ≥ 1000
- 合规：不存储明文 PAN

**FR-SCORE-002 异步评分**
验收标准：
- Given 交易提交至 Kafka 评分主题
- When 异步消费处理完成
- Then Webhook 回调结果，端到端延迟 < 5s
- 性能：吞吐 ≥ 10000 笔/分钟

**FR-SCORE-003 批量回查**
验收标准：
- Given T+1 批量交易 ID 列表（≤ 10000 条）
- When POST /transactions/score/batch
- Then 返回每笔评分结果，整体 < 60s
- 性能：吞吐 ≥ 10000 笔/分钟

**FR-SCORE-004 决策动作**
验收标准：
- Given 评分结果产生
- When risk_band = CRITICAL
- Then decision = DENY
- Given risk_band = HIGH
- Then decision = REVIEW 或 CHALLENGE
- Given risk_band = LOW
- Then decision = ALLOW
- 合规：decision 枚举值大写下划线

**FR-SCORE-005 风险分 + SHAP**
验收标准：
- Given 模型推理完成
- When 返回评分结果
- Then risk_score ∈ [0.0000, 1.0000]（DECIMAL(5,4)）+ risk_band ∈ {LOW, MEDIUM, HIGH, CRITICAL} + Top5 SHAP 因子
- 性能：SHAP 计算 P99 < 50ms（基于 TreeSHAP）
- 合规：支持用户查询拒付理由（对接 PIPL 自动化决策解释权）

**FR-SCORE-006 幂等性**
验收标准：
- Given 相同 Idempotency-Key
- When 重复提交评分
- Then 返回首次结果，不重复计费
- 合规：幂等记录保留 24h

**FR-SCORE-007 4 层回退**
验收标准：
- Given 主 ML 服务健康
- When 评分请求
- Then 主 ML 推理返回
- Given 主 ML 超时/异常
- When 切换备用 ML
- Then 备用 ML 接管，切换延迟 < 100ms
- Given 备用 ML 也异常
- When 降级规则引擎
- Then 规则引擎输出决策
- Given 规则引擎异常
- When 降级启发式
- Then 启发式输出 ALLOW（默认放行）+ 告警
- 合规：每次回退记入 audit_logs，FR-MODEL-006 从模型治理视角引用本回退链

**FR-SCORE-008 缓存策略**
验收标准：
- Given 同卡号+同金额 5min 内重复评分
- When 命中 Redis 缓存
- Then 返回缓存结果，P99 < 10ms
- 性能：缓存命中率 ≥ 30%

### 3.4 FR-STRUCTURED 结构化模态

#### 3.4.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-STRUCT-001 | 交易特征工程 | P0 | 金额/时间/商户/设备/历史频次 |
| FR-STRUCT-002 | 实时聚合特征 | P0 | 滑窗 1min/5min/1h/24h 聚合 |
| FR-STRUCT-003a | 客户端指纹采集 SDK | P0 | Canvas/WebGL/字体组合 hash 采集 |
| FR-STRUCT-003b | 设备 ID 持久化与归并 | P0 | device_id 持久化 + 跨会话归并 |
| FR-STRUCT-003c | 异常设备检测 | P1 | 模拟器/root/代理识别 |
| FR-STRUCT-003d | 设备风险评分 | P1 | 设备维度风险分 0.0000-1.0000 |
| FR-STRUCT-004 | 用户画像 | P0 | 历史 AOV/偏好品类/常驻地域 |
| FR-STRUCT-005 | LightGBM 模型 | P0 | 单模态评分 0.0000-1.0000 |

#### 3.4.2 P0 验收标准

**FR-STRUCT-001 交易特征工程**
验收标准：
- Given 交易数据接入
- When 特征工程执行
- Then 输出 ≥ 50 维结构化特征，特征计算 P99 < 30ms
- 性能：特征缺失率 < 5%

**FR-STRUCT-002 实时聚合特征**
验收标准：
- Given Redis 滑窗数据
- When 查询 1min/5min/1h/24h 聚合
- Then 返回同卡/同设备/同 IP 聚合统计，P99 < 20ms
- 性能：聚合特征计算延迟 < 30ms

**FR-STRUCT-003a 客户端指纹采集 SDK**
验收标准：
- Given 商户页面集成 SDK
- When 用户访问
- Then 采集 Canvas/WebGL/字体 hash，生成 device_fingerprint，SDK 体积 < 50KB
- 合规：不采集明文 PAN

**FR-STRUCT-003b 设备 ID 持久化与归并**
验收标准：
- Given 同一设备跨会话访问
- When device_fingerprint 匹配
- Then 归并至同一 device_id，归并准确率 ≥ 95%
- 性能：归并查询 P99 < 50ms

**FR-STRUCT-004 用户画像**
验收标准：
- Given 用户历史交易 ≥ 10 笔
- When 画像生成
- Then 输出 AOV/偏好品类/常驻地域，画像更新延迟 < 1h
- 合规：画像数据按 purpose 限制（FR-PIPL-002）

**FR-STRUCT-005 LightGBM 模型**
验收标准：
- Given IEEE-CIS 训练集
- When 模型训练完成
- Then 单模态 AUC ≥ 0.90，推理 P99 < 30ms
- 性能：模型推理 P99 < 30ms

### 3.5 FR-TEXT 文本模态

#### 3.5.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-TEXT-001 | 交易备注分析（BERT 中文微调） | P2 | BERT 中文微调（金融领域），生产可降级 |
| FR-TEXT-002 | 客服对话情感 | P1 | 申诉文本情绪识别 |
| FR-TEXT-003 | 实体抽取 | P2 | 商品/地址/收款人实体识别，生产可降级 |
| FR-TEXT-004 | 速率限制 | P0 | 文本模态 P99 < 100ms |

#### 3.5.2 P0 验收标准

**FR-TEXT-004 速率限制**
验收标准：
- Given 文本模态调用
- When 单笔文本分析
- Then P99 < 100ms，超时降级为空特征
- 性能：P99 < 100ms
- 合规：文本数据脱敏存储

### 3.6 FR-BEHAVIOR 行为时序模态

#### 3.6.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-BEHAV-001 | 点击流（行为时序建模） | P2 | 用户会话路径异常检测，生产可降级 |
| FR-BEHAV-002 | 输入节奏（行为异常检测） | P2 | 打字节奏/滑动节奏异常，生产可降级 |
| FR-BEHAV-003 | 1D-CNN | P0 | 时序信号编码 |
| FR-BEHAV-004 | IsolationForest | P0 | 无监督异常检测 |

#### 3.6.2 P0 验收标准

**FR-BEHAV-003 1D-CNN**
验收标准：
- Given 时序行为信号输入
- When 1D-CNN 编码
- Then 输出固定维度向量，推理 P99 < 50ms
- 性能：推理 P99 < 50ms

**FR-BEHAV-004 IsolationForest**
验收标准：
- Given 历史行为基线
- When IsolationForest 检测
- Then 输出异常分 0.0000-1.0000，召回率 ≥ 0.80
- 性能：推理 P99 < 30ms

### 3.7 FR-FUSION 多模态融合

#### 3.7.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-FUSION-001 | 三模态加权 | P0 | 结构化 + 文本 + 行为融合 |
| FR-FUSION-002 | Stacking 集成 | P0 | 二级 LightGBM 元学习器 |
| FR-FUSION-003 | 模态缺失容错 | P0 | 单模态缺失仍可输出 |
| FR-FUSION-004 | 融合优先级 | P0 | 按 modality_confidence 动态加权 |

#### 3.7.2 P0 验收标准

**FR-FUSION-001 三模态加权**
验收标准：
- Given 三模态评分输入
- When 融合引擎计算
- Then 输出融合 risk_score，融合 AUC ≥ 0.92
- 性能：融合计算 P99 < 20ms

**FR-FUSION-002 Stacking 集成**
验收标准：
- Given 二级 LightGBM 元学习器
- When 训练完成
- Then 融合 AUC ≥ 单模态最大 AUC + 0.02
- 性能：推理 P99 < 30ms

**FR-FUSION-003 模态缺失容错**
验收标准：
- Given 文本或行为模态缺失
- When 融合计算
- Then 仍输出 risk_score，缺失模态权重置 0
- 合规：缺失事件记入 audit_logs

**FR-FUSION-004 融合优先级**
验收标准：
- Given 各模态 confidence 已计算
- When 动态加权
- Then 高 confidence 模态权重提升，低 confidence 降低
- 性能：动态加权 P99 < 10ms

### 3.8 FR-RULE 规则引擎

#### 3.8.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-RULE-001 | 规则 DSL | P0 | YAML 配置 + 表达式引擎（Python eval 受限沙箱，备选 aviator） |
| FR-RULE-002 | 规则版本管理 | P0 | 灰度发布 + 回滚，rule_status ∈ {DRAFT, CANARY, ACTIVE, RETIRED} |
| FR-RULE-003 | 规则与 ML 协同 | P0 | 双轨决策（任一触发即拦截） |
| FR-RULE-004 | 规则可解释 | P0 | 命中规则列表输出 |
| FR-RULE-005 | 规则热更新 | P0 | 不重启加载新规则 |

#### 3.8.2 P0 验收标准

**FR-RULE-001 规则 DSL**
验收标准：
- Given YAML 规则配置
- When 表达式引擎执行（Python eval 受限沙箱，禁用 os/sys/open 等危险函数）
- Then 返回命中结果，P99 < 10ms
- Given 危险函数调用
- When 沙箱拦截
- Then 抛出 SecurityError + 拒绝执行
- 性能：单规则评估 P99 < 10ms
- 合规：沙箱隔离符合安全规范

**FR-RULE-002 规则版本管理**
验收标准：
- Given 规则新版本提交
- When 灰度发布 5% → 25% → 100%
- Then rule_status 流转 DRAFT → CANARY → ACTIVE，旧版本 RETIRED
- Given 回滚触发
- When 一键回滚
- Then 恢复至上一 ACTIVE 版本，延迟 < 10s

**FR-RULE-003 规则与 ML 协同**
验收标准：
- Given 规则与 ML 同时评估
- When 任一触发 DENY
- Then 最终 decision = DENY
- Given 规则 REVIEW + ML ALLOW
- Then decision = REVIEW
- 合规：双轨决策可追溯

**FR-RULE-004 规则可解释**
验收标准：
- Given 规则评估完成
- When 返回结果
- Then 输出命中规则 ID 列表 + rule_action ∈ {BLOCK, REVIEW}
- 合规：命中规则记入评分记录

**FR-RULE-005 规则热更新**
验收标准：
- Given 新规则已通过审批
- When 加载至引擎
- Then 不重启即时生效，生效延迟 < 5s
- 性能：热更新期间评分 P99 < 200ms

### 3.9 FR-GNN 团伙图分析

#### 3.9.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-GNN-001 | 图数据建模 | P0 | 账户-商户-设备-IP 多关系图 |
| FR-GNN-002 | 实时图查询 | P0 | Cypher 查询 P99 < 2s（千万级节点） |
| FR-GNN-003 | GraphSAGE 嵌入 | P2 | 节点向量化用于 ML 特征，生产可降级 |
| FR-GNN-004 | 团伙识别 | P0 | 社区发现 + 中心性分析 |
| FR-GNN-005 | 离线图计算 | P2 | 每日全量刷新嵌入，生产可降级 |
| FR-GNN-006 | 案件关联推荐 | P2 | 查询节点 k 跳关联节点，生产可降级 |

#### 3.9.2 P0 验收标准

**FR-GNN-001 图数据建模**
验收标准：
- Given 交易/账户/设备/IP 数据
- When 构建多关系图
- Then 节点/边写入 Neo4j，千万级节点构建完成 < 1h
- 性能：图构建吞吐 ≥ 10000 节点/秒

**FR-GNN-002 实时图查询**
验收标准：
- Given 千万级节点图
- When Cypher 查询 2 跳邻居
- Then P99 < 2s，返回关联节点列表
- 性能：P99 < 2s

**FR-GNN-004 团伙识别**
验收标准：
- Given 图数据已建模
- When 社区发现算法执行（Louvain/Label Propagation）
- Then 输出团伙社区列表 + 中心性排名，离线任务 < 2h
- 合规：团伙标签可用于案件调查

### 3.10 FR-WARN 预警与案件管理

#### 3.10.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-WARN-001 | 自动预警 | P0 | risk_band ∈ {HIGH, CRITICAL} 触发 P0 案件 + 实时推送 |
| FR-WARN-002 | 案件状态机 | P0 | case_status ∈ {OPEN, IN_REVIEW, CONFIRMED, CLOSED, FALSE_ALARM} |
| FR-WARN-003 | 案件分配 | P0 | 按金额/类型自动分配分析师 |
| FR-WARN-004 | SLA 升级 | P0 | P0 案件 4h 未处理 → 升级经理 |
| FR-WARN-005 | 多通道告警/案件协作 | P2 | 多分析师协作 + 评论 + 多通道推送，生产可降级 |
| FR-WARN-006 | 拒付管理 | P0 | 拒付关联案件 + SHAP 附送 |

#### 3.10.2 P0 验收标准

**FR-WARN-001 自动预警**
验收标准：
- Given 评分结果 risk_band ∈ {HIGH, CRITICAL}
- When 评分完成
- Then 自动创建案件（case_status = OPEN）+ 实时推送通知，延迟 < 5s
- 性能：预警延迟 < 5s

**FR-WARN-002 案件状态机**
验收标准：
- Given 案件已创建（OPEN）
- When 分析师受理
- Then case_status 流转 OPEN → IN_REVIEW → CONFIRMED → CLOSED（或 FALSE_ALARM）
- Given 非法状态跳转
- When OPEN 直接到 CLOSED
- Then 拒绝 + 返回 HTTP 400
- 合规：状态流转记入 audit_logs

**FR-WARN-003 案件分配**
验收标准：
- Given 新案件产生
- When 按金额/类型匹配分配规则
- Then 分配至对应分析师，分配延迟 < 10s
- 性能：分配延迟 < 10s

**FR-WARN-004 SLA 升级**
验收标准：
- Given P0 案件 4h 未处理
- When SLA 计时触发
- Then 自动升级至风控经理 + 告警
- 合规：SLA 违规记入报表

**FR-WARN-006 拒付管理**
验收标准：
- Given 持卡人发起拒付
- When 关联原始交易案件
- Then 案件附送 SHAP 归因 + 历史评分，关联延迟 < 5s
- 合规：拒付记录保留 10 年

### 3.11 FR-CASE 案件调查

#### 3.11.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-CASE-001 | 案件详情 | P0 | 交易详情 + SHAP + 图关联 |
| FR-CASE-002 | 历史交易 | P0 | 同卡号/同设备/同 IP 历史 |
| FR-CASE-003 | 关联案件 | P0 | GNN 推荐关联案件 |
| FR-CASE-004 | 处置动作 | P0 | 拦截/放行/标记/加入黑名单 |
| FR-CASE-005 | 调查笔记 | P1 | 富文本 + 附件 |
| FR-CASE-006 | 申诉处理 | P0 | 商户/持卡人申诉 + 文本分析 |

#### 3.11.2 P0 验收标准

**FR-CASE-001 案件详情**
验收标准：
- Given 案件已创建
- When 查询案件详情
- Then 返回交易详情 + SHAP Top5 + 图关联节点，P99 < 500ms
- 性能：P99 < 500ms

**FR-CASE-002 历史交易**
验收标准：
- Given 案件关联卡号/设备/IP
- When 查询历史交易
- Then 返回 90 天内同维度历史交易，P99 < 1s
- 性能：P99 < 1s

**FR-CASE-003 关联案件**
验收标准：
- Given 案件已创建
- When GNN 推荐关联案件
- Then 返回 Top10 关联案件 + 关联强度，P99 < 2s
- 性能：P99 < 2s

**FR-CASE-004 处置动作**
验收标准：
- Given 案件已确认（CONFIRMED）
- When 分析师执行处置（拦截/放行/标记/加入黑名单）
- Then 处置生效 + 黑名单写入 + 审计日志
- 合规：处置动作记入 audit_logs

**FR-CASE-006 申诉处理**
验收标准：
- Given 商户/持卡人提交申诉
- When 申诉文本分析（LLM 国内合规）
- Then 输出情感 + 实体 + 建议，appeal_status ∈ {PENDING, APPROVED, REJECTED, WITHDRAWN}
- 合规：LLM 选型为通义千问/DeepSeek（禁止 OpenAI 出境）

### 3.12 FR-MODEL 模型治理

#### 3.12.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-MODEL-001 | 模型注册 | P0 | 版本/指标/训练数据 hash，model_status ∈ {REGISTERED, CANARY, ACTIVE, RETIRED} |
| FR-MODEL-002 | 金丝雀发布 | P0 | 5% → 25% → 100% 三阶段 |
| FR-MODEL-003 | 漂移检测 | P0 | 每日 PSI/KL，PSI > 0.1 告警 / PSI > 0.25 失效 |
| FR-MODEL-004 | 自动回滚 | P0 | AUC 下降 > 5% 触发 |
| FR-MODEL-005 | Kill Switch | P0 | 管理员一键全局关停 ML |
| FR-MODEL-006 | 4 层回退（模型治理视角） | P0 | 引用 FR-SCORE-007 回退行为，补充模型治理视角（状态流转 + 治理审计） |
| FR-MODEL-007 | A/B 测试 | P2 | 双模型并行 + 决策对比，生产可降级 |
| FR-MODEL-008 | 影子模式 | P2 | 新模型不参与决策仅记录，生产可降级 |

#### 3.12.2 P0 验收标准

**FR-MODEL-001 模型注册**
验收标准：
- Given 模型训练完成
- When 提交注册
- Then model_status = REGISTERED，记录版本/指标/训练数据 hash
- 合规：训练数据 hash 可追溯

**FR-MODEL-002 金丝雀发布**
验收标准：
- Given 模型已注册
- When 金丝雀发布 5% → 25% → 100%
- Then model_status 流转 REGISTERED → CANARY → ACTIVE，每阶段观察 24h
- Given 阶段指标下降
- When 触发回滚
- Then 恢复至上一 ACTIVE 版本，延迟 < 30s

**FR-MODEL-003 漂移检测**
验收标准：
- Given 每日特征/预测分布采样
- When 计算 PSI
- Then PSI > 0.1 触发告警（drift_severity = MEDIUM），PSI > 0.25 触发失效（drift_severity = CRITICAL + 自动回滚）
- 性能：PSI 计算每日 1 次，< 5min 完成
- 合规：漂移指标 PSI 7d < 0.25

**FR-MODEL-004 自动回滚**
验收标准：
- Given 在线 AUC 监控
- When AUC 下降 > 5%
- Then 自动回滚至上一 ACTIVE 版本 + 告警，回滚延迟 < 30s
- 合规：回滚事件记入 audit_logs

**FR-MODEL-005 Kill Switch**
验收标准：
- Given 管理员触发 Kill Switch
- When 全局关停 ML
- Then 所有评分降级至规则引擎，生效延迟 < 5s
- 合规：Kill Switch 操作记入 audit_logs + 双人复核

**FR-MODEL-006 4 层回退（模型治理视角）**
验收标准：
- Given FR-SCORE-007 定义回退行为
- When 回退发生
- Then model_status 流转记录 + 治理审计日志（含回退原因/层级/持续时间）
- 合规：回退事件纳入模型治理报表

### 3.13 FR-AML 反洗钱报告

#### 3.13.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-AML-001 | 可疑交易识别 | P0 | 规则 + ML 双轨识别 |
| FR-AML-002 | 大额交易报告 | P0 | 单笔 ≥ 5 万人民币 或 当日累计 ≥ 5 万人民币 / 1 万美元等值外币自动上报 |
| FR-AML-003 | 可疑交易报告 | P0 | STR 模板生成 + 人工复核 |
| FR-AML-004 | 反洗钱报送 | P0 | 接入客户/第三方反洗钱监测系统接口（FRD 完成对接联调） |
| FR-AML-005 | 客户尽调 | P1 | KYC/KYB 信息管理 |
| FR-AML-006 | 黑名单匹配 | P0 | 制裁名单/政治暴露人（对接 FR-LIST） |

#### 3.13.2 P0 验收标准

**FR-AML-001 可疑交易识别**
验收标准：
- Given 规则 + ML 双轨评估
- When 命中可疑模式
- Then 生成 AML 预警，aml_report_type = SUSPICIOUS
- 合规：识别逻辑符合反洗钱法

**FR-AML-002 大额交易报告**
验收标准：
- Given 单笔交易 ≥ 5 万人民币 或 当日累计 ≥ 5 万人民币 / 1 万美元等值外币
- When 触发大额报告
- Then 生成 CTR，aml_report_type = LARGE，aml_report_status = PENDING
- 合规：累计逻辑按客户+账户维度计算

**FR-AML-003 可疑交易报告**
验收标准：
- Given 可疑交易已识别
- When STR 模板生成
- Then 输出标准 STR 报告 + 人工复核流程，复核 SLA < 24h
- 合规：STR 模板符合人行规范

**FR-AML-004 反洗钱报送**
验收标准：
- Given 客户/第三方提供上报接口
- When FRD 完成对接联调
- Then aml_report_status 流转 PENDING → SUBMITTED → ACCEPTED/REJECTED，提供联调报告
- 合规：上报通道由客户/第三方提供，FRD 完成对接联调

**FR-AML-006 黑名单匹配**
验收标准：
- Given 交易接入 + 名单已加载（FR-LIST）
- When 实时匹配制裁名单/PEP
- Then 命中即 decision = DENY + 生成案件，P99 < 50ms
- 性能：匹配 P99 < 50ms
- 合规：对接 FR-LIST 名单模块

### 3.14 FR-REPORT 报表与导出

#### 3.14.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-REPORT-001 | 风控仪表盘 | P0 | 实时欺诈率/拦截率/案件数 |
| FR-REPORT-002 | 趋势分析 | P0 | 周/月/季趋势 |
| FR-REPORT-003 | 商户画像 | P0 | 商户维度风险分布 |
| FR-REPORT-004 | 模型效果 | P0 | AUC/Recall/FPR 时序 |
| FR-REPORT-005 | PDF/Excel 导出 | P0 | 异步生成 + 邮件通知 |
| FR-REPORT-006 | 定时报表 | P1 | 周报邮件推送 |

#### 3.14.2 P0 验收标准

**FR-REPORT-001 风控仪表盘**
验收标准：
- Given 实时评分数据流
- When 查询仪表盘
- Then 返回欺诈率/拦截率/案件数，刷新延迟 < 10s
- 性能：页面 LCP < 2s

**FR-REPORT-002 趋势分析**
验收标准：
- Given 历史评分/案件数据
- When 查询周/月/季趋势
- Then 返回趋势图表数据，P99 < 2s
- 性能：P99 < 2s

**FR-REPORT-003 商户画像**
验收标准：
- Given 商户维度数据
- When 查询商户风险分布
- Then 返回 Top N 商户风险排名，P99 < 2s
- 性能：P99 < 2s

**FR-REPORT-004 模型效果**
验收标准：
- Given 模型在线指标采样
- When 查询 AUC/Recall/FPR 时序
- Then 返回时序数据，统计窗口可配置，P99 < 2s
- 性能：P99 < 2s
- 合规：AUC ≥ 0.92 / Recall@1%FPR ≥ 0.85

**FR-REPORT-005 PDF/Excel 导出**
验收标准：
- Given 报表数据已查询
- When 触发导出
- Then 异步生成 PDF/Excel + 邮件通知，生成时间 < 60s
- 性能：生成时间 < 60s

### 3.15 FR-AUDIT 审计与合规

#### 3.15.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-AUDIT-001 | 操作审计 | P0 | 所有写操作 + 哈希链 |
| FR-AUDIT-002 | 数据访问审计 | P0 | 持卡人数据访问日志 |
| FR-AUDIT-003 | PCI-DSS 季度扫描 | P0 | ASV 扫描报告 |
| FR-AUDIT-004 | 渗透测试 | P0 | 上线前 1 次 + 年度外部 + 年度内部 |
| FR-AUDIT-005 | 漏洞管理 | P0 | Trivy + Snyk + 修复 SLA |
| FR-AUDIT-006 | Secret 管理 | P0 | KMS + 季度轮换 |
| FR-AUDIT-007 | 审计日志保留 | P0 | 7 年 + 不可篡改 |

#### 3.15.2 P0 验收标准

**FR-AUDIT-001 操作审计**
验收标准：
- Given 任意写操作执行
- When 操作完成
- Then audit_logs 记录 user_id + action + target + before/after + hash 链
- 合规：哈希链不可篡改

**FR-AUDIT-002 数据访问审计**
验收标准：
- Given 持卡人数据（PAN Token）被访问
- When 访问完成
- Then 记录访问者 + 时间 + 目的 + 数据范围
- 合规：PCI-DSS 10.2 审计要求

**FR-AUDIT-003 PCI-DSS 季度扫描**
验收标准：
- Given ASV 扫描执行
- When 扫描完成
- Then 生成 ASV 扫描报告 + 无严重漏洞
- 合规：PCI-DSS 11.3.2 季度扫描

**FR-AUDIT-004 渗透测试**
验收标准：
- Given 上线前 / 年度节点
- When 渗透测试执行（上线前 1 次 + 年度外部 + 年度内部）
- Then 输出渗透测试报告 + 高危漏洞 0 + 修复 SLA 达标
- 合规：PCI-DSS 11.3 渗透测试

**FR-AUDIT-005 漏洞管理**
验收标准：
- Given Trivy + Snyk 扫描
- When 发现漏洞
- Then 严重 < 24h / 高 < 7d / 中 < 30d 修复
- 合规：安全高危漏洞 0

**FR-AUDIT-006 Secret 管理**
验收标准：
- Given Secret 存入 KMS
- When 季度轮换
- Then 全部 Secret 轮换 + 旧 Secret 失效
- 合规：PCI-DSS 3.5 密钥管理

**FR-AUDIT-007 审计日志保留**
验收标准：
- Given 审计日志写入
- When 保留 7 年
- Then 期满物理删除 + 删除前不可篡改
- 合规：反洗钱法 7 年保留

### 3.16 FR-ADMIN 系统管理

#### 3.16.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-ADMIN-001 | 租户管理 | P0 | 创建/配置/禁用 |
| FR-ADMIN-002 | 用户管理 | P0 | CRUD + 角色 + IP 白名单 |
| FR-ADMIN-003 | 告警规则 | P0 | 阈值/通知渠道/升级 |
| FR-ADMIN-004 | 系统监控 | P0 | Prometheus + Grafana |
| FR-ADMIN-005 | 备份恢复 | P0 | 每日全量 + 跨可用区 |

#### 3.16.2 P0 验收标准

**FR-ADMIN-001 租户管理**
验收标准：
- Given 系统管理员操作
- When 创建/配置/禁用租户
- Then tenant 生效 + 分配 KMS per-tenant key + 审计日志
- 合规：租户隔离符合 PCI-DSS

**FR-ADMIN-002 用户管理**
验收标准：
- Given 管理员操作
- When CRUD 用户 + 分配角色 + IP 白名单
- Then 用户生效 + RBAC 生效 + 审计日志
- 合规：最小权限原则

**FR-ADMIN-003 告警规则**
验收标准：
- Given 告警规则配置
- When 阈值触发
- Then 按渠道通知 + 升级链生效
- 性能：告警延迟 < 30s

**FR-ADMIN-004 系统监控**
验收标准：
- Given Prometheus 采集 + Grafana 展示
- When 查询监控指标
- Then 返回黄金信号（延迟/流量/错误/饱和度），刷新延迟 < 10s
- 性能：监控采集间隔 < 15s

**FR-ADMIN-005 备份恢复**
验收标准：
- Given 每日全量备份
- When 恢复操作
- Then RTO ≤ 30min（应用 5min + 数据库 30min），RPO ≤ 1min
- 合规：备份加密 + 跨可用区

### 3.17 FR-PIPL 个人信息保护合规

#### 3.17.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-PIPL-001 | 告知同意管理 | P0 | 首次接入时获取用户告知同意，记录 consent_records，consent_status ∈ {GRANTED, WITHDRAWN, EXPIRED} |
| FR-PIPL-002 | 最小必要字段控制 | P0 | 按 consent_purpose 限制字段采集 |
| FR-PIPL-003 | 自动化决策解释权 | P0 | 对接 SHAP 输出，支持用户查询拒付/拦截理由 |
| FR-PIPL-004 | 数据可携带权 | P0 | 支持用户申请数据导出（GET /pipl/data-export） |
| FR-PIPL-005 | 数据删除权 | P0 | 支持用户申请数据删除（POST /pipl/deletion） |
| FR-PIPL-006 | 跨境传输评估 | P1 | 禁止数据出境，LLM 选型用国内合规服务 |

#### 3.17.2 P0 验收标准

**FR-PIPL-001 告知同意管理**
验收标准：
- Given 用户首次接入
- When 展示告知同意书
- Then 用户授予/拒绝同意，consent_status = GRANTED，记录 consent_purpose + timestamp
- Given 用户撤回同意
- When 调用 /consent 撤回
- Then consent_status = WITHDRAWN + 后续停止处理
- 合规：PIPL 第 14/17 条

**FR-PIPL-002 最小必要字段控制**
验收标准：
- Given consent_purpose = TRANSACTION_SCORING
- When 字段采集
- Then 仅采集评分必要字段（金额/卡 Token/设备指纹等），非必要字段拒绝采集
- 合规：PIPL 第 6 条最小必要原则

**FR-PIPL-003 自动化决策解释权**
验收标准：
- Given 用户被 DENY/REVIEW
- When 用户查询拒付理由
- Then 返回 SHAP Top5 归因 + 决策依据说明，P99 < 500ms
- 合规：PIPL 第 24 条自动化决策说明权

**FR-PIPL-004 数据可携带权**
验收标准：
- Given 用户提交数据导出申请
- When POST /pipl/data-export
- Then 生成导出包（JSON）+ 邮件通知下载链接，完成时间 < 72h
- 合规：PIPL 第 45 条数据可携带权

**FR-PIPL-005 数据删除权**
验收标准：
- Given 用户提交数据删除申请
- When POST /pipl/deletion
- Then 删除用户相关数据（保留法定审计义务数据）+ 通知用户，完成时间 < 30d
- 合规：PIPL 第 47 条删除权（法定保留数据除外）

### 3.18 FR-LIST 黑灰名单管理

#### 3.18.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-LIST-001 | 多源名单接入 | P0 | 人行/卡组织/公安/自维护多源名单接入 |
| FR-LIST-002 | 名单 CRUD + 版本管理 | P0 | 名单增删改查 + 版本回滚 |
| FR-LIST-003 | 批量导入 + TTL 失效 | P1 | 批量导入 + 过期自动失效 |
| FR-LIST-004 | 命中查询 + 申诉解除 | P0 | 实时命中查询 + 申诉解除流程 |
| FR-LIST-005 | 名单共享与隔离 | P1 | 多租户名单共享与隔离 |

#### 3.18.2 P0 验收标准

**FR-LIST-001 多源名单接入**
验收标准：
- Given 人行/卡组织/公安/自维护名单源
- When 接入并同步
- Then 名单入库 + 来源标记 + 同步日志，同步频率可配置
- 性能：名单查询 P99 < 50ms
- 合规：名单来源可追溯

**FR-LIST-002 名单 CRUD + 版本管理**
验收标准：
- Given 管理员操作
- When CRUD 名单条目
- Then 生效 + 版本记录 + 审计日志，支持版本回滚
- 合规：名单变更可追溯

**FR-LIST-004 命中查询 + 申诉解除**
验收标准：
- Given 交易接入 + 名单已加载
- When 实时命中查询
- Then 命中即返回名单详情 + 触发 DENY，P99 < 50ms
- Given 用户申诉解除
- When 申诉审核通过
- Then 名单条目移除/标记 + 通知用户
- 性能：命中查询 P99 < 50ms
- 合规：申诉流程 appeal_status ∈ {PENDING, APPROVED, REJECTED, WITHDRAWN}

### 3.19 FR-BILLING 计费对账

#### 3.19.1 需求清单

| 编号 | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-BILLING-001 | 调用量计量 | P0 | 按 API/按笔计量 |
| FR-BILLING-002 | 账单生成 | P0 | 月度账单自动生成 |
| FR-BILLING-003 | 对账文件下载 | P1 | 对账文件 CSV/Excel 下载 |
| FR-BILLING-004 | 欠费停服与恢复 | P0 | 欠费自动停服 + 缴费恢复 |
| FR-BILLING-005 | 退款流程 | P2 | 退款申请 + 审批，生产可降级 |
| FR-BILLING-006 | 计费规则配置 | P1 | 多档套餐配置 |

#### 3.19.2 P0 验收标准

**FR-BILLING-001 调用量计量**
验收标准：
- Given 评分 API 调用
- When 每次调用
- Then 计量记录（tenant_id + api + count + timestamp），计量准确率 100%
- 合规：计量数据保留 7 年

**FR-BILLING-002 账单生成**
验收标准：
- Given 月度计量数据
- When 每月 1 日自动生成账单
- Then 输出账单（按套餐计费）+ 通知商户，生成时间 < 60min
- 合规：账单保留 7 年

**FR-BILLING-004 欠费停服与恢复**
验收标准：
- Given 商户欠费超过宽限期（7 天）
- When 自动停服
- Then API 返回 HTTP 402 + 通知商户
- Given 商户缴费
- When 恢复服务
- Then API 恢复正常 + 通知商户，恢复延迟 < 5min
- 合规：停服/恢复记入 audit_logs

---

## 4. 非功能需求（NFR）

### 4.1 性能

分两阶段目标：

| 指标 | MVP 单实例 | 生产集群 | 测量方法 |
|---|---|---|---|
| 同步评分延迟 P99 | < 200ms | < 200ms | Locust 压测 |
| 同步评分延迟 P999 | < 500ms | < 500ms | 同上 |
| 单实例 TPS | ≥ 1000 | - | 同上 |
| 集群 TPS | ≥ 2000 | ≥ 10000 | 同上 |
| GNN 图查询 P99 | < 2s | < 2s | Neo4j 监控 |
| Webhook 回调延迟 | < 5s | < 5s | 端到端监控 |
| 批量评分吞吐 | ≥ 10000 笔/分钟 | ≥ 10000 笔/分钟 | Celery 监控 |
| 页面 LCP | < 2s | < 2s | Lighthouse |

> MVP 阶段：单实例 1000 TPS；生产阶段：集群 2000-10000 TPS（扩容后）。

### 4.2 可用性

- SLA：99.5%（MVP）/ 99.9%（生产稳态）
- 多可用区部署（单 AZ 起步，扩容后多 AZ 双活）
- 计划停机：每月 1 次维护窗口
- 故障恢复：RTO ≤ 30min（应用层 5min + 数据库 30min），RPO ≤ 1min

### 4.3 安全性

- 传输加密：TLS 1.3
- 存储加密：数据库 TDE + 字段级 Fernet
- 卡号处理：Tokenization（不存储明文 PAN）
- 密码策略：长度 ≥ 14、90 天轮换、历史 5 次不可重用
- 限流：登录 5/min、API 1000/min/商户、评分 10000/min/商户
- OWASP Top10 + PCI-DSS v4.0 全覆盖
- 等保 2.0 三级

### 4.4 可维护性

- 代码覆盖率：总体 ≥ 85%（评分/规则引擎核心 ≥ 90%，ML/GNN ≥ 75%）
- MTTR：< 30min
- 文档完备：D01-D11 + A01-A04
- DWS 复用率：≥ 55%

### 4.5 可观测性

- 三支柱：Metrics / Logs / Traces
- 黄金信号：延迟/流量/错误/饱和度
- SLI/SLO：API 成功率 ≥ 99.5% / P99 < 200ms
- 业务指标：欺诈率/拦截率/误报率/案件数

### 4.6 合规

#### 4.6.1 合规总览

- **PCI-DSS v4.0**：QSA 季度评估，RoC 报告编号 + 日期作为验收证据
- **PIPL**：告知同意、最小必要、数据导出（GET /pipl/data-export）、数据删除（POST /pipl/deletion）、同意管理（/pipl/consent）、自动化决策解释权、数据本地化
- **反洗钱法**：KYC、STR/CTR 上报、7 年审计日志保留；上报通道由客户/第三方提供接口，FRD 完成对接联调
- **等保 2.0 三级**：物理/网络/主机/应用/数据/管理 6 类控制点；测评机构备案证明编号作为验收证据；M1 即启动备案（周期 3-6 个月）
- 数据保留：交易 7 年、案件 10 年、审计 7 年
- 跨境数据传输评估：禁止数据出境，LLM 选型用国内合规服务

#### 4.6.2 PIPL 合规项

| PIPL 条款 | 对应需求 | 验收证据 |
|---|---|---|
| 第 14/17 条 告知同意 | FR-PIPL-001 | consent_records 表 + 同意率统计 |
| 第 6 条 最小必要 | FR-PIPL-002 | 字段采集白名单 + purpose 映射 |
| 第 24 条 自动化决策说明 | FR-PIPL-003 | SHAP 输出 + 用户查询日志 |
| 第 45 条 数据可携带权 | FR-PIPL-004 | 导出请求记录 + 导出包 |
| 第 47 条 删除权 | FR-PIPL-005 | 删除请求记录 + 删除凭证 |
| 第 38/39/40 条 跨境传输 | FR-PIPL-006 | 数据本地化声明 + LLM 合规选型证明 |

#### 4.6.3 等保 2.0 三级控制点映射

| 控制类 | 控制点 | 对应实现 |
|---|---|---|
| 物理与环境安全 | 云等保合规 | 阿里云等保合规机房 |
| 安全通信网络 | VPC + 安全组 + NetworkPolicy | 网络分段 + CDE 隔离区 |
| 安全区域边界 | WAF + IDS/IPS | 阿里云 WAF + DDoS 高防 |
| 安全计算环境 | 堡垒机 + HIDS + 主机加固 + 可信验证 | 堡垒机接入 + 主机基线 |
| 安全管理中心 | 集中监控 + 审计 | Prometheus + Grafana + Loki + 审计中心 |
| 剩余信息保护 | 内存清零 + 磁盘擦除 | 进程退出清零 + 磁盘擦除流程 |

---

## 5. 数据需求

### 5.1 数据实体清单

| 实体 | 来源 | 保留期 | 敏感等级 |
|---|---|---|---|
| 交易记录 | 客户转发 | 7 年 | 极高（PCI） |
| 卡号 Token | Tokenization 服务 | 卡有效期+1 | 中（不存明文） |
| 评分记录 | 系统生成 | 7 年 | 高 |
| 案件记录 | 系统生成 | 10 年 | 高 |
| 审计日志 | 系统生成 | 7 年 | 极高 |
| 模型版本 | 系统生成 | 永久 | 中 |
| 训练数据 | 客户授权 | 模型退役+1 年 | 极高（PCI） |
| 图数据 | 系统生成 | 7 年 | 高 |
| consent_records | 系统生成 | 同意撤回+3 年 | 高（PIPL） |
| 名单数据 | 多源接入 | 名单失效+1 年 | 高 |
| 计量账单 | 系统生成 | 7 年 | 中 |

### 5.2 数据流图

```
                        ┌──── CDE 边界 ────┐
客户交易 ─API→ API Gateway ─→ Tokenization 服务（CDE 内）
                              ↓
                  ┌───────────┴───────────┐
                  ▼                       ▼
            规则引擎                 ML 评分引擎
            （特征存储）             （模型仓库）
                  │                       │
                  └───────┬───────────────┘
                          ▼
                    决策融合 (双轨)
                          │
                  ┌───────┼────────┐
                  ▼       ▼        ▼
              Webhook  Redis 缓存  案件生成
                          │
              Kafka 流（多分区） ─→ GNN 离线图计算
                          │
                  ┌───────┴────────┐
                  ▼                ▼
              计量服务          PIPL 合规
              （计费）         （同意/导出/删除）
```

> 标注：CDE 边界、Redis 缓存、特征存储、模型仓库、Kafka 多分区、Tokenization 服务。

### 5.3 数据保留策略

| 数据类型 | 保留期 | 到期处理 |
|---|---|---|
| 交易记录 | 7 年 | 物理删除（含 Token）|
| 评分记录 | 7 年 | 物理删除 |
| 案件记录 | 10 年 | 物理删除 |
| 审计日志 | 7 年 | 物理删除 |
| 模型版本 | 永久 | 仅保留指标元数据 |
| 备份 | 90 天滚动 | - |
| consent_records | 同意撤回+3 年 | 物理删除 |
| 计量账单 | 7 年 | 物理删除 |

---

## 6. 接口需求

### 6.1 外部接口（入站）

| 接口 | 协议 | 频率 | 数据 |
|---|---|---|---|
| 实时评分 | REST/HTTPS | 实时 | 交易数据 |
| 异步评分 | Kafka | 实时 | 交易数据 |
| 批量回查 | REST/HTTPS | T+1 | 交易 ID 列表 |
| 商户接入 | REST/HTTPS | 实时 | 商户数据 |
| 数据导出申请 | REST/HTTPS | 按需 | 用户 ID |
| 数据删除申请 | REST/HTTPS | 按需 | 用户 ID |
| 同意管理 | REST/HTTPS | 按需 | consent 数据 |

### 6.2 外部接口（出站）

| 接口 | 协议 | 频率 | 数据 |
|---|---|---|---|
| 决策 Webhook | HTTPS | 实时 | 评分结果 |
| 邮件通知 | SMTP | 实时 | 案件通知 |
| 短信通知 | HTTPS | 实时 | 紧急告警 |
| 反洗钱报送 | SFTP/HTTPS | 日度 | STR/CTR 报告 |
| Tokenization | HTTPS | 实时 | 卡号 ↔ Token |
| 数据导出包 | HTTPS | 按需 | JSON 导出包 |

### 6.3 接口治理

- **API 版本管理**：URL 路径版本（/v1/、/v2/），版本生命周期 ≥ 12 个月
- **向后兼容**：新增字段不破坏旧客户端；废弃字段提前 6 个月通知
- **限流**：超限返回 HTTP 429 + Retry-After 头
- **重试策略**：客户端指数退避（1s/2s/4s/8s/16s），最多 5 次
- **错误码**：统一错误码体系（4xx 客户端 / 5xx 服务端）
- **幂等性**：关键写接口支持 Idempotency-Key

---

## 7. 需求追踪矩阵（RTM）

部分示例（完整 RTM 见 D07 测试计划附录）：

| 需求 ID | 设计章节 | 代码模块 | 测试用例 ID |
|---|---|---|---|
| FR-AUTH-001 | SAD-3.2.1 | app/api/v1/auth.py | TC-AUTH-001~005 |
| FR-AUTH-004 | SAD-3.2.4 | app/core/tenant.py | TC-AUTH-010~015 |
| FR-SCORE-001 | SAD-3.4.1 | app/api/v1/score.py | TC-SCORE-010~020 |
| FR-RULE-001 | SAD-3.5.1 | app/core/rule_engine.py | TC-RULE-030~035 |
| FR-GNN-002 | SAD-3.6.2 | app/gnn/graph_query.py | TC-GNN-040~045 |
| FR-MODEL-005 | SAD-3.7.3 | app/core/kill_switch.py | TC-MODEL-050~052 |
| FR-AML-002 | SAD-3.8.1 | app/services/aml_service.py | TC-AML-060~065 |
| FR-PIPL-001 | SAD-3.9.1 | app/api/v1/privacy.py | TC-PIPL-070~075 |
| FR-LIST-001 | SAD-3.10.1 | app/services/list_service.py | TC-LIST-080~085 |
| FR-BILLING-001 | SAD-3.11.1 | app/services/billing.py | TC-BILLING-090~095 |

---

## 8. 变更记录

| 版本 | 日期 | 变更人 | 变更内容 | 审核人 |
|---|---|---|---|---|
| V1.0 | 2026-07-27 | 邝振华 | 初稿创建 | - |
| V1.1 | 2026-07-27 | 邝振华 + AI 协作 | 依据 FRD-BASELINE-V1.1 修订：①新增 FR-PIPL/FR-LIST/FR-BILLING 模块；②补全所有 P0 验收标准（Given-When-Then）；③收敛 P0 范围，引入 P2 分级；④FR-STRUCT-003 拆分为 a/b/c/d；⑤角色扩至 7 类；⑥性能目标分 MVP/生产两阶段；⑦等保 2.0 三级控制点映射；⑧多租户隔离细化；⑨JWT 空闲登出改 30min；⑩AML 大额累计逻辑；⑪PSI 阈值分级；⑫规则 DSL 明确 Python eval 沙箱；⑬渗透测试改为上线前+年度；⑭术语表补全；⑮数据流图标注 CDE；⑯接口治理补充；⑰枚举值对齐大写下划线 | 邝振华 |
