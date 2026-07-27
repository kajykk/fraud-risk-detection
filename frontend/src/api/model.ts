/**
 * ML 模型治理 API（对齐 D05 §6 + §10 治理接口）
 */
import { get, post, put, del } from './request'
import type { PageQuery, PageResult } from '@/types/api'
import type {
  ModelListItem,
  ModelDetail,
  RegisterModelRequest,
  UpdateModelRequest,
  StartCanaryRequest,
  PromoteModelRequest,
  RollbackModelRequest,
  RetireModelRequest,
  ModelDrift,
  CanaryStatus,
  KillSwitchState
} from '@/types/model'

/** 模型列表（D05 §6.1） */
export function listModels(query?: PageQuery) {
  return get<PageResult<ModelListItem>>('/models', query as Record<string, unknown>)
}

/** 模型详情（D05 §6.3） */
export function getModel(modelId: string) {
  return get<ModelDetail>(`/models/${modelId}`)
}

/** 注册模型（D05 §6.2） */
export function registerModel(payload: RegisterModelRequest) {
  return post<{ model_id: string; status: string }>('/models', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 更新模型元数据（D05 §6.4） */
export function updateModel(modelId: string, payload: UpdateModelRequest) {
  return put<{ model_id: string; status: string }>(`/models/${modelId}`, payload)
}

/** 退役模型（D05 §6.5） */
export function deleteModel(modelId: string, reason: string, approverId: string) {
  return del<{ model_id: string; status: string }>(
    `/models/${modelId}`,
    { params: { reason, approver_id: approverId } }
  )
}

/** 启动金丝雀（D05 §6.6） */
export function startCanary(modelId: string, payload: StartCanaryRequest) {
  return post<{ model_id: string; status: string }>(`/models/${modelId}/canary`, payload)
}

/** 晋升金丝雀（D05 §6.7） */
export function promoteModel(modelId: string, payload: PromoteModelRequest) {
  return post<{ model_id: string; status: string }>(`/models/${modelId}/promote`, payload)
}

/** 紧急回滚（D05 §6.8） */
export function rollbackModel(modelId: string, payload: RollbackModelRequest) {
  return post<{ model_id: string; status: string }>(`/models/${modelId}/rollback`, payload)
}

/** 显式退役（D05 §6.9） */
export function retireModel(modelId: string, payload: RetireModelRequest) {
  return post<{ model_id: string; status: string; artifacts_retained_until?: string }>(
    `/models/${modelId}/retire`,
    payload
  )
}

/** 漂移指标（D05 §6.10） */
export function getModelDrift(modelId: string) {
  return get<ModelDrift>(`/models/${modelId}/drift`)
}

/** 金丝雀发布状态列表（D05 §10.3） */
export function listCanaries() {
  return get<CanaryStatus[]>('/governance/canaries')
}

/** 推进金丝雀流量（D05 §10.4） */
export function advanceCanary(canaryId: string) {
  return post<{ canary_id: string; stage: number; traffic_percentage: number }>(
    `/governance/canaries/${canaryId}/advance`
  )
}

/** 回滚金丝雀（D05 §10.5） */
export function rollbackCanary(canaryId: string) {
  return post<{ canary_id: string; status: string }>(`/governance/canaries/${canaryId}/rollback`)
}

/** Kill Switch 紧急熔断（D05 §10.2 / D03 §4.8 四级分级） */
export function triggerKillSwitch(payload: {
  level: 'L1_GLOBAL' | 'L2_MODEL' | 'L3_MODAL' | 'L4_RULE'
  scope: string
  reason: string
  duration_minutes: number
  approver_id: string
}) {
  return post<{ active: boolean; triggered_at: string }>('/governance/kill-switch', payload)
}

/** 查询 Kill Switch 状态 */
export function getKillSwitchState(scope?: string) {
  return get<KillSwitchState[]>('/governance/kill-switch', scope ? { scope } : undefined)
}
