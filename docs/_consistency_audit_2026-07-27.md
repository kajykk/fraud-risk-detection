# FRD 文档-代码一致性审计报告

| 项 | 值 |
|---|---|
| 审计日期 | 2026-07-27 ~ 2026-07-28 |
| 审计范围 | D01-D11 V1.1 文档 vs backend/frontend/ml/gnn/infra 代码库 |
| 审计方法 | 架构师（技术文档）+ 产品经理（业务文档）双轨评估 + 工程师配置修复 |
| 差异总数 | ~100 项（去重后） |
| P0 阻断 | 8 项 — **全部修复** |
| P1 重要 | ~45 项 — 主要项已修复，部分留作后续 |
| P2 一般 | ~47 项 — 记录为已知差异 |

---

## 一、已执行修订清单

### P0 阻断项（8/8 已修复）

| 编号 | 文档 | 差异 | 修复方式 | 执行者 |
|---|---|---|---|---|
| P0-1 | README | 索引指向 V1.0、缺 baseline 条目和 V1.1 变更记录 | 索引升级 V1.2、增补 baseline 条目、变更记录加行 | 产品经理 |
| P0-2 | README/D01/D08 | 里程碑全标"计划"，与实际开发状态脱节 | 状态改为"计划（文档基线已完成，开发提前进行中）"；D01 加状态注记；D08 新增实际进度小节 | 产品经理 + 主理人 |
| P0-3 | D02 | 无当前实现对照，35 条 P0 需求大多仅 stub | §3.0 后新增 §3.0.1 实现对照表（18 模块逐条标注） | 主理人 |
| P0-4 | D04 | risk_score 写 INT 0-100（代码/基准为 DECIMAL(5,4)+risk_band） | §3.2 改 DECIMAL(5,4)、补 risk_band 列、§4.1 改 4 级 0-1 刻度 | 架构师 |
| P0-5 | D10 + helm | 副本数 3/3-9/2 vs values-prod.yaml 6/6-24/4 矛盾 | values-prod.yaml 降为 3/3-9/2 对齐 baseline §8.1 | 工程师 |
| P0-6 | D10 + helm + Dockerfile | 探针路径 /health 必然 404（应用仅暴露 /api/v1/health） | D10 文档 + helm values + Dockerfile HEALTHCHECK 全部改 /api/v1/health | 主理人 + 工程师 |

### P1 重要项（主要项已修复）

| 文档 | 修订内容 | 执行者 |
|---|---|---|
| **D03** | LightGBM→XGBoost（全局 4 处）；Neo4j Enterprise→Community（技术选型表+部署架构+ADR-003）；Redis Cluster→哨兵；Kafka 标注 MVP 暂缓（技术选型+部署架构+ADR-004）；Tempo→Jaeger；Loki/Jaeger 标注 M6 前补齐 | 主理人 |
| **D04** | 枚举逐条对账基准 §3（ATM→QR、补 P3、补 WITHDRAWN、AML 4 值、补 EXPIRED、consent_type 统一 D05 口径、drift 补 KS/WASSERSTEIN）；4 列补定义+迁移 0002 注记；MVP 不分区标注 | 架构师 |
| **D05** | 冒号端点→斜杠（:validate/:retire/:close 共 4 处） | 主理人 |
| **D02** | SHAP 改异步口径（ADR-007，shap_status=PENDING+task_id）；webhook 重试改 1m/5m/30m/2h/12h（对齐 D05/代码） | 主理人 |
| **D06** | 密码 8-32→≥14 位（PCI-DSS 8.3，2 处） | 主理人 |
| **D07** | 测试用例数 ~2040 加注"目标值，当前实际仅 5 个测试文件" | 主理人 |
| **D09** | 新增 R-21~R-24 实际技术风险（后端启动错误/前端 404/git 未初始化/文档脱节）；R-09"团队成员流失"调整为"真人单点故障" | 主理人 |
| **D11** | 196 项表"实现数 196/覆盖率 100%"→"实现数留空/目标覆盖率（M6 填入实测值）" | 主理人 |

### infra 配置修复（工程师完成，7 文件）

| 文件 | 修复内容 |
|---|---|
| infra/helm/frd-backend/values.yaml | 3 处探针 path /health→/api/v1/health |
| infra/helm/frd-backend/values-prod.yaml | replicas 6→3、HPA 6-24→3-9、PDB 4→2（对齐 baseline §8.1） |
| infra/helm/frd-backend/templates/deployment.yaml | 探针注释同步 |
| backend/Dockerfile | HEALTHCHECK 路径 /health→/api/v1/health |
| infra/helm/frd-ml/values.yaml | ML 端口 8500→8501+命令改 ml.scoring.main:app；GNN 端口 8600→8502+命令改 gnn.main:app |
| infra/helm/frd-ml/templates/deployment-ml.yaml | prometheus.io/port 8500→8501 |
| infra/helm/frd-ml/templates/deployment-gnn.yaml | prometheus.io/port 8600→8502 |
| infra/helm/frd-ml/templates/service.yaml | ML/GNN Service port/targetPort 同步修正 |

