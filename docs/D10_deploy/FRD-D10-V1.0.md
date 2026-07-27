# FRD 金融反欺诈系统 上线部署方案

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| V1.0 | 2026-07-27 | 邝振华 | 初版发布 |

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

- **高可用**：99.95% SLA（年宕机 ≤ 4.38h）
- **可扩展**：水平扩展支持 5000 TPS
- **安全合规**：PCI-DSS v4.0 / PIPL / 反洗钱法
- **可观测**：全链路监控、告警、追踪
- **可回滚**：任何变更 5 分钟内可回滚

### 1.2 部署原则

- 基础设施即代码（IaC）：Terraform + Helm
- 不可变基础设施：容器化 + 不可变镜像
- GitOps：Git 作为单一可信源
- 零停机部署：滚动更新 + 金丝雀
- 最小权限：RBAC + NetworkPolicy
- 多 AZ 容灾：跨可用区部署

### 1.3 部署范围

| 组件 | 部署形态 | 数量 |
|------|----------|------|
| API 网关 | K8s Deployment | 3 副本 × 3 AZ |
| 评分服务 | K8s Deployment | 6 副本 × 3 AZ |
| 规则服务 | K8s Deployment | 3 副本 × 3 AZ |
| 案件服务 | K8s Deployment | 3 副本 × 3 AZ |
| GNN 服务 | K8s Deployment | 2 副本 × 2 AZ |
| ML 推理 | K8s Deployment | 4 副本 × 2 AZ |
| Celery Worker | K8s Deployment | 4 副本 × 3 AZ |
| Celery Beat | K8s Deployment | 1 副本 + 1 standby |
| PostgreSQL | StatefulSet | 1 主 + 2 从 × 3 AZ |
| Redis | StatefulSet | 1 主 + 2 从 × 3 AZ |
| Neo4j | StatefulSet | 1 主 + 2 从 × 3 AZ |
| Prometheus | StatefulSet | 1 主 + 1 从 |
| Grafana | Deployment | 1 副本 |
| Nginx Ingress | DaemonSet | 每节点 1 个 |

---

## 2. 部署架构

### 2.1 整体架构图

```
                          ┌──────────────────┐
                          │   Cloudflare     │
                          │   CDN + WAF      │
                          └────────┬─────────┘
                                   │
                          ┌────────┴─────────┐
                          │  跨 AZ 负载均衡   │
                          └────────┬─────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │                                     │
        ┌───────┴───────┐                     ┌───────┴───────┐
        │   AZ-1        │                     │   AZ-2        │   ...
        │ ┌───────────┐ │                     │ ┌───────────┐ │
        │ │ Nginx     │ │                     │ │ Nginx     │ │
        │ │ Ingress   │ │                     │ │ Ingress   │ │
        │ └─────┬─────┘ │                     │ └─────┬─────┘ │
        │       │       │                     │       │       │
        │  ┌────┴────┐  │                     │  ┌────┴────┐  │
        │  │ K8s     │  │                     │  │ K8s     │  │
        │  │ Cluster │  │                     │  │ Cluster │  │
        │  │ -API    │  │                     │  │ -API    │  │
        │  │ -Rule   │  │                     │  │ -Rule   │  │
        │  │ -Case   │  │                     │  │ -Case   │  │
        │  │ -GNN    │  │                     │  │ -GNN    │  │
        │  │ -ML     │  │                     │  │ -ML     │  │
        │  │ -Worker │  │                     │  │ -Worker │  │
        │  └────┬────┘  │                     │  └────┬────┘  │
        └───────┼───────┘                     └───────┼───────┘
                │                                     │
                └─────────────┬───────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │       共享存储 / 数据库         │
              │  ┌────────┐  ┌────────┐      │
              │  │Postgre │  │ Redis  │      │
              │  │SQL主从 │  │ 主从   │      │
              │  └────────┘  └────────┘      │
              │  ┌────────┐  ┌────────┐      │
              │  │ Neo4j  │  │  对象  │      │
              │  │ 主从   │  │  存储  │      │
              │  └────────┘  └────────┘      │
              └───────────────────────────────┘
```

### 2.2 网络拓扑

- 公网入口：Cloudflare（CDN + WAF + DDoS 防护）
- VPC 边界：云厂商 NAT 网关 + 安全组
- 集群入口：Nginx Ingress Controller
- 服务间：K8s ClusterIP + NetworkPolicy
- 数据库：私有子网，仅集群内可达

---

## 3. 环境规划

### 3.1 环境清单

