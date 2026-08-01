/**
 * WebSocket 客户端
 * 对齐 D05 §2.8（WebSocket 通道，鉴权 ?access_token={jwt}）
 *
 * 适用事件（D05 §2.8）：
 * - transaction.shap_ready
 * - transaction.analysis_completed
 * - report.ready
 * - privacy.export.ready
 * - privacy.deletion.completed
 * - gang.detected
 */
import { ref, onScopeDispose } from 'vue'

export type WsEventType =
  | 'transaction.shap_ready'
  | 'transaction.analysis_completed'
  | 'report.ready'
  | 'privacy.export.ready'
  | 'privacy.deletion.completed'
  | 'privacy.rectification.completed'
  | 'gang.detected'
  | string

export interface WsMessage<T = unknown> {
  event_id: string
  event_type: WsEventType
  tenant_id: string
  occurred_at: string
  data: T
}

type Handler<T = unknown> = (msg: WsMessage<T>) => void

const RECONNECT_INTERVAL = 5_000
const HEARTBEAT_INTERVAL = 30_000

/** 创建 WebSocket 客户端（单例，需调用方持有引用） */
export function useWebSocket(tokenRef: () => string | null) {
  const connected = ref(false)
  let ws: WebSocket | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const handlers = new Map<WsEventType, Set<Handler>>()

  function buildUrl(): string | null {
    const token = tokenRef()
    if (!token) return null
    const base = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8002/api/v1/ws'
    const sep = base.includes('?') ? '&' : '?'
    return `${base}${sep}access_token=${encodeURIComponent(token)}`
  }

  function on(event: WsEventType, handler: Handler) {
    if (!handlers.has(event)) handlers.set(event, new Set())
    handlers.get(event)!.add(handler)
  }

  function off(event: WsEventType, handler: Handler) {
    handlers.get(event)?.delete(handler)
  }

  function dispatch(msg: WsMessage) {
    const set = handlers.get(msg.event_type)
    set?.forEach((h) => {
      try {
        h(msg)
      } catch (err) {
        console.error('[WS] handler error:', err)
      }
    })
  }

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, HEARTBEAT_INTERVAL)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function connect() {
    const url = buildUrl()
    if (!url) return
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

    try {
      ws = new WebSocket(url)
    } catch (err) {
      console.error('[WS] connect error:', err)
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      connected.value = true
      startHeartbeat()
      // 订阅过滤
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'subscribe',
            event_types: Array.from(handlers.keys())
          })
        )
      }
    }

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage
        if (msg.event_type) dispatch(msg)
      } catch (err) {
        console.error('[WS] parse message error:', err)
      }
    }

    ws.onerror = (err) => {
      console.error('[WS] error:', err)
    }

    ws.onclose = () => {
      connected.value = false
      stopHeartbeat()
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, RECONNECT_INTERVAL)
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    stopHeartbeat()
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    connected.value = false
  }

  onScopeDispose(() => disconnect())

  return {
    connected,
    connect,
    disconnect,
    on,
    off
  }
}
