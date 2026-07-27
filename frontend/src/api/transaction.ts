/**
 * 交易评分 API（对齐 D05 §4）
 */
import { get, post } from './request'
import type { PageQuery, PageResult } from '@/types/api'
import type {
  ScoreRequest,
  ScoreResponse,
  AsyncScoreTask,
  TransactionDetail,
  TransactionQuery,
  ShapResult,
  FeedbackRequest
} from '@/types/transaction'

/** 实时评分（D05 §4.1） */
export function scoreTransaction(payload: ScoreRequest) {
  return post<ScoreResponse>('/transactions/score', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** 异步深度评分（D05 §4.2） */
export function scoreAsync(payload: ScoreRequest & { analysis_depth?: 'STANDARD' | 'DEEP' }) {
  return post<AsyncScoreTask>('/transactions/score/async', payload)
}

/** 查询异步评分任务状态（D05 §4.3） */
export function getAsyncScoreTask(taskId: string) {
  return get<AsyncScoreTask>(`/transactions/score/tasks/${taskId}`)
}

/** 批量评分（D05 §4.4） */
export function scoreBatch(transactions: ScoreRequest[]) {
  return post<{ results: ScoreResponse[]; success_count: number; failure_count: number }>(
    '/transactions/score/batch',
    { transactions }
  )
}

/** 反馈真实标签（D05 §4.5） */
export function feedbackLabel(payload: FeedbackRequest) {
  return post<void>('/transactions/feedback', payload)
}

/** 查询交易详情（D05 §4.6） */
export function getTransaction(externalTxId: string) {
  return get<TransactionDetail>(`/transactions/${externalTxId}`)
}

/** 交易列表查询 */
export function listTransactions(query: TransactionQuery & PageQuery) {
  return get<PageResult<TransactionDetail>>('/transactions', query as Record<string, unknown>)
}

/** 触发 SHAP 异步计算（D05 §4.7） */
export function triggerShap(decisionId: string, payload?: { top_k?: number; model_id?: string }) {
  return post<{ shap_task_id: string; status: string; estimated_seconds?: number }>(
    `/scores/${decisionId}/shap`,
    payload
  )
}

/** 查询 SHAP 状态（D05 §4.8） */
export function getShapStatus(decisionId: string) {
  return get<{
    shap_task_id: string
    decision_id: string
    status: string
    progress: number
    result_url?: string
  }>(`/scores/${decisionId}/shap/status`)
}

/** 获取 SHAP 结果（D05 §4.9） */
export function getShapResult(decisionId: string) {
  return get<ShapResult>(`/scores/${decisionId}/shap/result`)
}
