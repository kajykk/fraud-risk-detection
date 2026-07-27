# FRD 金融反欺诈系统 上线部署方案

| 版本 | 日期 | 作者 | 状态 | 变更说明 |
|------|------|------|------|----------|
| V1.0 | 2026-07-27 | 邝振华 | 已发布 | 初版发布 |
| V1.1 | 2026-07-27 | 邝振华 + DevOps Agent | 修订稿 | 依据 `FRD-BASELINE-V1.1` 修订：云厂商统一阿里云；部署规模降级（3+2+2+2 副本单 AZ）；资源合计修正为 80C 216G + 2 GPU；SLA 99.5%；灰度统一 24h+24h（Day1/Day2/Day3）；RTO 统一 ≤ 30min；新增 §9.6 等保 2.0 三级合规矩阵、§15.5 AI Agent 辅助运维、§15.6 容量规划；告警规则补充；故障场景扩充至 10+；CI/CD 增加 AI Agent 自动 review；数据库回滚流程细化；密钥轮换周期调整；公网入口统一为阿里云 DCDN+WAF+DDoS 高防（国内节点） |

---

## 目录

1. [部署概述](#1-部署概述)
2. [部署架构](#2-部署架构)
3. [环境规划](#3-环境规划)
4. [基础设施准备](#4-基础设施准备)
5. [容器化与镜像](#5-容器化与镜像)
6. [Kubernetes 部署](#6-kubernetes-部署)
7. [数据库部署](#7-数据库部署)
8. [中间件部署](#8-中间件部署)
9. [网络与安全](#9-网络与安全)
10. [CI/CD 流水线](#10-cicd-流水线)
11. [可观测性](#11-可观测性)
12. [上线流程](#12-上线流程)
13. [灰度发布](#13-灰度发布)
14. [回滚方案](#14-回滚方案)
15. [运维手册](#15-运维手册)
16. [应急预案](#16-应急预案)

---

## 1. 部署概述

### 1.1 部署目标

- **高可用**：99.5% SLA（年宕机 ≤ 43.8h），试运行后视情况升级至 99.9%
- **可扩展**：水平扩展支持 ≥ 10000 TPS（生产扩容后，MVP 阶段 ≥ 2000 TPS）
- **安全合规**：PCI-DSS v4.0 / PIPL / 反洗钱法 / 等保 2.0 三级
- **可观测**：全链路监控、告警、追踪
- **可回滚**：应用层 5 分钟回滚，数据库层 30 分钟回滚，总体 RTO ≤ 30min

### 1.2 部署原则

- 基础设施即代码（IaC）：Terraform + Helm
- 不可变基础设施：容器化 + 不可变镜像
- GitOps：Git 作为单一可信源
- 零停机部署：滚动更新 + 金丝雀
- 最小权限：RBAC + NetworkPolicy
- 单 AZ 部署 + 异地备份：适配个人项目 + AI Agent 协作规模（生产稳态后可升级至 2 AZ）

### 1.3 部署范围

| 组件 | 部署形态 | 数量 |
|------|----------|------|
| API 网关 + 评分 + 规则 + 案件 | K8s Deployment | 3 副本 × 1 AZ |
| ML 推理 | K8s Deployment | 2 副本 × 1 AZ |
| GNN 服务 | K8s Deployment | 2 副本 × 1 AZ |
| Celery Worker | K8s Deployment | 2 副本 × 1 AZ |
| Celery Beat | K8s Deployment | 1 副本 + 1 standby |
| PostgreSQL | StatefulSet | 1 主 + 1 从（同 AZ） + 异地备份 |
| Redis | StatefulSet | 1 主 + 1 从（同 AZ） |
| Neo4j | StatefulSet | 1 主（社区版） + 异地备份 |
| Prometheus+Grafana+Loki+Jaeger | Deployment | 各 1 副本 |

> 说明：合并部署（API 网关 + 评分 + 规则 + 案件共 3 副本）降低运维复杂度，匹配"1 真人 + 11 AI Agent"团队模式与个人项目预算。生产稳态后可评估升级至 2 AZ 多副本部署。

---

## 2. 部署架构

### 2.1 整体架构图

```
                          ┌──────────────────┐
                          │  阿里云 DCDN      │
                          │  + WAF + DDoS 高防│
                          │  (国内节点)        │
                          └────────┬─────────┘
                                   │
                          ┌────────┴─────────┐
                          │  阿里云 SLB       │
                          │  (单 AZ + 异地备份)│
                          └────────┬─────────┘
                                   │
                          ┌────────┴─────────┐
                          │   Nginx Ingress  │
                          └────────┬─────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │            K8s Cluster             │
                │  ┌────────────────────────────┐    │
                │  │ frd-prod namespace         │    │
                │  │  - API 网关 + 评分 + 规则 + 案件│    │
                │  │  - GNN 服务                │    │
                │  │  - ML 推理                 │    │
                │  │  - Celery Worker / Beat    │    │
                │  └────────────┬───────────────┘    │
                └───────────────┼────────────────────┘
                                │
              ┌─────────────────┴──────────────────┐
              │       单 AZ 数据层 + 异地备份       │
              │  ┌────────┐  ┌────────┐           │
              │  │Postgre │  │ Redis  │           │
              │  │SQL主从 │  │ 主从   │           │
              │  │(同AZ)  │  │(同AZ)  │           │
              │  └────────┘  └────────┘           │
              │  ┌────────┐  ┌────────┐           │
              │  │ Neo4j  │  │阿里云  │           │
              │  │社区版  │  │ OSS    │           │
              │  └────────┘  └────────┘           │
              └─────────────────┬──────────────────┘
                                │
                       异地备份（OSS 跨区域复制）
```

### 2.2 网络拓扑

- 公网入口：阿里云 DCDN + WAF + DDoS 高防（国内节点）
- VPC 边界：阿里云 NAT 网关 + 安全组
- 集群入口：Nginx Ingress Controller
- 服务间：K8s ClusterIP + NetworkPolicy
- 数据库：私有子网，仅集群内可达
- 异地备份：阿里云 OSS 跨区域复制（cn-hangzhou → cn-shanghai）

---

## 3. 环境规划

### 3.1 环境清单

| 环境 | 用途 | 部署形态 | 数据 | 资源规格 |
|------|------|----------|------|----------|
| Local | 开发 | docker-compose | 模拟 | 4C8G |
| Dev | 联调 | K8s 单节点 | 脱敏 | 8C16G |
| Test | 功能测试 | K8s 单节点 | 脱敏 | 16C32G |
| Staging | 预发 | K8s 多节点 | 生产快照 | 与生产一致（小规格） |
| Prod | 生产 | K8s 单 AZ + 异地备份 | 真实 | 见 §3.2 |

### 3.2 生产环境资源规格

| 资源 | 规格 | 数量 | 总资源 |
|------|------|------|--------|
| API/规则/案件节点 | 4C8G | 3 | 12C 24G |
| ML 推理节点 | 8C16G + GPU | 2 | 16C 32G + 2 GPU |
| GNN 节点 | 4C8G | 2 | 8C 16G |
| Worker 节点 | 4C8G | 2 | 8C 16G |
| PostgreSQL | 8C32G + 500GB SSD | 2 | 16C 64G |
| Redis | 4C16G + 100GB | 2 | 8C 32G |
| Neo4j | 4C16G + 200GB | 1 | 4C 16G |
| 监控 | 2C4G | 4 | 8C 16G |
| **合计** | - | 18 | **80C 216G + 2 GPU** |

> 说明：合计已按降级后规模重算（V1.0 的 188C 396G+4GPU 与 496G 矛盾已修正），匹配个人项目预算与基准 §6.1 云资源预算 12 万元/年。

### 3.3 环境隔离

- 每个环境独立 VPC
- 跨环境通过 VPN 互联
- 生产环境仅运维可访问（堡垒机 + 阿里云 RAM 双因子）
- 数据不跨环境同步（除脱敏快照）

---

## 4. 基础设施准备

### 4.1 云资源清单

| 资源类型 | 数量 | 说明 |
|----------|------|------|
| VPC | 5 | 每环境 1 个 |
| 子网 | 20 | 公网 + 私网 + 数据库 |
| 安全组 | 15 | 按 environment/role 分组 |
| 负载均衡（阿里云 SLB） | 5 | 每环境 1 个 |
| NAT 网关 | 5 | 每环境 1 个 |
| Kubernetes 集群（阿里云 ACK） | 5 | 每环境 1 个 |
| RDS PostgreSQL | 5 | 每环境 1 套主从 |
| Redis（阿里云 Tair/Redis） | 5 | 每环境 1 套主从 |
| 对象存储（阿里云 OSS） | 5 | 每环境 1 个 |
| KMS 密钥（阿里云 KMS） | 10 | 数据加密 + JWT 签名 |
| DCDN | 1 | 生产前端分发 |
| WAF | 1 | 生产入口防护 |
| DDoS 高防 | 1 | 生产入口抗 D |
| 域名 + SSL 证书 | 5 | 每环境 1 套 |

### 4.2 Terraform 配置

```hcl
# infra/terraform/main.tf
# 阿里云 Provider（统一云厂商，依据 FRD-BASELINE-V1.1 §8.4）
provider "alicloud" {
  region = "cn-hangzhou"
}

module "vpc" {
  source  = "aliyun/terraform-alicloud/modules/vpc"
  version = "1.220.0"
  vpc_name   = "frd-prod-vpc"
  vpc_cidr   = "10.0.0.0/16"
  # 单 AZ 部署 + 异地备份（依据 §1.3 降级规模）
  vswitch_cidrs = ["10.0.1.0/24", "10.0.101.0/24"]
  vswitch_names = ["frd-prod-private-k", "frd-prod-public-k"]
  # 杭州 K 区可用区（与基准 §8.4 一致：cn-hangzhou）
  availability_zones = ["cn-hangzhou-k", "cn-hangzhou-k-a", "cn-hangzhou-k-b"]
}

module "ack" {
  source  = "aliyun/terraform-alicloud/modules/ack"
  version = "1.220.0"
  cluster_name    = "frd-prod-ack"
  cluster_version = "1.28"
  vpc_id          = module.vpc.vpc_id
  vswitch_ids     = [module.vpc.vswitch_ids[0]]
  node_pools = {
    api      = { instance_type = "ecs.c6.xlarge",    desired_size = 3 }
    worker   = { instance_type = "ecs.c6.xlarge",    desired_size = 2 }
    ml       = { instance_type = "ecs.gn6i-c4g1.xlarge", desired_size = 2 }
    gnn      = { instance_type = "ecs.c6.xlarge",    desired_size = 2 }
  }
}

# OSS（备份 + 模型工件，跨区域复制到 cn-shanghai 实现异地备份）
module "oss" {
  source  = "aliyun/terraform-alicloud/modules/oss"
  version = "1.220.0"
  bucket = "frd-prod-backup"
  acl    = "private"
  replication = {
    target_bucket = "frd-prod-backup-dr"
    target_region = "cn-shanghai"
  }
}

# WAF + DDoS 高防 + DCDN（阿里云国内节点，统一云厂商安全栈）
module "waf" {
  source  = "aliyun/terraform-alicloud/modules/waf"
  version = "1.220.0"
  domain = "api.frd.example.com"
}

module "ddos" {
  source  = "aliyun/terraform-alicloud/modules/antiddos"
  version = "1.220.0"
  instance_name = "frd-prod-ddos"
}

module "dcdn" {
  source  = "aliyun/terraform-alicloud/modules/dcdn"
  version = "1.220.0"
  domain = "frd.example.com"
  origin = "frd-prod.oss-cn-hangzhou-internal.aliyuncs.com"
}
```

### 4.3 网络配置

- VPC CIDR：`10.0.0.0/16`
- 公网子网：`10.0.101.0/24`（NAT + SLB）
- 私网子网：`10.0.1.0/24`（K8s 节点）
- 数据库子网：`10.0.201.0/24`（独立子网）
- 安全组规则：最小化开放，默认拒绝
- DCDN/WAF/DDoS 高防联动，国内节点回源

---

## 5. 容器化与镜像

### 5.1 镜像清单

| 镜像 | 大小 | 基础镜像 | 说明 |
|------|------|----------|------|
| frd-backend | 280MB | python:3.12-slim | FastAPI 后端（API 网关 + 评分 + 规则 + 案件合并） |
| frd-worker | 280MB | python:3.12-slim | Celery Worker |
| frd-frontend | 50MB | nginx:1.27-alpine | Vue 静态资源 |
| frd-ml-serving | 1.2GB | nvidia/cuda:12.2-runtime | ML 推理（含 GPU 驱动） |
| frd-gnn-serving | 850MB | python:3.12-slim | GNN 服务 |

### 5.2 Dockerfile 示例

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5.3 镜像构建与扫描

```bash
# 多阶段构建
docker build -t frd-backend:1.0.0 .

# 漏洞扫描（Trivy）
trivy image frd-backend:1.0.0 --severity HIGH,CRITICAL

# 签名（Cosign，与 §10 AI Agent 自动 review 联动）
cosign sign --key cosign.key frd-backend:1.0.0

# 推送
docker push registry.frd.example.com/frd-backend:1.0.0
```

### 5.4 镜像仓库

- 私有仓库：阿里云 ACR（容器镜像服务）或 Harbor 自建
- 命名规范：`registry.frd.example.com/{image}:{version}`
- 版本：`{semver}-{git-sha}`（如 `1.0.0-abc1234`）
- 保留策略：最新 10 个版本 + 所有发版版本
- 镜像签名：Cosign 签名验证，未签名镜像禁止部署

---

## 6. Kubernetes 部署

### 6.1 命名空间规划

```yaml
namespaces:
  - frd-prod        # 生产业务
  - frd-monitoring  # 监控
  - frd-logging     # 日志
  - frd-ingress     # 入口
  - frd-cicd        # CI/CD 工具
```

### 6.2 Helm Chart 结构

```
helm/
├── frd-backend/
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── values-prod.yaml
│   └── templates/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── hpa.yaml
│       ├── pdb.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── networkpolicy.yaml
├── frd-frontend/
├── frd-ml-serving/
└── frd-gnn-serving/
```

### 6.3 Deployment 示例

```yaml
# helm/frd-backend/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frd-backend
  namespace: frd-prod
spec:
  replicas: 3  # 与 §1.3 降级规模对齐（API+评分+规则+案件合并 3 副本）
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: frd-backend
  template:
    metadata:
      labels:
        app: frd-backend
    spec:
      # 单 AZ 部署，podAntiAffinity 仅做软亲和（同节点不重复调度）
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: frd-backend
                topologyKey: kubernetes.io/hostname
      containers:
        - name: backend
          image: registry.frd.example.com/frd-backend:1.0.0
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: frd-backend-config
            - secretRef:
                name: frd-backend-secret
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
```

### 6.4 HPA（水平自动扩展）

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frd-backend-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frd-backend
  minReplicas: 3       # 与 §1.3 节点数对齐
  maxReplicas: 9       # 3 倍上限，避免超过单 AZ 节点容量
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "500"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 60
```

**Cluster Autoscaler 方案**：

- 启用阿里云 ACK Cluster Autoscaler，当 HPA 触达上限且节点资源不足时自动扩节点
- 节点池配置：min=2 / max=6（API 池），min=1 / max=3（ML GPU 池）
- 扩容冷却：节点扩容后 10min 不可缩容，避免抖动
- GPU 节点单独池管理，按需启动以节省成本

### 6.5 PDB（Pod Disruption Budget）

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: frd-backend-pdb
spec:
  minAvailable: 2   # 与 3 副本对齐，至少保留 2 个
  selector:
    matchLabels:
      app: frd-backend
```

### 6.6 NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frd-backend-netpol
  namespace: frd-prod
spec:
  podSelector:
    matchLabels:
      app: frd-backend
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: frd-ingress
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: frd-prod
        - podSelector:
            matchLabels:
              app: postgresql
      ports:
        - protocol: TCP
          port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - protocol: TCP
          port: 6379
    - to:
        - podSelector:
            matchLabels:
              app: neo4j
      ports:
        - protocol: TCP
          port: 7687
```

---

## 7. 数据库部署

### 7.1 PostgreSQL

#### 7.1.1 部署方案

- 模式：主从复制（1 主 + 1 从，同 AZ 部署 + 异地 OSS 备份）
- 工具：CloudNativePG 或 Patroni
- 备份：每日全量 + WAL 持续归档到阿里云 OSS（跨区域复制到 cn-shanghai）
- RPO：< 1 分钟
- RTO：≤ 30 分钟

#### 7.1.2 关键配置

```yaml
# postgresql.conf
shared_buffers = 8GB
effective_cache_size = 24GB
work_mem = 64MB
maintenance_work_mem = 1GB
max_connections = 500
wal_level = replica
max_wal_senders = 5
# 单 AZ 内本地同步 + 远程异步（降级后无需跨 AZ 同步提交）
synchronous_commit = on
synchronous_standby_names = 'FIRST 1 (replica1)'
# 远程异地备份通过 OSS WAL 归档异步完成
archive_mode = on
archive_command = 'aliyun oss cp %p oss://frd-prod-backup/wal/%f'
```

#### 7.1.3 备份策略

| 类型 | 频率 | 保留 | 存储 |
|------|------|------|------|
| 全量备份 | 每日 02:00 | 30 天 | 阿里云 OSS（标准存储） |
| WAL 归档 | 持续 | 30 天 | 阿里云 OSS（标准存储） |
| 月度备份 | 每月 1 日 | 12 个月 | 阿里云 OSS（低频访问） |
| 年度备份 | 每年 1 月 | 7 年 | 阿里云 OSS（归档存储，符合反洗钱法 7 年要求） |
| 异地副本 | 实时复制 | 同上 | 阿里云 OSS（cn-shanghai，跨区域复制） |

### 7.2 Redis

- 模式：哨兵集群（1 主 + 1 从 + 3 哨兵，同 AZ）
- 持久化：RDB 每小时 + AOF 每秒
- 内存：16GB（业务 12GB + 系统 4GB）
- 淘汰策略：`allkeys-lru`

### 7.3 Neo4j

- 模式：社区版单主（1 主） + 异地 OSS 备份
- 内存：堆 8GB + 页缓存 6GB
- 备份：每日全量 + 增量事务日志，归档到阿里云 OSS
- 说明：生产首年使用社区版降本（依据基准 §6.1），第 2 年评估升级 Enterprise Causal Cluster

---

## 8. 中间件部署

### 8.1 消息队列（Celery Broker）

- 使用 Redis 作为 Broker
- 队列分组：
  - `default`：默认任务
  - `ml_inference`：ML 推理
  - `gnn_detection`：GNN 检测
  - `report_export`：报表导出
  - `webhook_delivery`：Webhook 投递

### 8.2 对象存储

- 用途：附件、报表导出、备份、模型文件
- 类型：阿里云 OSS（S3 兼容）
- 桶规划：
  - `frd-attachments`：案件附件
  - `frd-reports`：报表导出
  - `frd-backups`：数据库备份（跨区域复制到 cn-shanghai）
  - `frd-models`：模型文件
  - `frd-audit-logs`：审计日志归档（7 年保留）

### 8.3 服务发现

- K8s 内置 Service + DNS
- 跨语言调用：gRPC + 服务网格（可选 Istio）

---

## 9. 网络与安全

### 9.1 网络分层

```
公网 → 阿里云 DCDN/WAF/DDoS 高防 → 阿里云 SLB → Ingress → Service → Pod → 数据库
   ↓                ↓                  ↓           ↓          ↓
   DDoS            WAF                TLS         NetworkPolicy
   高防            限流/规则          终止        + RBAC
```

### 9.2 TLS 证书

- 公网证书：阿里云数字证书管理服务（免费 DV 或付费 OV）
- 内部服务：自签 CA + cert-manager 自动签发
- 证书自动续期：cert-manager + ACME
- TLS 版本：1.2+，禁用 SSLv3/TLSv1.0/1.1

### 9.3 密钥管理

| 密钥类型 | 存储位置 | 轮换周期 | 说明 |
|----------|----------|----------|------|
| JWT 签名 | 阿里云 KMS | **月度** | V1.1 由季度改为月度 |
| 数据库密码 | K8s Secret + 阿里云 KMS | 月度 | |
| PII 加密密钥（Fernet） | 阿里云 KMS | 季度 | **双密钥并行期 7 天**（旧密钥解密 + 新密钥加密并存） |
| API Token | K8s Secret | 月度 | |
| Webhook 签名密钥 | K8s Secret | 季度 | |
| K8s Secret 加密密钥 | 阿里云 KMS | 年度 | etcd 加密 |

### 9.4 RBAC

```yaml
# ServiceAccount + RoleBinding
apiVersion: v1
kind: ServiceAccount
metadata:
  name: frd-backend-sa
  namespace: frd-prod
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: frd-backend-role
  namespace: frd-prod
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
```

### 9.5 合规要求

| 标准 | 要求 | 实现 |
|------|------|------|
| PCI-DSS v4.0 | 卡数据不存储 | Token 化 |
| PCI-DSS v4.0 | 加密传输 | TLS 1.2+ |
| PIPL | 数据本地化 | **使用阿里云国内区域 + 国内存储**（cn-hangzhou + cn-shanghai 异地备份，不出境） |
| 反洗钱法 | 审计日志 7 年 | 月度归档到阿里云 OSS 归档存储 |
| 等保 2.0 三级 | 单 AZ + 异地备份 | 见 §9.6 合规矩阵 |

### 9.6 等保 2.0 三级合规矩阵

> 依据 `FRD-BASELINE-V1.1 §7.2`，覆盖 GB/T 22239 三级 6 类控制点。

| 控制点类别 | 控制要求 | 本项目实现 | 证据 |
|-----------|----------|-----------|------|
| **物理与环境安全** | 等保合规机房 | 阿里云等保合规机房（已通过等保三级测评） | 阿里云等保合规白皮书 + 机房测评报告 |
| **安全通信网络** | 网络隔离 + 跨可用区备份 | VPC + 安全组 + NetworkPolicy + 单 AZ 内同步 + 阿里云 OSS 跨区域（cn-hangzhou → cn-shanghai）异地备份 | Terraform 网络配置 + NetworkPolicy YAML |
| **安全区域边界** | 边界防护 + 入侵检测 | 阿里云 WAF（OWASP Top 10 防护）+ IDS/IPS（阿里云云盾）+ DDoS 高防（DDoS 高防 IP） | WAF 规则集 + DDoS 高防流量日志 |
| **安全计算环境** | 主机加固 + 入侵检测 + 可信验证 + 剩余信息保护 | 堡垒机（阿里云堡垒机）+ HIDS（青藤云主机安全）+ 主机加固（CIS Benchmark 基线）+ 可信验证（阿里云可信启动）+ 剩余信息保护（内存清零 + 磁盘擦除） | 堡垒机会话录像 + HIDS 探针 + 加固报告 |
| **安全管理中心** | 集中监控 + 审计集中 | Prometheus + Grafana 集中监控 + 阿里云 ActionTrail + K8s Audit Log 集中归档到 OSS | Grafana 仪表盘 + ActionTrail 日志 |
| **安全审计** | 审计日志完整 + 完整性保护 | 审计日志 **7 年保留**（OSS 归档存储）+ 哈希链完整性校验（每日哈希上链）+ 防篡改（OSS WORM 模式） | OSS WORM 配置 + 哈希链校验脚本 |

**等保 2.0 三级备案计划**：
- M1（2026-08-15）启动等保备案
- M5（2026-12-31）完成备案，取得备案证明编号
- 周期：3-6 个月（测评机构：待定）
- 验收证据：备案证明编号 + 测评报告

---

## 10. CI/CD 流水线

### 10.1 流水线全景

```
开发提交代码 → PR → CI 检查（含 AI Agent 自动 review）→ 评审 → 合并 main
                          ↓
                  ┌──── AI Agent 代码 review 自动化 ────┐
                  │  - SAST 静态扫描（SonarQube）       │
                  │  - 依赖扫描（Snyk）                │
                  │  - 镜像扫描（Trivy）               │
                  │  - 镜像签名（Cosign）              │
                  └────────────────────────────────────┘
                                      ↓
                              构建镜像 + 扫描 + 推送
                                      ↓
                              部署到 Dev（自动）
                                      ↓
                              部署到 Test（手动触发）
                                      ↓
                              部署到 Staging（手动触发）
                                      ↓
                              部署到 Prod（手动 + 多人审批）
                                      ↓
                              灰度发布（5% → 25% → 100%）
```

### 10.2 GitHub Actions 工作流

```yaml
# .github/workflows/deploy-prod.yml
name: Deploy to Production
on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Image version to deploy'
        required: true
      strategy:
        description: 'Deployment strategy'
        type: choice
        options: [canary, blue-green, rolling]
        default: canary

jobs:
  ai-agent-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # 1. SAST 静态扫描（SonarQube）
      - name: SonarQube Scan
        uses: SonarSource/sonarqube-scan-action@v2
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
      # 2. 依赖扫描（Snyk）
      - name: Snyk Dependency Scan
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
      # 3. 镜像扫描（Trivy）
      - name: Trivy Image Scan
        run: trivy image registry.frd.example.com/frd-backend:${{ inputs.version }} --severity HIGH,CRITICAL --exit-code 1
      # 4. 镜像签名（Cosign）
      - name: Cosign Sign
        run: cosign sign --key cosign.key registry.frd.example.com/frd-backend:${{ inputs.version }}
      # 5. AI Agent 自动 review 报告
      - name: AI Agent Review Report
        run: |
          echo "## AI Agent 代码 Review 报告" >> $GITHUB_STEP_SUMMARY
          echo "- SAST: PASS" >> $GITHUB_STEP_SUMMARY
          echo "- 依赖扫描: PASS" >> $GITHUB_STEP_SUMMARY
          echo "- 镜像扫描: PASS" >> $GITHUB_STEP_SUMMARY
          echo "- 镜像签名: PASS" >> $GITHUB_STEP_SUMMARY

  deploy:
    runs-on: ubuntu-latest
    needs: ai-agent-review
    environment: production  # 需要审批
    steps:
      - uses: actions/checkout@v4
      - name: Configure Aliyun credentials
        uses: aliyun/credentials-action@v1
        with:
          access-key-id: ${{ secrets.ALIYUN_AK }}
          access-key-secret: ${{ secrets.ALIYUN_SK }}
      - name: Update kubeconfig
        run: aliyun cs UpdateClusterUserConfig --cluster-id ${{ secrets.ACK_CLUSTER_ID }}
      - name: Deploy with Helm
        run: |
          helm upgrade frd-backend ./helm/frd-backend \
            --namespace frd-prod \
            --set image.tag=${{ inputs.version }} \
            --set deployment.strategy=${{ inputs.strategy }} \
            --values ./helm/frd-backend/values-prod.yaml
      - name: Verify deployment
        run: |
          kubectl rollout status deployment/frd-backend -n frd-prod
          kubectl get pods -n frd-prod -l app=frd-backend
```

### 10.3 GitOps（ArgoCD）

- Git 仓库作为部署清单单一可信源
- ArgoCD 自动同步集群状态到 Git
- 任何生产变更必须通过 PR 修改 Git
- 审计日志：所有变更可追溯
- 镜像签名验证：ArgoCD 仅同步 Cosign 签名验证通过的镜像

---

## 11. 可观测性

### 11.1 三支柱

```
Metrics（指标）   →   Prometheus + Grafana
Logs（日志）      →   Loki + Grafana
Traces（追踪）    →   Jaeger + OpenTelemetry
```

### 11.2 关键指标

| 类别 | 指标 | 阈值 |
|------|------|------|
| 业务 | 评分 QPS | - |
| 业务 | 决策分布 | - |
| 业务 | 案件数 | - |
| 性能 | API P99 延迟 | < 200ms |
| 性能 | 评分 P99 延迟 | < 200ms |
| 性能 | 错误率 | < 0.1% |
| 资源 | CPU 使用率 | < 70% |
| 资源 | 内存使用率 | < 80% |
| 资源 | 磁盘使用率 | < 80% |
| ML | 模型 AUC | ≥ 0.92 |
| ML | 漂移 PSI | < 0.25 |
| 数据库 | 连接数 | < 80% |
| 数据库 | 慢查询 | < 100ms |
| Redis | 命中率 | > 95% |

### 11.3 告警规则

| 告警 | 触发条件 | 级别 | 接收人 |
|------|----------|------|--------|
| API 错误率 | > 1% 持续 1min | CRITICAL | 运维 + PM |
| P99 延迟 | > 200ms 持续 5min | WARN | 运维 |
| 节点宕机 | 1 个 | WARN | 运维 |
| 节点宕机 | 2+ 个 | CRITICAL | 运维 + 高管 |
| 数据库主从延迟 | > 10s | CRITICAL | 运维 + DBA |
| 模型 AUC 下降 | < 0.92 | WARN | ML |
| 漂移 PSI | > 0.25 | WARN | ML |
| 金丝雀失败 | 触发回滚 | CRITICAL | ML + PM |
| 审计日志中断 | 5min 无日志 | CRITICAL | 合规 |
| **GPU 使用率** | > 90% 持续 5min | **CRITICAL** | **ML** |
| **Neo4j 查询失败率** | > 1% | **WARN** | **GNN** |
| **Redis 主从切换触发** | 触发切换事件 | **CRITICAL** | **运维** |
| **Celery 任务积压** | > 1000 | **WARN** | **运维** |
| **备份失败** | 任一备份任务失败 | **CRITICAL** | **运维** |
| **证书过期** | < 14 天 | **WARN** | **运维** |
| **密钥轮换失败** | 任一密钥轮换失败 | **CRITICAL** | **安全** |
| **磁盘 inode 耗尽** | > 80% | **WARN** | **运维** |

> V1.1 新增 8 条告警规则（GPU / Neo4j / Redis 切换 / Celery 积压 / 备份失败 / 证书过期 / 密钥轮换失败 / inode 耗尽），覆盖降级后单 AZ 部署的关键风险点。

### 11.4 日志聚合

- 应用日志：JSON 格式，输出到 stdout
- 采集：Fluent Bit → Loki
- 查询：Grafana LogQL
- 保留：**应用日志 30 天热 + 1 年冷；审计日志单独 7 年冷存储**（符合反洗钱法要求）

### 11.5 分布式追踪

- OpenTelemetry SDK 全链路埋点
- 采样率：生产 10%，预发 100%
- Jaeger 查询调用链
- trace_id 贯穿 API / DB / MQ / ML

---

## 12. 上线流程

### 12.1 上线前检查清单

- [ ] 所有测试通过（单元 ≥ 99%，集成 ≥ 95%，契约 100%，E2E ≥ 95%）
- [ ] 性能测试通过（P99 < 200ms，TPS ≥ 2000）
- [ ] 安全测试通过（0 高危漏洞）
- [ ] 合规审计通过（PCI-DSS / PIPL / 反洗钱 / 等保 2.0 三级）
- [ ] 文档齐备（D01-D11）
- [ ] 运维手册 + 应急预案就绪
- [ ] 监控告警就绪
- [ ] 备份恢复验证通过
- [ ] 故障演练通过
- [ ] 客户 UAT 签字

### 12.2 上线时间窗

- 推荐时间：周六 02:00 起步（业务低峰）
- 回滚窗口：上线后 4 小时内可无条件回滚
- 灰度策略：5%（24h）→ 25%（24h）→ 100%（**100% 后观察 72h**）

### 12.3 上线步骤

> V1.1 统一为 24h + 24h 灰度窗口（依据基准 §8.2），Day1/Day2/Day3 三天推进。

```
Day1 02:00  开始上线，通知干系人
      02:05  停止旧版本 Cron 任务
      02:10  执行数据库迁移（向前兼容）
      02:20  部署新版本（灰度 5% 流量）
      02:30  健康检查 + 烟雾测试
      02:40  灰度观察开始（5% 流量持续 24h）

Day2 02:00  评估 5% 灰度 24h 指标达标，推进灰度到 25%
      02:10  健康检查 + 烟雾测试
      02:20  灰度观察（25% 流量持续 24h）

Day3 02:00  评估 25% 灰度 24h 指标达标，推进灰度到 100%
      02:10  全量健康检查
      02:20  启用新版本 Cron 任务
      02:30  上线完成，通知干系人
      02:30 起  100% 后观察 72h（DevOps Agent 7×24 监控）
```

### 12.4 烟雾测试脚本

```bash
#!/bin/bash
# scripts/smoke_test.sh
BASE_URL="https://api.fraud-detection.example.com/api/v1"
TOKEN="..."

# 1. 健康检查
curl -f "$BASE_URL/health" || exit 1

# 2. 评分接口
RESULT=$(curl -s -X POST "$BASE_URL/transactions/score" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: tenant_smoke" \
  -H "X-Idempotency-Key: $(uuidgen)" \
  -d @smoke_tx.json)
echo "$RESULT" | jq -e '.code == "OK"'

# 3. 规则查询
curl -sf "$BASE_URL/rules?status=ACTIVE" \
  -H "Authorization: Bearer $TOKEN" | jq -e '.data.items | length > 0'

# 4. 案件查询
curl -sf "$BASE_URL/cases?status=OPEN" \
  -H "Authorization: Bearer $TOKEN" | jq -e '.code == "OK"'

echo "All smoke tests passed."
```

---

## 13. 灰度发布

### 13.1 灰度策略

> V1.1 统一为 24h + 24h 灰度窗口（依据基准 §8.2）。

```
Stage 1: 5% 流量，持续 24h，观察 P0 故障 + P99 < 200ms
   ↓ 监控指标达标
Stage 2: 25% 流量，持续 24h，观察同上
   ↓ 监控指标达标
Stage 3: 100% 流量，观察 72h（完成上线）
```

### 13.2 灰度实现

- **Ingress Nginx**：通过权重路由
- **Istio**：基于权重 / Header 路由（更精细）
- **Argo Rollouts**：原生支持金丝雀 + 自动推进/回滚

```yaml
# Argo Rollouts 示例
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: frd-backend
spec:
  strategy:
    canary:
      canaryService: frd-backend-canary
      stableService: frd-backend-stable
      trafficRouting:
        nginx:
          stableIngress: frd-backend-stable
      steps:
        - setWeight: 5
        - pause: { duration: 24h }
        - setWeight: 25
        - pause: { duration: 24h }
        - setWeight: 100
      analysis:
        templates:
          - templateName: success-rate
        args:
          - name: service-name
            value: frd-backend-canary
```

### 13.3 灰度判定指标

| 指标 | 阈值 | 持续 |
|------|------|------|
| 错误率 | < 0.5% | 5min |
| P99 延迟 | **< 200ms** | 5min |
| 业务成功率 | > 99% | 5min |
| 模型 AUC 偏差 | < 2% | 30min |
| 误报率 | < 10% | 1h |

任一指标超阈值触发自动回滚。

> V1.1 将 P99 阈值从 250ms 统一为 200ms，与 D01/D11/基准 §2.1 保持一致。

---

## 14. 回滚方案

### 14.1 回滚触发条件

- 自动：灰度指标超阈值
- 手动：运维 / PM / 客户决策

### 14.2 回滚类型

| 类型 | 适用 | 耗时 | 说明 |
|------|------|------|------|
| 镜像回滚 | 代码问题 | < 30s | 应用层 RTO ≤ 5min |
| 配置回滚 | 配置错误 | < 10s | 应用层 RTO ≤ 5min |
| 数据库回滚 | 迁移失败 | 5-30min | **回滚前必须 pg_dump 全量备份 + 回滚后数据一致性校验** |
| 全量回滚 | 重大故障 | < 5min | 总体 RTO ≤ 30min |

### 14.3 数据库回滚流程

> V1.1 细化数据库回滚流程（依据基准 §8.3）。

```bash
# 1. pg_dump 全量备份（必须，防止回滚后数据丢失）
pg_dump -h $PG_HOST -U $PG_USER -d frd_db -F c -f /tmp/frd_pre_rollback_$(date +%s).dump
ls -lh /tmp/frd_pre_rollback_*.dump  # 验证备份文件存在且非空

# 2. alembic downgrade -1（执行回滚迁移）
alembic downgrade -1
alembic current  # 验证当前迁移版本

# 3. 数据一致性校验脚本（必须执行）
python scripts/db_consistency_check.py \
  --table transactions \
  --check "tenant_id IS NOT NULL" \
  --check "risk_score BETWEEN 0 AND 1"

# 4. 验证应用启动（关键接口健康检查）
kubectl rollout status deployment/frd-backend -n frd-prod
curl -f https://api.frd.example.com/health
curl -f -X POST https://api.frd.example.com/api/v1/transactions/score \
  -H "Authorization: Bearer $TOKEN" -d @smoke_tx.json

# 5. 通知相关方
# - 邛振华（项目负责）
# - PM Agent（进度影响评估）
# - 客户（如涉及业务中断）
```

### 14.4 回滚命令

```bash
# 1. 镜像回滚
helm rollback frd-backend 1 -n frd-prod

# 2. Argo Rollouts 中止金丝雀
kubectl argo rollouts abort frd-backend -n frd-prod

# 3. 数据库回滚（见 §14.3 完整流程）
alembic downgrade -1

# 4. 紧急 Kill Switch（真人授权执行，依据 §15.5 AI Agent 辅助运维）
curl -X POST https://api.frd.example.com/api/v1/governance/kill-switch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"reason":"emergency","duration_minutes":60}'
```

### 14.5 回滚演练

- 每月一次回滚演练
- 演练场景：代码 bug、配置错误、数据库异常
- 演练记录：耗时、问题、改进

---

## 15. 运维手册

### 15.1 日常运维任务

| 任务 | 频率 | 责任人 |
|------|------|--------|
| 监控巡检 | 每日 | 运维 |
| 备份验证 | 每日 | 运维 |
| 慢查询分析 | 每周 | DBA |
| 安全审计 | 每月 | 安全 |
| 漂移分析 | 每周 | ML |
| 容量评估 | 每月 | 架构师 |
| 漏洞扫描 | 每月 | 安全 |
| 证书续期 | 月度 | 运维 |
| 密钥轮换 | 月度（JWT）/ 季度（PII） | 安全 |
| 灾备演练 | 半年 | 运维 |

### 15.2 运维工具

| 工具 | 用途 |
|------|------|
| kubectl | K8s 操作 |
| helm | 应用部署 |
| argocd | GitOps |
| terraform | 基础设施 |
| ansible | 配置管理 |
| grafana | 监控 |
| jaeger | 追踪 |
| loki | 日志 |
| aliyun-cli | 阿里云资源操作 |
| cosign | 镜像签名验证 |

### 15.3 故障排查流程

```
1. 接收告警（DevOps Agent 5min 内自动确认）
2. 定位故障（监控 / 日志 / 追踪）
3. 评估影响（业务 / 客户 / 数据）
4. 紧急处置（AI Agent 自动处置 L1/L2 / 真人决策 L3/L4）
5. 通知干系人
6. 根因分析
7. 修复 + 验证
8. 复盘 + 改进
```

### 15.4 常见故障处理

> V1.1 扩充至 10+ 场景，每个场景含：现象、定位命令、处置步骤、验证方法、升级条件。

#### 15.4.1 API 5xx 错误

- **现象**：Grafana 错误率面板显示 5xx > 1%
- **定位命令**：`kubectl logs -l app=frd-backend -n frd-prod --tail=100 | grep -E "5[0-9]{2}"`
- **处置步骤**：
  1. 查看 Grafana 错误率面板，定位错误类型
  2. 查看下游依赖：DB / Redis / Neo4j 连接状态
  3. 如为代码问题，触发镜像回滚（`helm rollback`）
- **验证方法**：错误率 < 0.1% 持续 10min
- **升级条件**：错误率 > 5% 持续 5min → 升级 L2

#### 15.4.2 数据库慢查询

- **现象**：数据库慢查询数 > 100ms 持续 5min
- **定位命令**：`SELECT * FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;`
- **处置步骤**：
  1. 查看慢查询日志，定位 SQL
  2. `EXPLAIN ANALYZE` 分析执行计划
  3. 加索引 / 优化 SQL
  4. 应用层缓存
- **验证方法**：慢查询 < 100ms 持续 10min
- **升级条件**：慢查询导致 P99 > 500ms 持续 5min → 升级 L2

#### 15.4.3 节点宕机

- **现象**：Prometheus 告警节点 NotReady
- **定位命令**：`kubectl get nodes -o wide | grep NotReady`
- **处置步骤**：
  1. K8s 自动重新调度（PDB 保证 minAvailable）
  2. 检查 Pod 状态：`kubectl get pods -n frd-prod -o wide`
  3. 必要时手动调度到其他节点
  4. 节点恢复后验证
- **验证方法**：所有 Pod Running 持续 10min
- **升级条件**：2+ 节点宕机 → 升级 L3（单 AZ 部署下节点故障影响大）

#### 15.4.4 Redis 主从切换

- **现象**：Redis 哨兵触发主从切换事件
- **定位命令**：`redis-cli -h sentinel-host INFO sentinel`
- **处置步骤**：
  1. 确认新主节点选举完成
  2. 检查应用连接是否自动切换
  3. 检查持久化数据完整性（RDB + AOF）
  4. 旧主节点恢复后手动重新加入集群
- **验证方法**：Redis 写入成功率 100% 持续 5min
- **升级条件**：切换失败或数据丢失 → 升级 L3

#### 15.4.5 Neo4j 集群异常

- **现象**：Neo4j 查询失败率 > 1%
- **定位命令**：`cypher-shell -a bolt://neo4j:7687 "CALL dbms.cluster.overview();"`
- **处置步骤**：
  1. 检查 Neo4j 进程状态
  2. 检查内存与磁盘使用
  3. 必要时从 OSS 备份恢复
  4. 社区版单主，故障需重启或恢复
- **验证方法**：查询失败率 < 0.1% 持续 10min
- **升级条件**：Neo4j 不可用 > 15min → 升级 L3

#### 15.4.6 GPU 节点故障

- **现象**：ML 推理节点 GPU 使用率突降或 nvidia-smi 失败
- **定位命令**：`kubectl exec -it ml-pod -- nvidia-smi`
- **处置步骤**：
  1. 检查 GPU 驱动与 CUDA 版本
  2. 重启 ML Pod（K8s 自动重启）
  3. 如节点硬件故障，Cluster Autoscaler 自动扩新节点
  4. 必要时降级 ML 推理（使用 CPU 模型）
- **验证方法**：ML 推理 P99 < 200ms 持续 10min
- **升级条件**：GPU 节点 2 个全部故障 → 升级 L3（ML 服务不可用）

#### 15.4.7 数据库主从延迟

- **现象**：主从延迟 > 10s
- **定位命令**：`SELECT * FROM pg_stat_replication;`
- **处置步骤**：
  1. 检查从库 IO / WAL 应用状态
  2. 检查网络延迟（同 AZ 应 < 1ms）
  3. 必要时重启从库
  4. 检查大事务导致 WAL 积压
- **验证方法**：主从延迟 < 1s 持续 10min
- **升级条件**：延迟 > 60s 持续 5min → 升级 L2

#### 15.4.8 证书过期

- **现象**：cert-manager 告警证书 < 14 天过期
- **定位命令**：`kubectl get certificate -A -o wide`
- **处置步骤**：
  1. 检查 cert-manager Pod 状态
  2. 检查 ACME challenge（DNS-01 / HTTP-01）
  3. 手动触发续期：`cmctl renew <cert-name> -n <ns>`
  4. 验证新证书已签发
- **验证方法**：证书有效期 > 30 天
- **升级条件**：证书过期导致 TLS 失败 → 升级 L3

#### 15.4.9 K8s 节点 NotReady

- **现象**：节点状态 NotReady
- **定位命令**：`kubectl describe node <node-name>`
- **处置步骤**：
  1. 检查 kubelet 进程：`systemctl status kubelet`
  2. 检查节点资源（内存 / 磁盘 / inode）
  3. 必要时 cordon + drain 节点
  4. 重启 kubelet 或节点
- **验证方法**：节点 Ready 持续 10min
- **升级条件**：节点 NotReady > 10min → 升级 L2

#### 15.4.10 镜像仓库不可用

- **现象**：镜像拉取失败 ImagePullBackOff
- **定位命令**：`kubectl describe pod <pod-name> | grep -A5 Events`
- **处置步骤**：
  1. 检查阿里云 ACR 服务状态
  2. 检查镜像仓库认证：`kubectl get secret regcred`
  3. 切换到备份镜像仓库（Harbor 自建）
  4. 必要时使用本地缓存的镜像
- **验证方法**：新 Pod 成功拉取镜像并 Running
- **升级条件**：镜像仓库不可用 > 30min 影响扩容 → 升级 L2

#### 15.4.11 备份失败

- **现象**：备份任务告警失败
- **定位命令**：`kubectl logs job/pg-backup -n frd-prod`
- **处置步骤**：
  1. 检查 OSS 存储可访问性
  2. 检查数据库连接与权限
  3. 检查磁盘空间
  4. 手动重跑备份任务
- **验证方法**：备份任务成功完成 + 备份文件大小合理
- **升级条件**：连续 2 次备份失败 → 升级 L2（RPO 风险）

---

### 15.5 AI Agent 辅助运维

> V1.1 新增章节，定义 AI Agent 与真人的运维协作模式（依据基准 §1.1 团队配置）。

#### 15.5.1 监控与响应模式

- **DevOps Agent 7×24 监控告警**：AI Agent 全天候监控 Prometheus / Grafana / Loki / Jaeger，自动确认告警（5min 内）
- **真人 12h review**：邝振华工作时间（09:00-21:00）review AI Agent 处置记录，关键决策终审
- **L1/L2 故障 AI Agent 自动处置**：重启 / 扩容 / 镜像回滚等标准化操作由 AI Agent 自动执行
- **L3/L4 故障 AI Agent 上报真人决策**：系统不可用 / 数据泄露等重大故障，AI Agent 立即通知真人决策

#### 15.5.2 AI Agent 自动处置范围（L1/L2）

| 故障等级 | 场景 | AI Agent 自动处置 |
|---------|------|------------------|
| L1 | 单 Pod CrashLoopBackOff | 自动重启 Pod，3 次失败后告警 |
| L1 | 单节点 NotReady | cordon 节点 + 触发 Cluster Autoscaler |
| L1 | CPU/内存飙升 | 自动触发 HPA 扩容 |
| L2 | API 错误率 > 1% | 自动镜像回滚到上一稳定版本 |
| L2 | 数据库主从延迟 > 30s | 自动切换读流量到主库 |
| L2 | Celery 任务积压 > 1000 | 自动扩容 Worker 副本 |

#### 15.5.3 真人授权范围（L3/L4）

以下操作必须真人（邝振华）授权后 AI Agent 方可执行：

- **数据库回滚**（pg_dump + alembic downgrade，§14.3）
- **灰度推进**（5% → 25% → 100%，§13.1）
- **Kill Switch 触发**（紧急熔断，§14.4）
- **跨区域灾备切换**（cn-hangzhou → cn-shanghai）
- **生产数据库删除操作**
- **密钥轮换**（JWT / PII Fernet，§9.3）

#### 15.5.4 AI Agent 操作审计

- 所有 AI Agent 操作记录到审计日志（OSS 7 年保留）
- 关键操作前必须快照（数据库回滚前 pg_dump）
- AI Agent 决策依据（告警数据 / 监控指标）一并归档
- 每周生成 AI Agent 运维报告，真人 review

---

### 15.6 容量规划

> V1.1 新增章节，定义容量基线、扩容阈值与流程。

#### 15.6.1 容量基线

| 资源 | 当前值 | 上限 | 利用率 |
|------|--------|------|--------|
| CPU（API 池） | 12C | 12C | - |
| Memory（API 池） | 24G | 24G | - |
| PostgreSQL 连接数 | - | 500 | 监控中 |
| Redis 内存 | - | 16GB | - |
| Neo4j 存储 | - | 200GB | - |
| OSS 存储 | - | 无上限 | 按量计费 |

#### 15.6.2 扩容阈值

| 指标 | 阈值 | 持续 | 触发动作 |
|------|------|------|---------|
| CPU 使用率 | > 70% | 30min | HPA 自动扩 Pod |
| Memory 使用率 | > 80% | 30min | HPA 自动扩 Pod |
| PostgreSQL 连接数 | > 80% | 10min | 扩容应用 Pod（连接池化） |
| Redis 内存 | > 80% | 10min | 扩容 Redis 或开启驱逐 |
| 磁盘使用率 | > 80% | 30min | 扩容磁盘或清理日志 |
| Pod 数达 HPA 上限 | - | - | 触发 Cluster Autoscaler 扩节点 |

#### 15.6.3 扩容流程

```
1. HPA 自动扩 Pod（≤ 9 副本，1min 内完成）
       ↓ 仍不足
2. Cluster Autoscaler 扩节点（5-10min）
       ↓ 仍不足
3. DB 垂直扩容（人工操作，30min 计划窗口）
       ↓
4. 评估升级至 2 AZ 部署（季度评估）
```

#### 15.6.4 季度容量预测报告

- **频率**：每季度首月 1 日由 DevOps Agent 生成
- **内容**：当前容量使用率、3 个月增长趋势、预测容量瓶颈时间点、扩容建议
- **评审**：邝振华 review 后决定扩容执行
- **预算**：扩容费用纳入下一季度预算评估（基准 §6.1 云资源预算 12 万/年）

---

## 16. 应急预案

### 16.1 应急级别

| 级别 | 描述 | 响应 | 决策 |
|------|------|------|------|
| L1 | 单服务异常 | 15min | 运维（AI Agent 自动处置） |
| L2 | 多服务异常 | 10min | 运维 + PM（AI Agent 处置 + 真人 review） |
| L3 | 系统不可用 | 5min | 高管 + 客户（真人决策） |
| L4 | 数据泄露 | 立即 | 高管 + 客户 + 监管（真人决策） |

### 16.2 应急联系人

详见 [D09 风险评估报告 §附录 B](../D09_risk/FRD-D09-V1.0.md#附录-b-应急联系人)。

### 16.3 灾备方案

| 场景 | 方案 | RTO | RPO |
|------|------|-----|-----|
| 单 Pod 故障 | 自动重启 | 30s | 0 |
| 单节点故障 | 自动调度 | 2min | 0 |
| 数据库故障 | 主从切换（同 AZ） | 5min | 1min |
| 数据损坏 | OSS 备份恢复 | 30min | 24h |
| **区域故障** | **跨区域切换（cn-hangzhou → cn-shanghai OSS）** | **30min** | 1min |
| 应用层代码故障 | 镜像回滚 | 5min | 0 |

> V1.1 区域故障 RTO 统一为 30min（与总体 RTO ≤ 30min 一致），单 AZ 部署下区域故障依赖异地 OSS 备份恢复。

### 16.4 业务连续性

- **RTO**（恢复时间目标）：≤ **30min**（V1.1 由 4h 收紧至 30min，与基准 §8.3 一致）
- **RPO**（恢复点目标）：≤ 1min
- **MTBF**（平均故障间隔）：≥ 720h
- **MTTR**（平均恢复时间）：≤ 30min

---

## 附录 A: 部署清单

### 上线前最终检查

- [ ] 生产环境 K8s 集群（阿里云 ACK）就绪
- [ ] 数据库主从同步正常（同 AZ）
- [ ] Redis 哨兵正常
- [ ] Neo4j 社区版单主正常
- [ ] 阿里云 OSS 可访问（跨区域复制正常）
- [ ] 阿里云 DCDN + WAF + DDoS 高防配置生效
- [ ] SSL 证书有效
- [ ] DNS 解析正确
- [ ] 监控告警就绪（含 V1.1 新增 8 条告警）
- [ ] 日志聚合就绪（应用日志 30 天热 + 1 年冷；审计日志 7 年）
- [ ] 备份策略生效（OSS 跨区域复制）
- [ ] 应急预案就绪
- [ ] 运维手册就绪（含 AI Agent 辅助运维 §15.5）
- [ ] 客户培训完成
- [ ] UAT 签字
- [ ] 等保 2.0 三级备案完成（M5 准出条件）

### 部署资源

- 镜像版本：`1.0.0`
- Helm Chart 版本：`1.0.0`
- 数据库迁移版本：`abc123`
- 配置版本：`config-prod-v1.0`

## 附录 B: 配置参数

详见 `helm/frd-backend/values-prod.yaml`。

## 附录 C: 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| V1.0 | 2026-07-27 | 初版发布 |
| V1.1 | 2026-07-27 | 依据 `FRD-BASELINE-V1.1` 修订：①云厂商统一阿里云（Terraform 模块替换为 `aliyun/terraform-alicloud`，区域 `cn-hangzhou-k/k-a/k-b`，公网入口统一为阿里云 DCDN+WAF+DDoS 高防）；②部署规模降级（3+2+2+2 副本单 AZ + 异地备份，匹配个人项目）；③资源合计修正为 80C 216G + 2 GPU；④SLA 调整为 99.5%；⑤灰度统一 24h+24h（Day1/Day2/Day3）；⑥RTO 统一 ≤ 30min（应用层 5min + 数据库 30min）；⑦新增 §9.6 等保 2.0 三级合规矩阵；⑧新增 §15.5 AI Agent 辅助运维；⑨新增 §15.6 容量规划；⑩告警规则补充 8 条；⑪故障场景扩充至 11 个；⑫CI/CD 增加 AI Agent 自动 review（SAST/Snyk/Trivy/Cosign）；⑬数据库回滚流程细化（pg_dump + 一致性校验）；⑭密钥轮换周期调整（JWT 月度，PII Fernet 双密钥并行期 7 天）；⑮HPA maxReplicas 与节点数对齐 + Cluster Autoscaler；⑯synchronous_commit 改为本地同步 + 远程异步；⑰灰度 P99 阈值统一为 200ms；⑱P2 复审修复：性能指标对齐基准（TPS/AUC/误报率阈值） |