| 环境 | 用途 | 部署形态 | 数据 | 资源规格 |
|------|------|----------|------|----------|
| Local | 开发 | docker-compose | 模拟 | 4C8G |
| Dev | 联调 | K8s 单节点 | 脱敏 | 8C16G |
| Test | 功能测试 | K8s 单节点 | 脱敏 | 16C32G |
| Staging | 预发 | K8s 多节点 | 生产快照 | 与生产一致（小规格） |
| Prod | 生产 | K8s 多 AZ | 真实 | 见 §3.2 |

### 3.2 生产环境资源规格

| 资源 | 规格 | 数量 | 总资源 |
|------|------|------|--------|
| API 节点 | 4C8G | 9 | 36C 72G |
| Worker 节点 | 4C8G | 12 | 48C 96G |
| ML 推理节点 | 8C16G + GPU | 4 | 32C 64G + 4 GPU |
| PostgreSQL | 8C32G + 500GB SSD | 3 | 24C 96G |
| Redis | 4C16G + 100GB | 3 | 12C 48G |
| Neo4j | 8C32G + 200GB SSD | 3 | 24C 96G |
| 监控 | 2C4G | 3 | 6C 12G |
| Ingress | 2C4G | 3 | 6C 12G |
| **合计** | - | 40 | **188C 396G + 4 GPU** |

### 3.3 环境隔离

- 每个环境独立 VPC
- 跨环境通过 VPN 互联
- 生产环境仅运维可访问（堡垒机）
- 数据不跨环境同步（除脱敏快照）

---

## 4. 基础设施准备

### 4.1 云资源清单

| 资源类型 | 数量 | 说明 |
|----------|------|------|
| VPC | 5 | 每环境 1 个 |
| 子网 | 20 | 公网 + 私网 + 数据库 |
| 安全组 | 15 | 按 environment/role 分组 |
| 负载均衡 | 5 | 每环境 1 个 |
| NAT 网关 | 5 | 每环境 1 个 |
| Kubernetes 集群 | 5 | 每环境 1 个 |
| RDS PostgreSQL | 5 | 每环境 1 套主从 |
| ElastiCache Redis | 5 | 每环境 1 套主从 |
| 对象存储（S3/OSS） | 5 | 每环境 1 个 |
| KMS 密钥 | 10 | 数据加密 + JWT 签名 |
| CDN | 1 | 生产前端分发 |
| WAF | 1 | 生产入口防护 |
| 域名 + SSL 证书 | 5 | 每环境 1 套 |

### 4.2 Terraform 配置

```hcl
# infra/terraform/main.tf
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0"
  name    = "frd-prod-vpc"
  cidr    = "10.0.0.0/16"
  azs             = ["cn-north-1a", "cn-north-1b", "cn-north-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
  enable_nat_gateway = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.0"
  cluster_name    = "frd-prod-eks"
  cluster_version = "1.28"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets
  node_groups = {
    api      = { instance_type = "c5.xlarge", desired_size = 9 }
    worker   = { instance_type = "c5.xlarge", desired_size = 12 }
    ml       = { instance_type = "g4dn.xlarge", desired_size = 4 }
  }
}
```

### 4.3 网络配置

- VPC CIDR：`10.0.0.0/16`
- 公网子网：`10.0.101.0/24` 等（NAT + ALB）
- 私网子网：`10.0.1.0/24` 等（K8s 节点）
- 数据库子网：`10.0.201.0/24` 等（独立子网）
- 安全组规则：最小化开放，默认拒绝

---

## 5. 容器化与镜像

### 5.1 镜像清单

| 镜像 | 大小 | 基础镜像 | 说明 |
|------|------|----------|------|
| frd-backend | 280MB | python:3.12-slim | FastAPI 后端 |
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

# 漏洞扫描
trivy image frd-backend:1.0.0 --severity HIGH,CRITICAL

# 签名
cosign sign --key cosign.key frd-backend:1.0.0

# 推送
docker push registry.frd.example.com/frd-backend:1.0.0
```

### 5.4 镜像仓库

- 私有仓库：Harbor（自建）或云厂商 ACR
- 命名规范：`registry.frd.example.com/{image}:{version}`
- 版本：`{semver}-{git-sha}`（如 `1.0.0-abc1234`）
- 保留策略：最新 10 个版本 + 所有发版版本

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
  replicas: 6
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
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: frd-backend
                topologyKey: topology.kubernetes.io/zone
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
  minReplicas: 6
  maxReplicas: 24
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

### 6.5 PDB（Pod Disruption Budget）

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: frd-backend-pdb
spec:
  minAvailable: 4
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

- 模式：主从复制（1 主 + 2 从）
- 工具：CloudNativePG 或 Patroni
- 备份：每日全量 + WAL 持续归档
- RPO：< 1 分钟
- RTO：< 5 分钟

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
synchronous_commit = on
synchronous_standby_names = 'FIRST 1 (replica1, replica2)'
```

