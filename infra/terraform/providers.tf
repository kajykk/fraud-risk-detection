# ============================================================
# FRD Terraform Providers
# 依据：FRD-D10-V1.1 §4.2 / FRD-BASELINE-V1.1 §8.4
# 云厂商统一阿里云，区域 cn-hangzhou
# ============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = "~> 1.220"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # 远程 state（生产建议启用 OSS backend）
  # backend "oss" {
  #   bucket   = "frd-terraform-state"
  #   prefix   = "terraform/state"
  #   region   = "cn-hangzhou"
  #   encrypt  = true
  #   acl      = "private"
  # }
}

provider "alicloud" {
  region = var.region
  # 凭证通过环境变量传入：ALICLOUD_ACCESS_KEY / ALICLOUD_SECRET_KEY
  # 或通过 RAM Role（生产推荐）
}

# 异地备份区域 provider（用于 OSS 跨区域复制目标 bucket）
provider "alicloud" {
  alias  = "dr"
  region = var.dr_region
}
