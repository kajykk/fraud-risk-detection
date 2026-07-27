# ============================================================
# KMS 密钥（数据加密 + JWT 签名 + PII Fernet + K8s Secret）
# 依据：FRD-D10-V1.1 §9.3 密钥管理 / FRD-BASELINE-V1.1 §8.4
# 轮换周期：JWT 月度 / DB 密码月度 / PII Fernet 季度（双密钥并行期 7 天）/ K8s Secret 年度
# ============================================================

# ---------- 数据加密 KMS 密钥 ----------
resource "alicloud_kms_key" "data" {
  description            = "FRD prod data encryption key (TDE + 字段级加密)"
  key_usage              = "ENCRYPT/DECRYPT"
  key_spec               = "Aliyun_AES_256"
  rotation_interval      = "31536000s"   # 365d（年度轮换）
  protection_level       = "HSM"
  deletion_window_in_days = 30
  tags                   = local.common_tags
}

resource "alicloud_kms_alias" "data" {
  alias_name  = "alias/${var.kms_key_alias_data}"
  key_id      = alicloud_kms_key.data.id
}

# ---------- JWT 签名 KMS 密钥（月度轮换） ----------
resource "alicloud_kms_key" "jwt" {
  description            = "FRD JWT signing key (monthly rotation, D10 §9.3)"
  key_usage              = "SIGN/VERIFY"
  key_spec               = "Aliyun_RSA_3072"
  rotation_interval      = "2592000s"   # 30d 月度轮换
  protection_level       = "HSM"
  deletion_window_in_days = 7
  tags                   = local.common_tags
}

resource "alicloud_kms_alias" "jwt" {
  alias_name  = "alias/${var.kms_key_alias_jwt}"
  key_id      = alicloud_kms_key.jwt.id
}

# ---------- PII Fernet 加密 KMS 密钥（季度轮换，双密钥并行期 7 天） ----------
resource "alicloud_kms_key" "pii" {
  description            = "FRD PII Fernet encryption key (quarterly rotation, 7-day dual-key parallel, D10 §9.3)"
  key_usage              = "ENCRYPT/DECRYPT"
  key_spec               = "Aliyun_AES_256"
  rotation_interval      = "7776000s"   # 90d 季度轮换
  protection_level       = "HSM"
  deletion_window_in_days = 30
  tags                   = local.common_tags
}

resource "alicloud_kms_alias" "pii" {
  alias_name  = "alias/${var.kms_key_alias_pii}"
  key_id      = alicloud_kms_key.pii.id
}

# ---------- K8s Secret etcd 加密 KMS 密钥（年度轮换） ----------
resource "alicloud_kms_key" "k8s_secret" {
  description            = "FRD K8s Secret etcd encryption key (annual rotation, D10 §9.3)"
  key_usage              = "ENCRYPT/DECRYPT"
  key_spec               = "Aliyun_AES_256"
  rotation_interval      = "31536000s"   # 365d 年度轮换
  protection_level       = "HSM"
  deletion_window_in_days = 30
  tags                   = local.common_tags
}

resource "alicloud_kms_alias" "k8s_secret" {
  alias_name  = "alias/${var.kms_key_alias_k8s_secret}"
  key_id      = alicloud_kms_key.k8s_secret.id
}
