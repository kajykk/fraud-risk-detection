# ============================================================
# Redis 7 实例（主从，单 AZ，依据 D10 §7.2 / §3.2）
# 规格：4C16G + 100GB（依据 D10 §3.2）
# 模式：哨兵集群（1 主 + 1 从 + 3 哨兵，同 AZ）
# 持久化：RDB 每小时 + AOF 每秒
# 淘汰策略：allkeys-lru
# ============================================================

# ---------- Redis 主实例 ----------
resource "alicloud_kvstore_instance" "main" {
  instance_class       = var.redis_instance_type
  instance_name        = "${local.resource_prefix}-redis-primary"
  engine_version       = var.redis_engine_version
  engine               = "Redis"
  vswitch_id           = alicloud_vswitch.db.id
  zone_id              = var.availability_zone
  # 单 AZ 部署（D10 §1.3）：主从同 AZ
  zone_slave_a         = var.availability_zone
  instance_charge_type = "Postpaid"

  # 哨兵集群模式（1 主 + 1 从 + 3 哨兵）
  architecture_type = "standard"
  ha_config         = "sentinel"

  # 备份策略（依据 D10 §7.2）
  backup_period     = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday"
  backup_time       = "03:00Z"   # 每日 03:00 UTC
  backup_retention_period = 7

  # 删除保护
  deletion_protection = true

  # 安全组（仅业务安全组可访问）
  security_group_ids = [alicloud_security_group.db.id]

  # 密码
  password = var.redis_password

  tags = local.common_tags
}

# ---------- Redis 参数配置（依据 D10 §7.2） ----------
resource "alicloud_kvstore_account" "main" {
  instance_id     = alicloud_kvstore_instance.main.id
  account_name    = "frd_app"
  account_password = var.redis_password
  description     = "FRD application Redis account"
}

# 说明：Redis 参数通过控制台或 API 单独配置（terraform 暂不直接支持）：
#   - maxmemory-policy: allkeys-lru
#   - maxmemory: 12GB（业务 12GB + 系统 4GB）
#   - appendonly: yes（AOF 每秒）
#   - save: 3600 1（RDB 每小时）
