/**
 * PIPL 数据主体权利 API（对齐 D05 §13，/api/v1/pipl/* 命名空间）
 * 对齐 baseline §7.1
 */
import { get, post } from './request'
import type { ConsentStatus, ConsentPurpose } from '@/types/enum'

/** 同意记录（D05 §13.1） */
export interface ConsentRecord {
  consent_id: string
  user_id: string
  purpose: ConsentPurpose
  legal_basis: string
  consent_type: 'EXPLICIT' | 'IMPLICIT_BY_ACTION'
  status: ConsentStatus
  scope: string[]
  granted_at: string
  expires_at?: string
  withdrawn_at?: string
  policy_version: string
  evidence_ref?: string
}

/** 同意列表响应（D05 §13.3） */
export interface ConsentListResult {
  user_id: string
  items: ConsentRecord[]
  summary: { active_count: number; withdrawn_count: number; expired_count: number }
  page: number
  page_size: number
  total: number
}

/** 数据导出任务（D05 §13.4-13.5） */
export interface DataExportTask {
  task_id: string
  user_id: string
  status: 'PROCESSING' | 'READY' | 'FAILED' | 'EXPIRED'
  scope?: string[]
  format?: 'JSON' | 'CSV' | 'XLSX'
  download_url?: string
  expires_at?: string
  estimated_seconds?: number
  created_at?: string
  completed_at?: string
  callback_event?: string
}

/** 删除请求（D05 §13.6-13.7） */
export interface DeletionRequest {
  request_id: string
  user_id: string
  status: 'PENDING_REVIEW' | 'APPROVED' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'PARTIALLY_COMPLETED'
  scope: string[]
  deleted_count?: number
  anonymized_count?: number
  retained_count?: number
  retention_reason?: string
  legal_hold_review?: { required: boolean; reviewer_id?: string; reviewed_at?: string }
  estimated_seconds?: number
  created_at?: string
  completed_at?: string
  callback_event?: string
}

/** 更正请求（D05 §13.8） */
export interface RectificationRequest {
  request_id: string
  user_id: string
  status: 'PENDING_REVIEW' | 'APPROVED' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'PARTIALLY_COMPLETED'
  correction_count: number
  estimated_seconds?: number
  callback_event?: string
}

/** 记录同意（D05 §13.1） */
export function grantConsent(payload: {
  user_id: string
  verification_token: string
  consent_type: 'EXPLICIT' | 'IMPLICIT_BY_ACTION'
  purpose: ConsentPurpose
  legal_basis: string
  scope: string[]
  policy_version: string
  expires_at?: string
  evidence: { channel: string; user_agent: string; ip_address: string; signed_text_hash: string }
}) {
  return post<ConsentRecord>('/pipl/consent', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 撤回同意（D05 §13.2） */
export function withdrawConsent(payload: {
  user_id: string
  verification_token: string
  consent_id: string
  withdrawal_reason?: 'NO_LONGER_NEEDED' | 'SERVICE_CANCELLED' | 'PRIVACY_CONCERN' | 'OTHER'
  effective_immediately?: boolean
}) {
  return post<ConsentRecord>('/pipl/consent/withdraw', payload)
}

/** 查询用户同意状态（D05 §13.3） */
export function getConsent(
  userId: string,
  params: { purpose?: ConsentPurpose; status?: ConsentStatus; include_history?: boolean } = {}
) {
  return get<ConsentListResult>(`/pipl/consent/${userId}`, params as Record<string, unknown>)
}

/** 申请数据导出（D05 §13.4） */
export function requestDataExport(params: {
  user_id: string
  verification_token: string
  scope: string
  format?: 'JSON' | 'CSV' | 'XLSX'
  start_date?: string
  end_date?: string
  delivery_method?: 'OSS_PRESIGNED_URL' | 'WEBHOOK'
}) {
  return get<DataExportTask>('/pipl/data-export', params as Record<string, unknown>)
}

/** 查询导出状态（D05 §13.5） */
export function getDataExportStatus(taskId: string) {
  return get<DataExportTask>(`/pipl/data-export/${taskId}/status`)
}

/** 申请数据删除（D05 §13.6） */
export function requestDeletion(payload: {
  user_id: string
  verification_token: string
  scope: string[]
  reason: 'USER_REQUEST' | 'CONSENT_WITHDRAWN' | 'DATA_RETENTION_EXPIRED' | 'LEGAL_OBLIGATION_END'
  retain_for_aml?: boolean
  legal_hold_review?: boolean
}) {
  return post<DeletionRequest>('/pipl/deletion', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 查询删除状态（D05 §13.7） */
export function getDeletionStatus(requestId: string) {
  return get<DeletionRequest>(`/pipl/deletion/${requestId}/status`)
}

/** 数据更正请求（D05 §13.8） */
export function requestRectification(payload: {
  user_id: string
  verification_token: string
  corrections: {
    resource_type: 'TRANSACTION' | 'USER_PROFILE' | 'CASE' | 'CONSENT'
    resource_id: string
    field: string
    current_value: unknown
    corrected_value: unknown
    evidence: string
  }[]
  reason: 'DATA_INACCURATE' | 'DATA_OUTDATED' | 'DATA_INCOMPLETE' | 'USER_REQUEST'
}) {
  return post<RectificationRequest>('/pipl/rectification', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}
