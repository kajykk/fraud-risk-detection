# ============================================================
# 阿里云容器服务 Kubernetes（ACK）
# 依据：FRD-D10-V1.1 §4.2 / §3.2 生产环境资源规格 / §1.3 部署范围
# K8s 1.28，单 AZ 部署
# 节点池：API(4C8G×3) + Worker(4C8G×2) + ML(8C16G+GPU×2) + GNN(4C8G×2)
# ============================================================

# ---------- ACK 托管集群 ----------
resource "alicloud_cs_managed_kubernetes" "main" {
  name                 = var.ack_cluster_name
  cluster_spec         = "ack.pro.small"
  version              = var.ack_cluster_version
  worker_vswitch_ids   = [alicloud_vswitch.private.id]
  pod_cidr             = "10.1.0.0/16"
  service_cidr         = "10.2.0.0/16"
  new_nat_gateway      = false   # 已在 vpc.tf 单独创建
  enable_ssh           = true
  password             = var.ack_node_password
  install_cloud_monitor = true
  deletion_protection  = true
  # 安全：API Server 公网访问仅白名单
  api_server_public_ip_enabled = true
  control_plane_log_components = [
    "kcp",
    "ccm",
    "scheduler",
    "kubectl",
    "proxy",
  ]
  tags = local.common_tags
}

# ---------- API 节点池（4C8G × 3） ----------
resource "alicloud_cs_kubernetes_node_pool" "api" {
  cluster_id          = alicloud_cs_managed_kubernetes.main.id
  name                = "${local.resource_prefix}-api-pool"
  vswitch_ids         = [alicloud_vswitch.private.id]
  instance_types      = ["ecs.c6.xlarge"]   # 4C8G
  password            = var.ack_node_password
  desired_size        = 3
  min_size            = 3
  max_size            = 6   # Cluster Autoscaler 上限
  enable_auto_scaling = true
  system_disk_category = "cloud_essd"
  system_disk_size     = 120
  image_type          = "AliyunLinux3"
  node_labels = {
    "node-pool" = "api"
    "role"      = "api"
  }
  tags = local.common_tags
}

# ---------- Worker 节点池（4C8G × 2，Celery Worker/Beat） ----------
resource "alicloud_cs_kubernetes_node_pool" "worker" {
  cluster_id          = alicloud_cs_managed_kubernetes.main.id
  name                = "${local.resource_prefix}-worker-pool"
  vswitch_ids         = [alicloud_vswitch.private.id]
  instance_types      = ["ecs.c6.xlarge"]   # 4C8G
  password            = var.ack_node_password
  desired_size        = 2
  min_size            = 2
  max_size            = 6
  enable_auto_scaling = true
  system_disk_category = "cloud_essd"
  system_disk_size     = 120
  image_type          = "AliyunLinux3"
  node_labels = {
    "node-pool" = "worker"
    "role"      = "worker"
  }
  tags = local.common_tags
}

# ---------- ML 推理节点池（8C16G + GPU × 2） ----------
# 依据 D10 §3.2：ecs.gn6i-c4g1.xlarge（含 1×T4 GPU）
resource "alicloud_cs_kubernetes_node_pool" "ml" {
  cluster_id          = alicloud_cs_managed_kubernetes.main.id
  name                = "${local.resource_prefix}-ml-pool"
  vswitch_ids         = [alicloud_vswitch.private.id]
  instance_types      = ["ecs.gn6i-c4g1.xlarge"]
  password            = var.ack_node_password
  desired_size        = 2
  min_size            = 1
  max_size            = 3
  enable_auto_scaling = true
  system_disk_category = "cloud_essd"
  system_disk_size     = 200
  image_type          = "AliyunLinux3"
  # GPU 节点需安装 NVIDIA 驱动
  user_data = base64encode(<<-EOF
    #!/bin/bash
    echo "GPU node bootstrap for FRD ML pool"
  EOF
  )
  node_labels = {
    "node-pool" = "ml"
    "role"      = "ml"
    "nvidia.com/gpu" = "present"
  }
  node_taints {
    key    = "nvidia.com/gpu"
    value  = "present"
    effect = "NoSchedule"
  }
  tags = local.common_tags
}

# ---------- GNN 节点池（4C8G × 2） ----------
resource "alicloud_cs_kubernetes_node_pool" "gnn" {
  cluster_id          = alicloud_cs_managed_kubernetes.main.id
  name                = "${local.resource_prefix}-gnn-pool"
  vswitch_ids         = [alicloud_vswitch.private.id]
  instance_types      = ["ecs.c6.xlarge"]   # 4C8G
  password            = var.ack_node_password
  desired_size        = 2
  min_size            = 2
  max_size            = 4
  enable_auto_scaling = true
  system_disk_category = "cloud_essd"
  system_disk_size     = 120
  image_type          = "AliyunLinux3"
  node_labels = {
    "node-pool" = "gnn"
    "role"      = "gnn"
  }
  tags = local.common_tags
}
