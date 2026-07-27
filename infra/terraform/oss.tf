# ============================================================
# 对象存储 OSS（备份 + 模型工件 + 跨区域复制异地备份）
# 依据：FRD-D10-V1.1 §7.1.3 备份策略 / §8.2 对象存储 / §2.2 异地备份
# 异地：cn-hangzhou → cn-shanghai（跨区域复制）
# 合规：审计日志 7 年保留（OSS WORM 模式 + 归档存储）
# ============================================================

# ---------- 主 bucket：备份 + 模型工件 ----------
resource "alicloud_oss_bucket" "main" {
  bucket = var.oss_bucket_name
  acl    = "private"

  # 服务端加密（KMS）
  server_side_encryption_rule {
    sse_algorithm = "KMS"
    kms_master_key_id = alicloud_kms_key.data.id
  }

  # 版本控制（防止误删）
  versioning {
    status = "Enabled"
  }

  # 生命周期：30 天后转低频，90 天后转归档
  lifecycle_rule {
    id      = "backup-lifecycle"
    enabled = true

    expiration {
      days = 365   # 业务备份 1 年保留
    }

    transition {
      days          = 30
      storage_class = "IA"
    }

    transition {
      days          = 90
      storage_class = "Archive"
    }

    noncurrent_version_expiration {
      days = 30
    }
  }

  # WORM 模式（审计日志 7 年保留，符合反洗钱法）
  # 注意：实际 WORM 配置需通过 OSS 控制台或 API 单独设置
  tags = local.common_tags
}

# ---------- 审计日志 bucket（7 年保留，反洗钱法要求） ----------
resource "alicloud_oss_bucket" "audit_logs" {
  bucket = "${var.oss_bucket_name}-audit-logs"
  acl    = "private"

  server_side_encryption_rule {
    sse_algorithm   = "KMS"
    kms_master_key_id = alicloud_kms_key.data.id
  }

  versioning {
    status = "Enabled"
  }

  lifecycle_rule {
    id      = "audit-log-7year-retention"
    enabled = true
    expiration {
      days = 2555   # 7 年（反洗钱法要求）
    }
    transition {
      days          = 90
      storage_class = "Archive"
    }
  }

  tags = local.common_tags
}

# ---------- 模型工件 bucket ----------
resource "alicloud_oss_bucket" "models" {
  bucket = "${var.oss_bucket_name}-models"
  acl    = "private"

  server_side_encryption_rule {
    sse_algorithm   = "KMS"
    kms_master_key_id = alicloud_kms_key.data.id
  }

  versioning {
    status = "Enabled"
  }

  tags = local.common_tags
}

# ---------- 异地备份 bucket（cn-shanghai，跨区域复制目标） ----------
# 使用 alicloud provider 的多 region 配置
resource "alicloud_oss_bucket" "dr" {
  provider = alicloud.dr
  bucket   = var.oss_dr_bucket_name
  acl      = "private"

  server_side_encryption_rule {
    sse_algorithm = "KMS"
  }

  versioning {
    status = "Enabled"
  }

  tags = local.common_tags
}

# 跨区域复制规则（cn-hangzhou → cn-shanghai）
resource "alicloud_oss_bucket_replication" "main_to_dr" {
  bucket = alicloud_oss_bucket.main.id

  rule {
    prefix       = ""   # 复制所有对象
    target_bucket = alicloud_oss_bucket.dr.id
    target_location = var.dr_region
  }
}