---

## 二、已知差异与后续修复建议（未完成 P1/P2）

### 代码缺失类（需开发实现，非文档修订）

| 模块 | 差异 | 建议交付里程碑 |
|---|---|---|
| users 表 + 2FA | D02 FR-AUTH 声明但代码无 users 表/模型/TOTP | M4 Alpha |
| 商户 API | D02 FR-MERCHANT 声明但无 /merchants 路由 | M4 Alpha |
| 报表模块 | D05 §9 声明 5 接口但代码无 /reports 路由 | M6 RC |
| 治理 API | D05 §10 声明 5 接口但无 /governance 路由（前端调用 404） | M5 Beta |
| WebSocket | D05 §2.8 声明但后端无 WS 端点 | M5 Beta |
| 幂等中间件 | D05 §2.6 声明 Idempotency-Key 但代码 0 处实现 | M5 Beta |
| Kafka 接入 | D03 ADR-014 声明但完全未实现（MVP 暂缓） | M6 前评估 |
| Loki + Jaeger | D03/D10 声明但 infra 无部署文件 | M6 前补齐 |
| 前端 /audit-logs、/governance/kill-switch | 前端调用但后端无端点（404） | M5 Beta |
| 后端 pydantic 启动错误 | backend_logs.txt 显示 undefined-annotation 运行时错误 | 立即修复 |
| Git 仓库 | 项目目录未初始化 Git | 立即初始化 |

### 文档修订类（P2，后续批量处理）

| 文档 | 待修项 |
|---|---|
| D02 | RTM 模块路径修订（§7）、限流口径统一（租户套餐 QPS）、补 FR-PIPL-007 更正权 + fairness 需求 |
| D03 | §8.1 多 AZ→单 AZ 拓扑重写、§8.2 RTO 统一 D10 口径、模块路径修订（§4.5/§9）、三端 UI 口径统一 |
| D05 | 缺失模块（reports/governance/WS）章节加"⏳ 规划接口"标注、rule_action 正文 4 值→2 值、severity 字段对齐 D04、token expires_in 3600→1800、/ops 路径修订、补录 auth/scores/health 端点 |
| D06 | §10/§13/§14 四章节加"待实现"标注、§7.7 DISABLED→RETIRED、§14.3 REVIEW 状态修订、§11.3 PIPL GET、§13.5.4 webhook 重试 1m/5m/30m/2h/12h、截图死链改占位 |
| D08 | §13.3 预填 CR-001~003 标注"模板示例"、§10.1 D09 链接→V1.1 |
| D10 | §6.2 helm 结构修订（frd-ml 合并 chart）、Celery 队列按代码修订、§5.1 GNN 基础镜像改 CUDA、补 deploy-prod.yml 或改名 |
| D11 | §6.1 API 路径 /graph/detect→/api/v1/gnn/community-detection、§5.3/§7.4 404/403 口径统一、§5.2.3/§8.4 回退链统一、§4.2 过时注记删除 |
| D07/D09 | ✅ 已审计并创建 V1.2（D07 测试用例数标注实际状态；D09 新增 R-21~R-24 实际技术风险+R-09 描述调整）——剩余 P2 项同上 |

---

## 三、审计结论

1. **文档体系与代码库存在双向脱节**：进度表述严重滞后（文档说项目 08-15 才启动，实际代码已写至约 M4 Alpha 雏形水平）；功能描述大量超前（D02 约 35 条 P0 中仅评分主链路为骨架可演示）
2. **跨文档口径冲突**约 15 处（密码长度、规则状态枚举、PIPL GET/POST、webhook 重试、回退链顺序等）——本轮已修复主要冲突项
3. **D04 变更记录与正文不符**的系统性问题已通过 V1.2 枚举逐条对账解决
4. **配置级错误**（探针路径 404、chart 启动命令错误、副本数矛盾）已全部修复并验证通过
5. **核心矛盾（里程碑 vs 实际进度）**已通过"不改计划日期、仅补充实际进展"的方式解决，正当化为 D01 §8.3 PoC/Spike 准入工作

---

## 四、参与成员

| 角色 | 姓名 | 贡献 |
|---|---|---|
| 主理人 | 齐活林（Qi） | 审计编排、差异汇总、P0/P1 修订执行、变更日志 |
| 架构师 | 高见远（Gao） | D03/D04/D05/D10 技术一致性评估（52 项）、D04 V1.2 枚举系统修订 |
| 产品经理 | 许清楚（Xu） | D01/D02/D06/D08/D11 业务一致性评估（51 项）、README+D01 V1.2 修订 |
| 工程师 | 寇豆码（Kou） | infra 3 处配置修复（7 文件，验证通过） |
