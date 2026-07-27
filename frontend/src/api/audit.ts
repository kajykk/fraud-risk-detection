/**
 * 审计日志 API（对齐 D06 §11 审计与合规）
 * 依据 D05 §3.4：AUDITOR / COMPLIANCE_OFFICER / TENANT_ADMIN 可读
 */
import { get } from './request'
import type { PageQuery, PageResult } from '@/types/api'

/** 审计日志查询参数 */
export interface AuditLogQuery {
  actor_id?: string
  resource_type?: string
  resource_id?: string
  action?: string
  start_time?: string
  end_time?: string
  trace_id?: string
}

/** 审计日志条目 */
export interface AuditLogItem {
  log_id: string
  actor_id: string
  actor_name?: string
  actor_role?: string
  tenant_id: string
  action: string
  resource_type: string
  resource_id?: string
  before?: Record<string, unknown>
  after?: Record<string, unknown>
  ip_address?: string
  user_agent?: string
  trace_id?: string
  request_id?: string
  result: 'SUCCESS' | 'FAILURE' | 'DENIED'
  occurred_at: string
  hash_chain_prev?: string
  hash_current?: string
}

/** 审计日志列表（对齐 D05 §2.3 通用响应 + §2.4 分页） */
export function listAuditLogs(query: AuditLogQuery & PageQuery) {
  return get<PageResult<AuditLogItem>>('/audit-logs', query as Record<string, unknown>)
}

/** 审计日志详情 */
export function getAuditLog(logId: string) {
  return get<AuditLogItem>(`/audit-logs/${logId}`)
}
