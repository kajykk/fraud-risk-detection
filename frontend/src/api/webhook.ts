/**
 * Webhook API（对齐 D05 §11）
 */
import { get, post, put, del } from './request'
import type { PageQuery, PageResult } from '@/types/api'
import type { WebhookStatus, WebhookDeliveryStatus } from '@/types/enum'

/** Webhook 列表项（D05 §11.2） */
export interface WebhookListItem {
  id: string
  url: string
  events: string[]
  status: WebhookStatus
  created_at: string
  last_delivery_at?: string
  last_delivery_status?: WebhookDeliveryStatus
}

/** Webhook 详情（D05 §11.3） */
export interface WebhookDetail extends WebhookListItem {
  secret_hash: string
  updated_at: string
  recent_deliveries: WebhookDelivery[]
}

/** 投递记录（D05 §11.7） */
export interface WebhookDelivery {
  delivery_id: string
  event_id: string
  event_type: string
  webhook_id: string
  status: WebhookDeliveryStatus
  is_test: boolean
  attempts: WebhookDeliveryAttempt[]
  delivered_at?: string
  dead_lettered_at?: string
  dead_letter_reason?: string
}

export interface WebhookDeliveryAttempt {
  attempt_no: number
  sent_at: string
  response_code: number
  response_body_snippet?: string
  latency_ms?: number
  next_retry_at?: string | null
}

/** 注册 Webhook（D05 §11.1） */
export function createWebhook(payload: {
  url: string
  events: string[]
  secret: string
  challenge_expected?: boolean
}) {
  return post<WebhookListItem>('/webhooks', payload, {
    headers: { 'X-Idempotency-Key': crypto.randomUUID() }
  })
}

/** Webhook 列表（D05 §11.2） */
export function listWebhooks(query?: PageQuery) {
  return get<PageResult<WebhookListItem>>('/webhooks', query as Record<string, unknown>)
}

/** Webhook 详情（D05 §11.3） */
export function getWebhook(id: string) {
  return get<WebhookDetail>(`/webhooks/${id}`)
}

/** 更新 Webhook（D05 §11.4） */
export function updateWebhook(
  id: string,
  payload: { url: string; events: string[]; secret?: string; challenge_expected?: boolean }
) {
  return put<WebhookListItem>(`/webhooks/${id}`, payload)
}

/** 注销 Webhook（D05 §11.5） */
export function deleteWebhook(id: string) {
  return del<void>(`/webhooks/${id}`)
}

/** 测试投递（D05 §11.6） */
export function testWebhook(id: string, payload: { event_type: string; test_payload?: Record<string, unknown> }) {
  return post<{ delivery_id: string; status: string; signature_header: string }>(
    `/webhooks/${id}/test`,
    payload
  )
}

/** 投递记录（D05 §11.7） */
export function listWebhookDeliveries(
  id: string,
  query: PageQuery & {
    event_type?: string
    status?: WebhookDeliveryStatus
    start_time?: string
    end_time?: string
  }
) {
  return get<PageResult<WebhookDelivery>>(`/webhooks/${id}/deliveries`, query as Record<string, unknown>)
}
