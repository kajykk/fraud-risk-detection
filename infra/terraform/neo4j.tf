# ============================================================
# Neo4j 社区版（自建 ECS，单主 + 异地 OSS 备份）
# 依据：FRD-D10-V1.1 §3.2 / §7.3 Neo4j
# 规格：4C16G + 200GB SSD（依据 D10 §3.2）
# 内存：堆 8GB + 页缓存 6GB（依据 D10 §7.3）
# 说明：生产首年使用社区版降本（依据基准 §6.1），第 2 年评估升级 Enterprise Causal Cluster
# ============================================================

# ---------- Neo4j ECS 实例 ----------
resource "alicloud_instance" "neo4j" {
  instance_type           = var.neo4j_instance_type   # ecs.g6.xlarge 4C16G
  image_id                = data.alicloud_images.ubuntu.images[0].id
  instance_name           = "${local.resource_prefix}-neo4j"
  host_name               = "frd-neo4j"
  vswitch_id              = alicloud_vswitch.db.id
  zone_id                 = var.availability_zone
  security_groups         = [alicloud_security_group.db.id]
  internet_max_bandwidth_out = 0   # 不分配公网
  instance_charge_type    = "Postpaid"

  system_disk_category = "cloud_essd"
  system_disk_size     = 100

  # 数据盘（200GB SSD，依据 D10 §3.2）
  data_disks {
    name             = "${local.resource_prefix}-neo4j-data"
    size             = var.neo4j_storage
    category         = "cloud_essd"
    delete_with_instance = true
  }

  password = var.ack_node_password
  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -euo pipefail

    # 挂载数据盘
    mkdir -p /data/neo4j
    mkfs.ext4 /dev/vdb
    mount /dev/vdb /data/neo4j
    echo "/dev/vdb /data/neo4j ext4 defaults 0 2" >> /etc/fstab

    # 安装 Docker
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker

    # 运行 Neo4j 5 社区版容器
    docker run -d \
      --name neo4j \
      --restart unless-stopped \
      --network host \
      -e NEO4J_AUTH=neo4j/${var.neo4j_password} \
      -e NEO4J_PLUGINS='["apoc"]' \
      -e NEO4J_dbms_memory_heap_max__size=8G \
      -e NEO4J_dbms_memory_pagecache_size=6G \
      -e NEO4J_dbms_directories_data=/data/neo4j/data \
      -e NEO4J_dbms_directories_logs=/data/neo4j/logs \
      -v /data/neo4j:/data/neo4j \
      neo4j:5.20-community

    # 每日备份脚本（02:00 CST，归档到 OSS）
    cat > /usr/local/bin/neo4j-backup.sh <<'BACKUP'
    #!/bin/bash
    set -euo pipefail
    DATE=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="/tmp/neo4j-backup-${DATE}.tar.gz"
    docker exec neo4j neo4j-admin database dump neo4j --to-path=/data/neo4j/dumps
    tar czf "${BACKUP_FILE}" -C /data/neo4j/dumps .
    # 上传到 OSS（需安装 ossutil 并配置凭证）
    ossutil cp "${BACKUP_FILE}" oss://${var.oss_bucket_name}/neo4j/daily/
    rm -f "${BACKUP_FILE}"
    find /data/neo4j/dumps -mtime +7 -delete
    BACKUP
    chmod +x /usr/local/bin/neo4j-backup.sh
    echo "0 18 * * * /usr/local/bin/neo4j-backup.sh" | crontab -
  EOF
  )

  tags = local.common_tags
}

# ---------- Ubuntu 镜像数据源 ----------
data "alicloud_images" "ubuntu" {
  most_recent = true
  owners      = "system"
  name_regex  = "^ubuntu_22.*"
}

# ---------- Neo4j ECS 内网 IP 输出 ----------
# 实际内网 IP 通过 alicloud_instance.neo4j.private_ip 获取
# K8s 集群通过 ExternalName Service 或 CoreDNS 解析访问
