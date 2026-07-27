# ============================================================
# RDS PostgreSQL 15（主从，单 AZ + 异地 OSS 备份）
# 依据：FRD-D10-V1.1 §3.2 / §7.1 数据库部署 / §9.3 密钥管理
# 规格：8C32G + 500GB SSD（依据 D10 §3.2）
# 备份：每日全量 + WAL 持续归档到 OSS（跨区域复制到 cn-shanghai）
# RPO < 1 分钟；RTO ≤ 30 分钟
# ============================================================

# ---------- RDS 主实例（PostgreSQL 15） ----------
resource "alicloud_db_instance" "main" {
  engine                = "PostgreSQL"
  engine_version        = var.rds_engine_version
  instance_type         = var.rds_instance_type
  instance_storage      = var.rds_storage
  instance_storage_type = "cloud_essd"   # ESSD PL1
  db_instance_storage_type = "cloud_essd"

  instance_name     = "${local.resource_prefix}-pg-primary"
  vswitch_id        = alicloud_vswitch.db.id
  security_ips      = [var.vswitch_private_cidr]

  # 单 AZ 部署（D10 §1.3 降级方案），主从同 AZ
  zone_id            = var.availability_zone
  zone_id_slave_a    = var.availability_zone
  instance_charge_type = "Postpaid"

  # 高可用：主从切换
  ha_instance_used   = true
  ha_config          = "Auto"

  # 网络类型：VPC
  instance_network_type = "VPC"

  # 备份策略（依据 D10 §7.1.3）
  backup_period    = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
  backup_time      = "02:00Z"   # 每日 02:00 UTC（10:00 CST）
  backup_retention_period = 30   # 30 天保留

  # 日志备份（WAL 持续归档，RPO < 1min）
  log_backup_period         = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
  log_backup_retention_period = 30

  # TDE 透明数据加密（KMS）
  tde_status      = "Enabled"
  encryption_key  = alicloud_kms_key.data.id

  # 删除保护
  deletion_protection = true

  tags = local.common_tags
}

# ---------- 业务数据库 ----------
resource "alicloud_rds_database" "main" {
  instance_id = alicloud_db_instance.main.id
  name        = var.rds_db_name
  description = "FRD business database (RLS enabled, ADR-015)"
}

# ---------- 数据库账号 ----------
resource "alicloud_rds_account" "main" {
  db_instance_id   = alicloud_db_instance.main.id
  account_name     = var.rds_username
  account_password = var.rds_password
  account_type     = "Super"
  description      = "FRD admin account"
}

# 说明：
# 1. RDS 白名单通过 security_ips 已在主实例配置，仅业务私网子网可访问
# 2. RDS 异地备份通过 OSS 跨区域复制实现（见 oss.tf）
#    - WAL 归档：archive_command 'aliyun oss cp %p oss://frd-prod-backup/wal/%f'
# 3. 月度备份归档到 OSS 低频访问，年度备份归档到 OSS 归档存储（7 年保留）
# 4. PostgreSQL 配置（依据 D10 §7.1.2）：
#    - shared_buffers = 8GB
#    - effective_cache_size = 24GB
#    - max_connections = 500
#    - wal_level = replica
#    - synchronous_commit = on（单 AZ 本地同步 + 远程异步）