#### 7.1.3 备份策略

| 类型 | 频率 | 保留 | 存储 |
|------|------|------|------|
| 全量备份 | 每日 02:00 | 30 天 | 对象存储 |
| WAL 归档 | 持续 | 30 天 | 对象存储 |
| 月度备份 | 每月 1 日 | 12 个月 | 对象存储（冷存储） |
| 年度备份 | 每年 1 月 | 7 年 | 对象存储（归档） |

### 7.2 Redis

- 模式：哨兵集群（1 主 + 2 从 + 3 哨兵）
- 持久化：RDB 每小时 + AOF 每秒
- 内存：16GB（业务 12GB + 系统 4GB）
- 淘汰策略：`allkeys-lru`

### 7.3 Neo4j

- 模式：Causal Cluster（1 主 + 2 从）
- 内存：堆 16GB + 页缓存 12GB
- 备份：每日全量 + 增量事务日志

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
- 类型：S3 兼容（MinIO 自建 / 云厂商 OSS）
- 桶规划：
  - `frd-attachments`：案件附件
  - `frd-reports`：报表导出
  - `frd-backups`：数据库备份
  - `frd-models`：模型文件
  - `frd-audit-logs`：审计日志归档

### 8.3 服务发现

- K8s 内置 Service + DNS
- 跨语言调用：gRPC + 服务网格（可选 Istio）

---

## 9. 网络与安全

### 9.1 网络分层

```
公网 → CDN/WAF → 负载均衡 → Ingress → Service → Pod → 数据库
   ↓           ↓           ↓           ↓
   DDoS       限流        TLS        NetworkPolicy
   防护        WAF        终止       + RBAC
```

### 9.2 TLS 证书

- 公网证书：Let's Encrypt 或云厂商免费证书
- 内部服务：自签 CA + cert-manager 自动签发
- 证书自动续期：cert-manager + ACME
- TLS 版本：1.2+，禁用 SSLv3/TLSv1.0/1.1

### 9.3 密钥管理

| 密钥类型 | 存储位置 | 轮换周期 |
|----------|----------|----------|
| JWT 签名 | KMS | 季度 |
| 数据库密码 | K8s Secret + KMS | 月度 |
| PII 加密密钥（Fernet） | KMS | 季度 |
| API Token | K8s Secret | 月度 |
| Webhook 签名密钥 | K8s Secret | 季度 |

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
| PIPL | 数据本地化 | 国内云 + 国内存储 |
| 反洗钱法 | 审计日志 7 年 | 月度归档到冷存储 |
| 等保 2.0 三级 | 多 AZ 容灾 | 跨 AZ 部署 |

---

## 10. CI/CD 流水线

### 10.1 流水线全景

```
开发提交代码 → PR → CI 检查 → 评审 → 合并 main
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
  deploy:
    runs-on: ubuntu-latest
    environment: production  # 需要审批
    steps:
      - uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
      - name: Update kubeconfig
        run: aws eks update-kubeconfig --name frd-prod-eks
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
| ML | 模型 AUC | > 0.90 |
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
| 模型 AUC 下降 | < 0.90 | WARN | ML |
| 漂移 PSI | > 0.25 | WARN | ML |
| 金丝雀失败 | 触发回滚 | CRITICAL | ML + PM |
| 审计日志中断 | 5min 无日志 | CRITICAL | 合规 |

### 11.4 日志聚合

- 应用日志：JSON 格式，输出到 stdout
- 采集：Fluent Bit → Loki
- 查询：Grafana LogQL
- 保留：30 天热数据 + 1 年冷归档

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
- [ ] 合规审计通过（PCI-DSS / PIPL / 反洗钱）
- [ ] 文档齐备（D01-D11）
- [ ] 运维手册 + 应急预案就绪
- [ ] 监控告警就绪
- [ ] 备份恢复验证通过
- [ ] 故障演练通过
- [ ] 客户 UAT 签字

### 12.2 上线时间窗

- 推荐时间：周六 02:00-06:00（业务低峰）
- 回滚窗口：上线后 4 小时内可无条件回滚
- 灰度观察：72 小时

### 12.3 上线步骤

```
1. 02:00  开始上线，通知干系人
2. 02:05  停止旧版本 Cron 任务
3. 02:10  执行数据库迁移（向前兼容）
4. 02:20  部署新版本（灰度 5% 流量）
5. 02:30  健康检查 + 烟雾测试
6. 02:40  灰度观察 30 分钟
7. 03:10  推进灰度到 25%
8. 03:40  灰度观察 30 分钟
9. 04:10  推进灰度到 100%
10. 04:20 全量健康检查
11. 04:30 启用新版本 Cron 任务
12. 04:40 上线完成，通知干系人
13. 04:40-06:00 监控值班
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

