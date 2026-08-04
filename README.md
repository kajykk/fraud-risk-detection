# 实时金融反欺诈系统（FRD · Fraud Risk Detection）

> 面向持牌金融机构的**实时反欺诈风控平台**：规则引擎 + 多模态机器学习融合 + GNN 团伙检测三引擎并行决策，覆盖交易评分、案件处置、模型治理与合规安全（PCI-DSS / PIPL / 反洗钱），并配套 K8s 金丝雀发布与全链路可观测性。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-异步高并发-009688)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue_3+TS-Vite_6-42b883)](https://vuejs.org/)
[![ML](https://img.shields.io/badge/ML-XGBoost_·_BERT_·_PyG-ff69b4)](https://pytorch.org/)
[![Tests](https://img.shields.io/badge/Tests-57+-green)](.github/workflows/ci.yml)

---

## 项目定位

对每一笔交易在 **200ms 内** 输出 `ALLOW / REVIEW / CHALLENGE / DENY` 四档风险决策。与传统单模型风控不同，FRD 采用**双轨并行决策架构**（可解释规则引擎 ‖ 黑盒 ML 引擎），并以 **GNN 团伙检测** 识别关联账户欺诈，是完整的生产级工程实现而非 demo。

## 核心亮点

| 能力 | 实现 |
|---|---|
| **双轨实时决策** | 规则引擎与 ML 引擎经 `asyncio.gather` 并行计算后融合决策，评分接口 P99 目标 <200ms，支持同步 / 异步（Celery）/ 批量三种评分形态 |
| **自研规则引擎 DSL** | 手写 Tokenizer + 递归下降解析器（**全程无 eval**），支持 `== != > >= < <= && \|\| ()`；规则版本化、Redis 缓存、**Pub/Sub 热加载**、租户级与全局规则、BLOCK 短路 |
| **多模态 ML 融合** | 结构化（XGBoost）+ 文本（BERT）+ 行为时序（1D-CNN + IsolationForest）三模态并行评分，加权融合（0.6/0.2/0.2）+ 模态熔断自动降级 + 电路熔断回退（Redis 历史均值） |
| **GNN 团伙检测** | Neo4j k-hop 子图 + **GraphSAGE** 图嵌入（PyG）+ **Louvain** 社区发现，团伙风险评分（欺诈率 × 0.7 + 规模 × 0.3），欺诈率 > 0.3 自动标记欺诈团伙 |
| **模型治理** | PSI / KL 漂移检测（1h vs 7d 窗口），**三级 Kill Switch**（L1 全局 / L2 模型 / L3 模态），PSI ≥ 0.25 自动触发模型级熔断回退 |
| **可解释性** | SHAP TreeExplainer 单笔交易归因，特征缓存 + 异步计算任务 |
| **合规安全** | PCI-DSS 卡号 **Token 化**；PIPL 数据主体权利（导出 / 删除 / 更正，反洗钱 7 年法定保留校验）；OAuth2 双凭据（JWT + API Key）；7 角色 RBAC；哈希链审计日志 |
| **金融级工程化** | Celery 任务路由 + Beat 调度（漂移巡检 / 合规归档）、Webhook HMAC-SHA256 签名 + 指数退避重试 + 死信、**金丝雀发布（5%→25%→100%）**、Trivy / Bandit / Semgrep 安全扫描 |

## 系统架构

```
                     ┌─────────────────────────────┐
                     │  前端 Vue 3 + TS + Element Plus │
                     │  交易监控 · 规则管理 · 案件中心   │
                     │  团伙图谱(vis-network) · 模型治理 │
                     └──────────────┬──────────────┘
                                    │ REST / SSE / WS
┌───────────────────────────────────▼────────────────────────────┐
│  FRD Backend (FastAPI, :8002)                                    │
│  · 双轨评分: 规则引擎 DSL ‖ ML 引擎 (并行)                        │
│  · 多租户隔离 · RBAC · 限流 · 审计(哈希链) · 请求追踪              │
│  · 案件自动生成 · PIPL 合规流程 · Webhook 签名与重试               │
│  · Celery Worker/Beat (评分 / SHAP / 漂移 / 归档)                │
└────────┬────────────────────────────┬───────────────────────────┘
         │                            │
┌────────▼────────┐          ┌────────▼─────────┐
│  ML Service :8501│          │  GNN Service :8502│
│  XGBoost · BERT   │          │  GraphSAGE · Louvain │
│  1D-CNN · SHAP    │          │  Neo4j k-hop 子图     │
│  漂移检测 · 熔断    │          │  团伙识别 · 图嵌入      │
└────────┬────────┘          └────────┬─────────┘
         │                            │
┌────────▼────────────────────────────▼─────────┐
│  PostgreSQL(15/TimescaleDB) · Redis(7) · Neo4j(5) │
│  Prometheus · Grafana · 日志(JSON) · 健康检查         │
└─────────────────────────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 · Celery 5 · structlog |
| 数据库 | PostgreSQL 15 + TimescaleDB · Redis 7 · Neo4j 5 + APOC |
| ML | XGBoost 2.1 · PyTorch · Transformers (BERT) · scikit-learn · SHAP |
| GNN | PyTorch Geometric · networkx Louvain |
| 前端 | Vue 3.5 + TS 5.6 · Vite 6 · Element Plus · ECharts · vis-network · Pinia · PWA |
| DevOps | Docker Compose (10 服务) · Helm ×3 · Terraform (ACK/RDS/Redis) · GitHub Actions · ArgoCD · Trivy/Cosign |

## 目录结构

```
backend/    FastAPI 服务（api / services / models / core / workers / alembic）
ml/         独立 ML 评分服务 :8501（scoring / training / drift）
gnn/        独立图服务 :8502（GraphSAGE / Louvain / 图构建）
frontend/   Vue 3 前端（16 个视图，按 7 角色路由守卫）
infra/      Helm charts · Terraform (Aliyun ACK) · Prometheus
docs/       完整文档体系 D01-D11（立项→需求→架构→DB→API→手册→测试→进度→风险→部署→验收）
```

## 快速开始

```bash
docker compose up -d --build          # 一键启动全部 10 个服务
# 后端 API 文档: http://localhost:8002/docs
# 前端:          http://localhost:5174
# Grafana:       http://localhost:3001 · Prometheus: http://localhost:9091
```

后端单独开发：

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8002
```

## 测试与质量

| 模块 | 覆盖内容 |
|---|---|
| 后端 pytest（42 用例） | 规则引擎 DSL 解析器（13）、评分链路（9）、Kill Switch（8）、漂移检测（7）、健康检查（5） |
| ML pytest（10 用例） | 多模态引擎熔断与降级、各模态评分正确性 |
| GNN pytest（5 用例） | k-hop 子图、图嵌入、社区检测 |
| 前端 vitest | 格式化工具断言（16） |

CI 四阶段流水线（`ci.yml` / `security-scan.yml` / `build-images.yml` / `deploy-staging.yml`）：

1. **质量门禁** — ruff + mypy + ESLint + 全量测试 + 前端类型检查与构建
2. **安全扫描** — Trivy 镜像漏洞、Bandit 静态分析、Semgrep SAST、依赖漏洞检查（每周一 + 每次 PR）
3. **镜像发布** — 打 tag 自动构建 5 个镜像（backend / worker / frontend / ml / gnn），Trivy 拦截 HIGH/CRITICAL，Cosign 签名推送
4. **金丝雀部署** — 推送 main 自动同步至 Staging，5% → 25% → 100% 逐步放量

## 文档体系

遵循完整软件工程生命周期，docs/ 下含 **D01-D11 共 11 份文档**（立项 / 需求 SRS / 架构 SAD / 数据库 / API 规范 / 用户手册 / 测试计划 / 进度 / 风险 / 部署 / 验收），全部基于跨文档修订基线（单一事实源）。见 [docs/README.md](docs/README.md)。

## 联系方式

- 作者：邝振华 · GitHub：[kajykk](https://github.com/kajykk)
- 邮箱：1754902912@qq.com
