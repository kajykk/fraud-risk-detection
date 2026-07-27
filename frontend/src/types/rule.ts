/**
 * 规则引擎类型
 * 对齐 D05 §5（规则引擎接口）与 baseline §3.4（规则状态/动作枚举）
 */
import type { RuleStatus, RuleAction, RuleSeverity, Channel } from './enum'

/** 规则列表查询参数（D05 §5.1） */
export interface RuleQuery {
  status?: RuleStatus
  action?: RuleAction
  channel?: Channel
  severity?: RuleSeverity
}

/** 规则列表项（D05 §5.1） */
export interface RuleListItem {
  rule_id: string
  name: string
  description?: string
  dsl: string
  severity: RuleSeverity
  action: RuleAction
  status: RuleStatus
  version: number
  hit_count_24h: number
  false_positive_rate: number
  created_at: string
  updated_at: string
}

/** 规则版本历史（D05 §5.3） */
export interface RuleVersion {
  version: number
  dsl: string
  status: RuleStatus
  change_summary?: string
  created_at: string
  created_by: string
}

/** 规则详情（D05 §5.3） */
export interface RuleDetail extends RuleListItem {
  valid_from?: string
  valid_to?: string | null
  scope?: { channels: Channel[] }
  published_at?: string
  published_by?: string
  versions: RuleVersion[]
}

/** 创建/更新规则请求（D05 §5.2 / §5.4） */
export interface UpsertRuleRequest {
  name: string
  description?: string
  dsl: string
  severity: RuleSeverity
  action: RuleAction
  valid_from?: string
  valid_to?: string | null
  scope?: { channels: Channel[] }
}

/** 创建新版本请求（D05 §5.6） */
export interface CreateRuleVersionRequest {
  dsl: string
  change_summary?: string
  severity?: RuleSeverity
  action?: RuleAction
}

/** 灰度推进请求（D05 §5.7） */
export interface PromoteRuleRequest {
  from_status: RuleStatus.DRAFT | RuleStatus.CANARY
  to_status: RuleStatus.CANARY | RuleStatus.ACTIVE
  canary_percentage?: number
  approver_id: string
  observation_hours?: number
  rollback_thresholds?: {
    false_positive_rate?: number
    precision_drop?: number
  }
}

/** 回滚请求（D05 §5.8） */
export interface RollbackRuleRequest {
  target_version?: number
  reason: string
  approver_id: string
}

/** DSL 校验请求（D05 §5.9） */
export interface ValidateRuleDslRequest {
  dsl: string
  sample_transactions?: string[]
}

/** DSL 校验响应 */
export interface ValidateRuleDslResult {
  valid: boolean
  syntax_errors: string[]
  sample_hits: { external_tx_id: string; matched: boolean; evaluated_at_ms: number }[]
}

/** 规则历史命中（D05 §5.11） */
export interface RuleHitRecord {
  hit_id: string
  rule_id: string
  external_tx_id: string
  decision: string
  risk_score: number
  occurred_at: string
}
