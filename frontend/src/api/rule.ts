/**
 * 规则引擎 API（对齐 D05 §5）
 */
import { get, post, put, del } from './request'
import type { PageQuery, PageResult } from '@/types/api'
import type {
  RuleQuery,
  RuleListItem,
  RuleDetail,
  UpsertRuleRequest,
  CreateRuleVersionRequest,
  PromoteRuleRequest,
  RollbackRuleRequest,
  ValidateRuleDslRequest,
  ValidateRuleDslResult,
  RuleHitRecord
} from '@/types/rule'

/** 规则列表（D05 §5.1） */
export function listRules(query: RuleQuery & PageQuery) {
  return get<PageResult<RuleListItem>>('/rules', query as Record<string, unknown>)
}

/** 规则详情（D05 §5.3） */
export function getRule(ruleId: string) {
  return get<RuleDetail>(`/rules/${ruleId}`)
}

/** 创建规则（D05 §5.2） */
export function createRule(payload: UpsertRuleRequest) {
  return post<{ rule_id: string; version: number; status: string }>('/rules', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 更新规则草稿（D05 §5.4） */
export function updateRule(ruleId: string, payload: UpsertRuleRequest) {
  return put<{ rule_id: string; version: number; status: string }>(`/rules/${ruleId}`, payload)
}

/** 软删除规则（D05 §5.5） */
export function deleteRule(ruleId: string) {
  return del<void>(`/rules/${ruleId}`)
}

/** 创建新版本（D05 §5.6） */
export function createRuleVersion(ruleId: string, payload: CreateRuleVersionRequest) {
  return post<{ rule_id: string; version: number; status: string; based_on_version: number }>(
    `/rules/${ruleId}/versions`,
    payload
  )
}

/** 灰度推进（D05 §5.7） */
export function promoteRule(ruleId: string, payload: PromoteRuleRequest) {
  return post<{ rule_id: string; version: number; from_status: string; to_status: string }>(
    `/rules/${ruleId}/promote`,
    payload
  )
}

/** 紧急回滚（D05 §5.8） */
export function rollbackRule(ruleId: string, payload: RollbackRuleRequest) {
  return post<{
    rule_id: string
    rolled_back_from_version: number
    rolled_back_to_version: number
    current_status: string
  }>(`/rules/${ruleId}/rollback`, payload)
}

/** DSL 校验与试运行（D05 §5.9） */
export function validateRuleDsl(ruleId: string, payload: ValidateRuleDslRequest) {
  return post<ValidateRuleDslResult>(`/rules/${ruleId}:validate`, payload)
}

/** 下线规则（D05 §5.10） */
export function retireRule(ruleId: string, reason: string) {
  return post<void>(`/rules/${ruleId}:retire`, { reason })
}

/** 规则历史命中（D05 §5.11） */
export function getRuleHits(ruleId: string, query: PageQuery & { start_time?: string; end_time?: string }) {
  return get<PageResult<RuleHitRecord>>(`/rules/${ruleId}/hits`, query as Record<string, unknown>)
}
