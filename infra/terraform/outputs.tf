# ============================================================
# FRD Terraform 输出
# 仅输出非敏感资源 ID 与连接信息
# 敏感凭证（密码 / KMS KeyID）通过外部 secrets manager 注入
# ============================================================

# ---------- 网络 ----------
output "vpc_id" {
  description = "VPC ID"
  value       = alicloud_vpc.main.id
}

output "vswitch_private_id" {
  description = "私网子网 ID（K8s 节点）"
  value       = alicloud_vswitch.private.id
}

output "vswitch_public_id" {
  description = "公网子网 ID（NAT + SLB）"
  value       = alicloud_vswitch.public.id
}

output "vswitch_db_id" {
  description = "数据库子网 ID"
  value       = alicloud_vswitch.db.id
}

output "nat_gateway_id" {
  description = "NAT 网关 ID"
  value       = alicloud_nat_gateway.main.id
}

# ---------- ACK ----------
output "ack_cluster_id" {
  description = "ACK 集群 ID"
  value       = alicloud_cs_managed_kubernetes.main.id
}

output "ack_cluster_name" {
  description = "ACK 集群名"
  value       = alicloud_cs_managed_kubernetes.main.name
}

output "ack_api_server_endpoint" {
  description = "ACK API Server 公网端点"
  value       = alicloud_cs_managed_kubernetes.main.api_server_slb_ip
}

# ---------- RDS ----------
output "rds_instance_id" {
  description = "RDS PostgreSQL 实例 ID"
  value       = alicloud_db_instance.main.id
}

output "rds_connection_string" {
  description = "RDS 内网连接地址（仅 VPC 内可访问）"
  value       = alicloud_db_instance.main.connection_string
}

output "rds_port" {
  description = "RDS 端口"
  value       = alicloud_db_instance.main.port
}

output "rds_db_name" {
  description = "业务数据库名"
  value       = alicloud_rds_database.main.name
}

# ---------- Redis ----------
output "redis_instance_id" {
  description = "Redis 实例 ID"
  value       = alicloud_kvstore_instance.main.id
}

output "redis_connection_string" {
  description = "Redis 内网连接地址"
  value       = alicloud_kvstore_instance.main.connection_domain
}

output "redis_port" {
  description = "Redis 端口"
  value       = alicloud_kvstore_instance.main.port
}

# ---------- Neo4j ----------
output "neo4j_instance_id" {
  description = "Neo4j ECS 实例 ID"
  value       = alicloud_instance.neo4j.id
}

output "neo4j_private_ip" {
  description = "Neo4j 内网 IP（Bolt 端口 7687）"
  value       = alicloud_instance.neo4j.private_ip
}

# ---------- OSS ----------
output "oss_bucket_main" {
  description = "OSS 主 bucket（备份 + 模型工件）"
  value       = alicloud_oss_bucket.main.id
}

output "oss_bucket_audit_logs" {
  description = "OSS 审计日志 bucket（7 年保留）"
  value       = alicloud_oss_bucket.audit_logs.id
}

output "oss_bucket_models" {
  description = "OSS 模型工件 bucket"
  value       = alicloud_oss_bucket.models.id
}

output "oss_bucket_dr" {
  description = "OSS 异地备份 bucket（cn-shanghai）"
  value       = alicloud_oss_bucket.dr.id
}

# ---------- KMS ----------
output "kms_key_data_arn" {
  description = "数据加密 KMS 密钥 ARN"
  value       = alicloud_kms_key.data.arn
}

output "kms_key_jwt_arn" {
  description = "JWT 签名 KMS 密钥 ARN"
  value       = alicloud_kms_key.jwt.arn
}

output "kms_key_pii_arn" {
  description = "PII Fernet KMS 密钥 ARN"
  value       = alicloud_kms_key.pii.arn
}

output "kms_key_k8s_secret_arn" {
  description = "K8s Secret etcd 加密 KMS 密钥 ARN"
  value       = alicloud_kms_key.k8s_secret.arn
}

# ---------- 安全组 ----------
output "security_group_app_id" {
  description = "应用层安全组 ID"
  value       = alicloud_security_group.app.id
}

output "security_group_db_id" {
  description = "数据库层安全组 ID"
  value       = alicloud_security_group.db.id
}
