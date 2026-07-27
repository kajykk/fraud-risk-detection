# ============================================================
# FRD Terraform 主入口
# 依据：FRD-D10-V1.1 §4 基础设施准备 / §1.3 单 AZ + 异地备份
# 资源清单（D10 §4.1）：
#   VPC + 公私网子网 + NAT 网关
#   ACK Kubernetes 集群（K8s 1.28）
#   RDS PostgreSQL 15（主从，单 AZ + 异地 OSS 备份）
#   Redis 7 实例
#   Neo4j 社区版（ECS 自建，4C16G + 200GB SSD）
#   OSS 对象存储（备份 + 模型工件，跨区域复制到 cn-shanghai）
#   KMS 密钥（数据加密 + JWT 签名 + PII Fernet + K8s Secret）
# SLA：99.5%（MVP）/ 99.9%（生产稳态）；RTO ≤ 30min；RPO ≤ 1min
# ============================================================

locals {
  resource_prefix = "${var.project_name}-${var.environment}"

  common_tags = merge(var.tags, {
    Region = var.region
    AZ     = var.availability_zone
  })
}

# ---------- 资源编排顺序（依赖关系） ----------
# 1. providers.tf      — Provider 配置
# 2. vpc.tf            — VPC + 子网 + NAT 网关
# 3. kms.tf            — KMS 密钥（被其他资源引用，需先创建）
# 4. oss.tf            — 对象存储（备份 + 模型工件 + 跨区域复制）
# 5. rds.tf            — RDS PostgreSQL（依赖 VPC + KMS）
# 6. redis.tf          — Redis 实例（依赖 VPC）
# 7. neo4j.tf          — Neo4j ECS 自建（依赖 VPC + 安全组）
# 8. ack.tf            — ACK 集群（依赖 VPC）
# 9. outputs.tf        — 输出关键资源 ID
