/**
 * Axios 实例 + 拦截器
 * 对齐 D05 §2.2（请求头）/ §2.6（HTTP 状态码）/ §12（错误码）
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

const STORAGE_KEY_TOKEN = 'frd_access_token'
const STORAGE_KEY_REFRESH_TOKEN = 'frd_refresh_token'

/** 读取本地 token（避免与 store 循环依赖） */
function getStoredToken(): string | null {
  return localStorage.getItem(STORAGE_KEY_TOKEN)
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

// 401 自动刷新：并发 401 共享同一个刷新请求；避免与 auth API 循环依赖
let refreshPromise: Promise<string | null> | null = null

function isAuthPath(url?: string): boolean {
  return !!url && /\/auth\/(login|refresh|token)/.test(url)
}

async function tryRefreshToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem(STORAGE_KEY_REFRESH_TOKEN)
  if (!refreshToken) return null
  try {
    // 用裸 axios 发送，避免经过本拦截器（防递归）；仍带 X-Request-Id 供后端链路追踪
    const res = await axios.post<ApiResponse<{ access_token: string; refresh_token?: string }>>(
      `${request.defaults.baseURL}/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { 'X-Request-Id': genRequestId() } }
    )
    const data = res.data?.data
    if (!data?.access_token) return null
    localStorage.setItem(STORAGE_KEY_TOKEN, data.access_token)
    if (data.refresh_token) {
      localStorage.setItem(STORAGE_KEY_REFRESH_TOKEN, data.refresh_token)
    }
    return data.access_token
  } catch {
    return null
  }
}

/** 清除 token 并跳转登录（避免在拦截器内 import store 造成循环依赖） */
function redirectToLogin() {
  localStorage.removeItem(STORAGE_KEY_TOKEN)
  localStorage.removeItem(STORAGE_KEY_REFRESH_TOKEN)
  const current = window.location.pathname + window.location.search
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = `/login?redirect=${encodeURIComponent(current)}`
  }
}

// 请求拦截器：注入 Authorization Bearer token + X-Request-ID
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getStoredToken()
    if (token && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`
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
      // 尝试自动刷新 token 并重放请求一次
      refreshPromise = refreshPromise ?? tryRefreshToken()
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

export { STORAGE_KEY_TOKEN, STORAGE_KEY_REFRESH_TOKEN }
export default request
