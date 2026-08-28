/**
 * Axios 实例 + 拦截器
 * 对齐 D05 §2.2（请求头）/ §2.6（HTTP 状态码）/ §12（错误码）
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

// ---------------------------------------------------------------------------
// Access Token 内存态管理（XSS 不可持久化窃取）
//
// - token 仅存于模块级变量，不落 localStorage/sessionStorage/非 HttpOnly Cookie；
// - 刷新凭证为 HttpOnly Cookie（同源自动携带）；
// - 跨标签页：BroadcastChannel 广播新 AT；刷新经 Web Locks 单飞串行，
//   锁内 15s 新鲜度短路避免旋转竞态（jti 重放保护）。
// ---------------------------------------------------------------------------
let accessToken: string | null = null
let lastRenewAt = 0

const LEGACY_STORAGE_KEY_TOKEN = 'frd_access_token'
const LEGACY_STORAGE_KEY_REFRESH_TOKEN = 'frd_refresh_token'

const authChannel: BroadcastChannel | null =
  typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('frd_auth') : null

if (authChannel) {
  authChannel.onmessage = (ev: MessageEvent) => {
    const msg = ev.data as { type?: string; token?: string }
    if (msg?.type === 'AT' && msg.token) {
      // 其他标签页完成旋转后广播的新 AT：直接采纳（不回广播）
      accessToken = msg.token
      lastRenewAt = Date.now()
    } else if (msg?.type === 'LOGOUT') {
      accessToken = null
    }
  }
}

/** 读取当前内存态 access token */
export function getAccessToken(): string | null {
  return accessToken
}

/** 写入 access token（broadcast=false 用于采纳他标签页广播，避免回环） */
export function setAccessToken(token: string | null, broadcast = true): void {
  accessToken = token
  if (token) {
    lastRenewAt = Date.now()
    if (broadcast && authChannel) {
      authChannel.postMessage({ type: 'AT', token })
    }
  }
}

/** 一次性清理历史版本遗留的本地 token 存储（迁移收口） */
export function purgeLegacyTokenStorage(): void {
  localStorage.removeItem(LEGACY_STORAGE_KEY_TOKEN)
  localStorage.removeItem(LEGACY_STORAGE_KEY_REFRESH_TOKEN)
}

function broadcastLogout(): void {
  authChannel?.postMessage({ type: 'LOGOUT' })
}

/** 生成 X-Request-ID（UUID v4） */
function genRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

const request: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Accept-Language': 'zh-CN'
  }
})

// 401 自动刷新：并发/跨标签页共享同一次旋转（Web Locks 单飞 + 新鲜度短路）
let refreshPromise: Promise<string | null> | null = null

function isAuthPath(url?: string): boolean {
  return !!url && /\/auth\/(login|refresh|token)/.test(url)
}

async function refreshAccessToken(): Promise<string | null> {
  const attempt = async (): Promise<string | null> => {
    // 锁内新鲜度检查：他标签页刚完成旋转时直接复用广播来的 AT，
    // 避免二次旋转触发后端 jti 重放判定
    if (accessToken && Date.now() - lastRenewAt < 15_000) {
      return accessToken
    }
    try {
      // 裸 axios 发送避免经过本拦截器（防递归）；RT 在 HttpOnly Cookie 中自动携带
      const res = await axios.post<ApiResponse<{ access_token: string; refresh_token?: string }>>(
        `${request.defaults.baseURL}/auth/refresh`,
        {},
        { headers: { 'X-Request-Id': genRequestId() } }
      )
      const data = res.data?.data
      if (!data?.access_token) return null
      setAccessToken(data.access_token)
      return data.access_token
    } catch {
      return null
    }
  }

  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
  if (locks?.request) {
    return locks.request('frd-refresh', attempt)
  }
  return attempt()
}

/** 清除本地会话并跳转登录（拦截器内使用，避免 import store 循环依赖） */
function redirectToLogin() {
  accessToken = null
  broadcastLogout()
  purgeLegacyTokenStorage()
  const current = window.location.pathname + window.location.search
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = `/login?redirect=${encodeURIComponent(current)}`
  }
}

// 请求拦截器：注入 Authorization Bearer token + X-Request-ID
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    if (accessToken && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${accessToken}`
    }
    if (!config.headers['X-Request-Id']) {
      config.headers['X-Request-Id'] = genRequestId()
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：401 跳转登录、统一错误提示
request.interceptors.response.use(
  (response) => {
    const data = response.data as ApiResponse
    // 业务错误（HTTP 200 但 code !== OK）
    if (data && data.code && data.code !== 'OK') {
      ElMessage.error(data.message || `业务错误：${data.code}`)
      return Promise.reject(new Error(data.message || data.code))
    }
    return response
  },
  (error) => {
    const status = error?.response?.status
    const respData = error?.response?.data as ApiResponse | undefined
    const config = error?.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined

    if (status === 401 && config && !config._retried && !isAuthPath(config.url)) {
      // 尝试自动刷新（跨标签页单飞）并重放请求一次
      refreshPromise = refreshPromise ?? refreshAccessToken()
      return refreshPromise.finally(() => {
        refreshPromise = null
      }).then((token) => {
        if (!token) {
          redirectToLogin()
          return Promise.reject(error)
        }
        config.headers = config.headers ?? {}
        config.headers.Authorization = `Bearer ${token}`
        config._retried = true
        return request(config)
      })
    }

    if (status === 401) {
      // 登录/刷新本身的 401：直接清除并跳转
      redirectToLogin()
      if (!isAuthPath(config?.url)) {
        ElMessage.error('登录已过期，请重新登录')
      }
      return Promise.reject(error)
    }

    if (status === 403) {
      ElMessage.error(respData?.message || '无权限访问该资源')
      return Promise.reject(error)
    }

    if (status === 429) {
      const retryAfter = error?.response?.headers?.['retry-after']
      ElMessage.warning(`请求被限流，请${retryAfter ? `${retryAfter}秒后` : '稍后'}重试`)
      return Promise.reject(error)
    }

    if (status >= 500) {
      ElMessage.error(respData?.message || '服务暂时不可用，请稍后重试')
      return Promise.reject(error)
    }

    ElMessage.error(respData?.message || error?.message || '请求失败')
    return Promise.reject(error)
  }
)

/** 通用 GET，返回 data 字段（已剥离 ApiResponse 外壳） */
export async function get<T = unknown>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.get<ApiResponse<T>>(url, { params, ...config })
  return res.data.data
}

/** 通用 POST */
export async function post<T = unknown>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.post<ApiResponse<T>>(url, body, config)
  return res.data.data
}

/** 通用 PUT */
export async function put<T = unknown>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.put<ApiResponse<T>>(url, body, config)
  return res.data.data
}

/** 通用 PATCH */
export async function patch<T = unknown>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.patch<ApiResponse<T>>(url, body, config)
  return res.data.data
}

/** 通用 DELETE */
export async function del<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.delete<ApiResponse<T>>(url, config)
  return res.data.data
}

export { broadcastLogout }
export default request
