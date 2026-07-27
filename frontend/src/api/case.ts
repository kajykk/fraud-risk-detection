/**
 * 案件管理 API（对齐 D05 §8）
 */
import { get, post, patch } from './request'
import type { PageQuery, PageResult } from '@/types/api'
import type {
  CaseQuery,
  CaseListItem,
  CaseDetail,
  CreateCaseRequest,
  UpdateCaseRequest,
  CloseCaseRequest,
  CaseComment,
  CaseTimelineEvent
} from '@/types/case'

/** 案件列表（D05 §8.1） */
export function listCases(query: CaseQuery & PageQuery) {
  return get<PageResult<CaseListItem>>('/cases', query as Record<string, unknown>)
}

/** 案件详情（D05 §8.3） */
export function getCase(caseId: string) {
  return get<CaseDetail>(`/cases/${caseId}`)
}

/** 创建案件（D05 §8.2） */
export function createCase(payload: CreateCaseRequest) {
  return post<CaseDetail>('/cases', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 更新案件（D05 §8.4） */
export function updateCase(caseId: string, payload: UpdateCaseRequest) {
  return patch<CaseDetail>(`/cases/${caseId}`, payload)
}

/** 添加备注（D05 §8.5） */
export function addCaseComment(caseId: string, content: string, mentions: string[] = []) {
  return post<CaseComment>(`/cases/${caseId}/comments`, { content, mentions })
}

/** 关闭案件（D05 §8.6） */
export function closeCase(caseId: string, payload: CloseCaseRequest) {
  return post<CaseDetail>(`/cases/${caseId}/close`, payload)
}

/** 案件时间线（D05 §8.7） */
export function getCaseTimeline(caseId: string) {
  return get<CaseTimelineEvent[]>(`/cases/${caseId}/timeline`)
}

/** 案件备注列表 */
export function listCaseComments(caseId: string) {
  return get<CaseComment[]>(`/cases/${caseId}/comments`)
}
