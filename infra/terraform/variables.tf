# ============================================================
# FRD Terraform 变量定义
# 依据：FRD-D10-V1.1 §3.2 生产环境资源规格 / §4 基础设施
# ============================================================

# ---------- 通用 ----------
variable "region" {
  description = "阿里云区域（统一 cn-hangzhou，依据基准 §8.4）"
  type        = string
  default     = "cn-hangzhou"
}

variable "dr_region" {
  description = "异地备份区域（OSS 跨区域复制目标，依据 D10 §2.2）"
  type        = string
  default     = "cn-shanghai"
}

variable "environment" {
  description = "环境标识：local/dev/test/staging/prod"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "项目名前缀"
  type        = string
  default     = "frd"
}

variable "availability_zone" {
  description = "主可用区（单 AZ 部署，依据 D10 §1.3 降级方案）"
  type        = string
  default     = "cn-hangzhou-k"
}

# ---------- 网络 ----------
variable "vpc_cidr" {
  description = "VPC CIDR（依据 D10 §4.3）"
  type        = string
  default     = "10.0.0.0/16"
}

variable "vswitch_private_cidr" {
  description = "私网子网（K8s 节点）"
  type        = string
  default     = "10.0.1.0/24"
}

variable "vswitch_public_cidr" {
  description = "公网子网（NAT + SLB）"
  type        = string
  default     = "10.0.101.0/24"
}

variable "vswitch_db_cidr" {
  description = "数据库子网（独立子网）"
  type        = string
  default     = "10.0.201.0/24"
}

# ---------- ACK 集群 ----------
variable "ack_cluster_name" {
  description = "ACK 集群名"
  type        = string
  default     = "frd-prod-ack"
}

variable "ack_cluster_version" {
  description = "ACK Kubernetes 版本（依据 D10 §1.3 / D03 §1.3）"
  type        = string
  default     = "1.28"
}

variable "ack_node_password" {
  description = "ACK 节点 SSH 密码（生产建议改用密钥对）"
  type        = string
  sensitive   = true
  default     = "ChangeMe!2026"
}

# ---------- RDS PostgreSQL ----------
variable "rds_instance_type" {
  description = "RDS PostgreSQL 实例规格（依据 D10 §3.2：8C32G）"
  type        = string
  default     = "pg.n2.large.2c"   # 8C32G
}

variable "rds_engine_version" {
  description = "PostgreSQL 大版本"
  type        = string
  default     = "15.0"
}

variable "rds_storage" {
  description = "RDS 存储容量 GB（依据 D10 §3.2：500GB SSD）"
  type        = number
  default     = 500
}

variable "rds_username" {
  description = "RDS 主账号"
  type        = string
  default     = "frd_admin"
}

variable "rds_password" {
  description = "RDS 主密码（生产必须从外部 secrets 注入）"
  type        = string
  sensitive   = true
  default     = "ChangeMe-RDS-2026"
}

variable "rds_db_name" {
  description = "业务数据库名"
  type        = string
  default     = "frd_db"
}

# ---------- Redis ----------
variable "redis_instance_type" {
  description = "Redis 实例规格（依据 D10 §3.2：4C16G）"
  type        = string
  default     = "redis.master.small.default"   # 4C16G
}

variable "redis_engine_version" {
  description = "Redis 版本"
  type        = string
  default     = "7.0"
}

variable "redis_password" {
  description = "Redis 密码"
  type        = string
  sensitive   = true
  default     = "ChangeMe-Redis-2026"
}

# ---------- Neo4j（自建 ECS） ----------
variable "neo4j_instance_type" {
  description = "Neo4j ECS 实例规格（依据 D10 §3.2：4C16G）"
  type        = string
  default     = "ecs.g6.xlarge"
}

variable "neo4j_storage" {
  description = "Neo4j 数据盘大小 GB（依据 D10 §3.2：200GB SSD）"
  type        = number
  default     = 200
}

variable "neo4j_password" {
  description = "Neo4j 密码"
  type        = string
  sensitive   = true
  default     = "ChangeMe-Neo4j-2026"
}

# ---------- OSS ----------
variable "oss_bucket_name" {
  description = "OSS bucket 名（备份 + 模型工件）"
  type        = string
  default     = "frd-prod-backup"
}

variable "oss_dr_bucket_name" {
  description = "OSS 异地备份 bucket 名（cn-shanghai）"
  type        = string
  default     = "frd-prod-backup-dr"
}

# ---------- KMS ----------
variable "kms_key_alias_data" {
  description = "数据加密 KMS 密钥别名"
  type        = string
  default     = "frd-prod-data-encryption"
}

variable "kms_key_alias_jwt" {
  description = "JWT 签名 KMS 密钥别名"
  type        = string
  default     = "frd-prod-jwt-signing"
}

variable "kms_key_alias_pii" {
  description = "PII Fernet 加密 KMS 密钥别名"
  type        = string
  default     = "frd-prod-pii-fernet"
}

variable "kms_key_alias_k8s_secret" {
  description = "K8s Secret etcd 加密 KMS 密钥别名"
  type        = string
  default     = "frd-prod-k8s-secret"
}

# ---------- 标签 ----------
variable "tags" {
  description = "统一资源标签"
  type        = map(string)
  default = {
    Project     = "fraud-risk-detection"
    Environment = "prod"
    Owner       = "kuang-zhenhua"
    Compliance  = "PCI-DSS-v4.0|PIPL|等保2.0-三级"
    ManagedBy   = "terraform"
  }
}
