/**
 * 交易 / 评分 / SHAP 类型
 * 对齐 D05 §4（交易反欺诈接口）与 baseline §4.1 transactions 表
 */
import type {
  Decision,
  RiskBand,
  TxType,
  Channel,
  ShapStatus,
  TaskStatus,
  FeedbackLabel
} from './enum'

/** 评分请求（D05 §4.1） */
export interface ScoreRequest {
  external_tx_id: string
  tx_type: TxType
  amount: number
  currency: string
  occurred_at: string
  card_token: string
  card_bin: string
  card_last4: string
  merchant_id?: string
  mcc?: string
  merchant_category?: string
  acquirer_id?: string
  device_fingerprint_hash?: string
  ip_address?: string
  ip_geo?: { country: string; city?: string }
  user_id: string
  user_created_at?: string
  channel?: Channel
  is_3ds_verified?: boolean
  shipping_country?: string
  billing_country?: string
  note_text?: string
  metadata?: Record<string, unknown>
}

/** 评分响应（D05 §4.1） */
export interface ScoreResponse {
  decision: Decision
  risk_score: number
  risk_band: RiskBand
  model_version: string
  rule_hits: RuleHit[]
  explainability: Explainability
  latency_ms: number
  case_id: string | null
  decision_id: string
}

export interface RuleHit {
  rule_id: string
  rule_name: string
  severity: 'INFO' | 'WARN' | 'BLOCK'
}

export interface Explainability {
  model_contribution: number
  rule_contribution: number
  shap_status: ShapStatus
  shap_task_id?: string
}

/** 异步评分任务（D05 §4.2-4.3） */
export interface AsyncScoreTask {
  task_id: string
  status: TaskStatus
  estimated_seconds?: number
  callback_event?: string
  result?: ScoreResponse
  created_at?: string
  completed_at?: string
}

/** 交易详情（D05 §4.6） */
export interface TransactionDetail {
  external_tx_id: string
  decision: Decision
  risk_score: number
  risk_band: RiskBand
  model_version: string
  rule_hits: RuleHit[]
  explainability: Explainability
  tx_type: TxType
  channel?: Channel
  is_3ds_verified?: boolean
  user_created_at?: string
  acquirer_id?: string
  shipping_country?: string
  billing_country?: string
  case_id?: string | null
  decision_id: string
  created_at: string
}

/** 交易列表查询参数（D05 §5.3） */
export interface TransactionQuery {
  external_tx_id?: string
  decision?: Decision
  risk_band?: RiskBand
  merchant_id?: string
  card_bin?: string
  model_version?: string
  start_time?: string
  end_time?: string
  min_amount?: number
  max_amount?: number
  channel?: Channel
  tx_type?: TxType
}

/** SHAP 计算结果（D05 §4.9） */
export interface ShapResult {
  shap_task_id: string
  decision_id: string
  model_id: string
  base_value: number
  prediction: number
  features: ShapFeature[]
  completed_at: string
}

export interface ShapFeature {
  name: string
  value: number
  shap: number
}

/** 反馈真实标签（D05 §4.5） */
export interface FeedbackRequest {
  external_tx_id: string
  label: FeedbackLabel
  label_source: 'CHARGEBACK' | 'MANUAL_REVIEW' | 'POLICE_REPORT' | 'EXTERNAL_LIST'
  labeled_at: string
  evidence?: string
}

/** 仪表盘 KPI 卡片数据（占位） */
export interface DashboardKpi {
  today_transactions: number
  blocked_count: number
  case_count: number
  model_auc: number
  p99_latency_ms: number
  drift_psi_7d: number
  fraud_loss_prevented_cents: number
  actual_loss_cents: number
  pass_rate: number
  appeal_count: number
}
