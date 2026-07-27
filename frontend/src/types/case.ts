/**
 * 案件管理类型
 * 对齐 D05 §8（案件管理接口）与 D06 §6（案件管理）
 */
import type { CaseStatus, CaseLevel } from './enum'

/** 案件列表查询参数（D05 §8.1） */
export interface CaseQuery {
  status?: CaseStatus
  priority?: CaseLevel
  assignee_id?: string
  created_after?: string
  created_before?: string
}

/** 案件列表项 */
export interface CaseListItem {
  case_id: string
  external_tx_id?: string
  title?: string
  status: CaseStatus
  priority: CaseLevel
  assignee_id?: string
  assignee_name?: string
  tags: string[]
  sla_deadline?: string
  created_at: string
  updated_at: string
}

/** 案件详情（D05 §8.3） */
export interface CaseDetail extends CaseListItem {
  description: string
  related_tx_ids: string[]
  related_community_id?: string
  related_account_ids: string[]
  loss_amount_cents?: number
  recovery_amount_cents?: number
  reportable_to_aml?: boolean
  conclusion?: 'CONFIRMED_FRAUD' | 'FALSE_ALARM' | 'INCONCLUSIVE'
  closed_at?: string
  closed_by?: string
  close_comment?: string
}

/** 创建案件请求（D05 §8.2） */
export interface CreateCaseRequest {
  external_tx_id?: string
  priority: CaseLevel
  assignee_id?: string
  description: string
  tags?: string[]
}

/** 更新案件请求（D05 §8.4） */
export interface UpdateCaseRequest {
  status?: CaseStatus
  priority?: CaseLevel
  assignee_id?: string
  comment?: string
}

/** 关闭案件请求（D05 §8.6） */
export interface CloseCaseRequest {
  conclusion: 'CONFIRMED_FRAUD' | 'FALSE_ALARM' | 'INCONCLUSIVE'
  loss_amount?: number
  recovery_amount?: number
  reportable_to_aml?: boolean
  comment?: string
}

/** 案件备注 */
export interface CaseComment {
  comment_id: string
  case_id: string
  author_id: string
  author_name: string
  content: string
  mentions: string[]
  created_at: string
  updated_at?: string
}

/** 案件时间线条目（D05 §8.7） */
export interface CaseTimelineEvent {
  event_id: string
  event_type: 'CREATED' | 'ASSIGNED' | 'STATUS_CHANGED' | 'COMMENTED' | 'CLOSED' | 'SLA_ESCALATED'
  actor_id: string
  actor_name: string
  description: string
  before?: Record<string, unknown>
  after?: Record<string, unknown>
  created_at: string
}

/** SLA 标准（D06 §6.3.3） */
export interface SlaStandard {
  priority: CaseLevel
  response_sla_minutes: number
  resolution_sla_minutes: number
}