```
Stage 1: 5% 流量，持续 24h
   ↓ 监控指标达标
Stage 2: 25% 流量，持续 24h
   ↓ 监控指标达标
Stage 3: 100% 流量（完成上线）
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
| P99 延迟 | < 250ms | 5min |
| 业务成功率 | > 99% | 5min |
| 模型 AUC 偏差 | < 2% | 30min |
| 误报率 | < 30% | 1h |

任一指标超阈值触发自动回滚。

---

## 14. 回滚方案

### 14.1 回滚触发条件

- 自动：灰度指标超阈值
- 手动：运维 / PM / 客户决策

### 14.2 回滚类型

| 类型 | 适用 | 耗时 |
|------|------|------|
| 镜像回滚 | 代码问题 | < 30s |
| 配置回滚 | 配置错误 | < 10s |
| 数据库回滚 | 迁移失败 | 5-30min |
| 全量回滚 | 重大故障 | < 5min |

### 14.3 回滚命令

```bash
# 1. 镜像回滚
helm rollback frd-backend 1 -n frd-prod

# 2. Argo Rollouts 中止金丝雀
kubectl argo rollouts abort frd-backend -n frd-prod

# 3. 数据库回滚（如迁移可逆）
alembic downgrade -1

# 4. 紧急 Kill Switch
curl -X POST https://api.frd.example.com/api/v1/governance/kill-switch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"reason":"emergency","duration_minutes":60}'
```

### 14.4 回滚演练

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
| 证书续期 | 季度 | 运维 |
| 密钥轮换 | 季度 | 安全 |
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

### 15.3 故障排查流程

```
1. 接收告警（5min 内确认）
2. 定位故障（监控 / 日志 / 追踪）
3. 评估影响（业务 / 客户 / 数据）
4. 紧急处置（重启 / 回滚 / 降级）
5. 通知干系人
6. 根因分析
7. 修复 + 验证
8. 复盘 + 改进
```

### 15.4 常见故障处理

#### 15.4.1 API 5xx 错误

1. 查看 Grafana 错误率面板
2. 定位错误 Pod：`kubectl logs -l app=frd-backend`
3. 查看下游依赖：DB / Redis / Neo4j
4. 必要时回滚

#### 15.4.2 数据库慢查询

1. 查看慢查询日志
2. EXPLAIN ANALYZE
3. 加索引 / 优化 SQL
4. 应用层缓存

#### 15.4.3 节点宕机

1. K8s 自动重新调度
2. 检查 Pod 状态
3. 必要时手动调度
4. 节点恢复后验证

---

## 16. 应急预案

### 16.1 应急级别

| 级别 | 描述 | 响应 | 决策 |
|------|------|------|------|
| L1 | 单服务异常 | 15min | 运维 |
| L2 | 多服务异常 | 10min | 运维 + PM |
| L3 | 系统不可用 | 5min | 高管 + 客户 |
| L4 | 数据泄露 | 立即 | 高管 + 客户 + 监管 |

### 16.2 应急联系人

详见 [D09 风险评估报告 §附录 B](../D09_risk/FRD-D09-V1.0.md#附录-b-应急联系人)。

### 16.3 灾备方案

| 场景 | 方案 | RTO | RPO |
|------|------|-----|-----|
| 单 Pod 故障 | 自动重启 | 30s | 0 |
| 单节点故障 | 自动调度 | 2min | 0 |
| 单 AZ 故障 | 跨 AZ 切换 | 5min | 0 |
| 区域故障 | 跨区域切换 | 30min | 1min |
| 数据库故障 | 主从切换 | 5min | 1min |
| 数据损坏 | 备份恢复 | 1h | 24h |

### 16.4 业务连续性

- **RTO**（恢复时间目标）：≤ 4h
- **RPO**（恢复点目标）：≤ 1min
- **MTBF**（平均故障间隔）：≥ 720h
- **MTTR**（平均恢复时间）：≤ 30min

---

## 附录 A: 部署清单

### 上线前最终检查

- [ ] 生产环境 K8s 集群就绪
- [ ] 数据库主从同步正常
- [ ] Redis 哨兵正常
- [ ] Neo4j 集群正常
- [ ] 对象存储可访问
- [ ] CDN + WAF 配置生效
- [ ] SSL 证书有效
- [ ] DNS 解析正确
- [ ] 监控告警就绪
- [ ] 日志聚合就绪
- [ ] 备份策略生效
- [ ] 应急预案就绪
- [ ] 运维手册就绪
- [ ] 客户培训完成
- [ ] UAT 签字

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
