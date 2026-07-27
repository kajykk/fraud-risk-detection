/**
 * ML 模型治理类型
 * 对齐 D05 §6（ML 模型接口）与 D06 §8（ML 模型治理）
 */
import type { ModelStatus, ModelType, DriftSeverity, DriftMetric } from './enum'

/** 模型列表项（D05 §6.1） */
export interface ModelListItem {
  model_id: string
  name: string
  version: string
  type: ModelType
  status: ModelStatus
  auc?: number
  precision_at_1pct?: number
  recall_at_1pct?: number
  trained_at?: string
  promoted_at?: string
  traffic_share?: number
  canary_started_at?: string
}

/** 模型指标 */
export interface ModelMetrics {
  auc: number
  precision_at_1pct: number
  recall_at_1pct: number
  psi_7d?: number
  pr_auc?: number
  ks?: number
  f1?: number
  mcc?: number
}

/** 模型详情（D05 §6.3） */
export interface ModelDetail extends ModelListItem {
  artifacts_path: string
  artifacts_sha256: string
  entrypoint?: string
  runtime?: string
  metrics: ModelMetrics
  feature_schema_path?: string
  registered_at?: string
  description?: string
}

/** 注册模型请求（D05 §6.2） */
export interface RegisterModelRequest {
  name: string
  version: string
  type: ModelType
  artifacts_path: string
  artifacts_sha256: string
  entrypoint?: string
  runtime?: string
  metrics: ModelMetrics
  feature_schema_path?: string
  trained_at: string
  description?: string
}

/** 更新模型元数据请求（D05 §6.4） */
export interface UpdateModelRequest {
  description?: string
  feature_schema_path?: string
  entrypoint?: string
}

/** 启动金丝雀请求（D05 §6.6） */
export interface StartCanaryRequest {
  candidate_model_id: string
  traffic_percentage: number
  rollback_thresholds?: {
    precision_drop?: number
    latency_p99_ms?: number
    error_rate?: number
  }
  observation_hours?: number
  approver_id: string
}

/** 晋升模型请求（D05 §6.7） */
export interface PromoteModelRequest {
  approver_id: string
  promotion_report_ref?: string
}

/** 回滚模型请求（D05 §6.8） */
export interface RollbackModelRequest {
  target_model_id: string
  reason: string
  approver_id: string
}

/** 退役模型请求（D05 §6.9） */
export interface RetireModelRequest {
  reason: string
  approver_id: string
  data_retention_days?: number
}

/** 模型漂移指标（D05 §6.10） */
export interface ModelDrift {
  model_id: string
  drift_status: DriftSeverity
  psi_1d: number
  psi_7d: number
  kl_divergence: number
  last_checked_at: string
  feature_drifts: FeatureDrift[]
}

export interface FeatureDrift {
  feature: string
  psi: number
  status: 'HEALTHY' | 'WARNING' | 'CRITICAL'
  metric?: DriftMetric
}

/** 金丝雀发布状态（D05 §10.3） */
export interface CanaryStatus {
  canary_id: string
  candidate_model_id: string
  baseline_model_id: string
  stage: 1 | 2 | 3
  traffic_percentage: number
  status: 'RUNNING' | 'PASSED' | 'ROLLED_BACK'
  started_at: string
  observation_hours: number
  metrics_snapshot?: ModelMetrics
}

/** Kill Switch 状态（D03 §4.8 四级分级） */
export interface KillSwitchState {
  level: 'L1_GLOBAL' | 'L2_MODEL' | 'L3_MODAL' | 'L4_RULE'
  scope: string
  active: boolean
  triggered_at?: string
  triggered_by?: string
  reason?: string
  duration_minutes?: number
  cooldown_until?: string
}
