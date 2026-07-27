# ============================================================
# VPC + 子网 + NAT 网关 + 安全组
# 依据：FRD-D10-V1.1 §4.3 网络配置 / §9.1 网络分层
# 单 AZ 部署：vswitch 均在 cn-hangzhou-k
# 异地备份通过 OSS 跨区域复制实现（见 oss.tf）
# ============================================================

# ---------- VPC ----------
resource "alicloud_vpc" "main" {
  vpc_name   = "${local.resource_prefix}-vpc"
  cidr_block = var.vpc_cidr
  tags       = local.common_tags
}

# ---------- 公网子网（NAT + SLB） ----------
resource "alicloud_vswitch" "public" {
  vpc_id            = alicloud_vpc.main.id
  cidr_block        = var.vswitch_public_cidr
  zone_id           = var.availability_zone
  vswitch_name      = "${local.resource_prefix}-public-${var.availability_zone}"
  tags              = local.common_tags
}

# ---------- 私网子网（K8s 节点） ----------
resource "alicloud_vswitch" "private" {
  vpc_id            = alicloud_vpc.main.id
  cidr_block        = var.vswitch_private_cidr
  zone_id           = var.availability_zone
  vswitch_name      = "${local.resource_prefix}-private-${var.availability_zone}"
  tags              = local.common_tags
}

# ---------- 数据库子网（独立子网，仅集群内可达） ----------
resource "alicloud_vswitch" "db" {
  vpc_id            = alicloud_vpc.main.id
  cidr_block        = var.vswitch_db_cidr
  zone_id           = var.availability_zone
  vswitch_name      = "${local.resource_prefix}-db-${var.availability_zone}"
  tags              = local.common_tags
}

# ---------- EIP for NAT Gateway ----------
resource "alicloud_eip_address" "nat" {
  name                 = "${local.resource_prefix}-nat-eip"
  bandwidth            = "100"
  internet_charge_type = "PayByTraffic"
  tags                 = local.common_tags
}

# ---------- NAT 网关 ----------
resource "alicloud_nat_gateway" "main" {
  vpc_id        = alicloud_vpc.main.id
  specification = "Small"
  name          = "${local.resource_prefix}-nat"
  description   = "NAT gateway for FRD prod VPC egress"
  tags          = local.common_tags
}

resource "alicloud_eip_association" "nat" {
  allocation_id = alicloud_eip_address.nat.id
  instance_id   = alicloud_nat_gateway.main.id
}

# ---------- SNAT 条目（私网出口） ----------
resource "alicloud_snat_entry" "private" {
  snat_table_id     = alicloud_nat_gateway.main.snat_table_ids[0]
  source_vswitch_id = alicloud_vswitch.private.id
  snat_ip           = alicloud_eip_address.nat.ip_address
}

resource "alicloud_snat_entry" "db" {
  snat_table_id     = alicloud_nat_gateway.main.snat_table_ids[0]
  source_vswitch_id = alicloud_vswitch.db.id
  snat_ip           = alicloud_eip_address.nat.ip_address
}

# ---------- 安全组（按 role 分组） ----------
# 业务安全组（API/规则/案件/Worker）
resource "alicloud_security_group" "app" {
  name        = "${local.resource_prefix}-sg-app"
  description = "FRD application tier (backend/worker/ML/GNN)"
  vpc_id      = alicloud_vpc.main.id
  tags        = local.common_tags
}

resource "alicloud_security_group_rule" "app_ingress_http" {
  type              = "ingress"
  ip_protocol       = "tcp"
  port_range        = "8000/8000"
  security_group_id = alicloud_security_group.app.id
  cidr_ip           = var.vswitch_private_cidr
}

# 数据库安全组
resource "alicloud_security_group" "db" {
  name        = "${local.resource_prefix}-sg-db"
  description = "FRD database tier (PostgreSQL/Redis/Neo4j)"
  vpc_id      = alicloud_vpc.main.id
  tags        = local.common_tags
}

resource "alicloud_security_group_rule" "db_ingress_pg_from_app" {
  type                     = "ingress"
  ip_protocol              = "tcp"
  port_range               = "5432/5432"
  security_group_id        = alicloud_security_group.db.id
  source_security_group_id = alicloud_security_group.app.id
}

resource "alicloud_security_group_rule" "db_ingress_redis_from_app" {
  type                     = "ingress"
  ip_protocol              = "tcp"
  port_range               = "6379/6379"
  security_group_id        = alicloud_security_group.db.id
  source_security_group_id = alicloud_security_group.app.id
}

resource "alicloud_security_group_rule" "db_ingress_neo4j_from_app" {
  type                     = "ingress"
  ip_protocol              = "tcp"
  port_range               = "7687/7687"
  security_group_id        = alicloud_security_group.db.id
  source_security_group_id = alicloud_security_group.app.id
}
