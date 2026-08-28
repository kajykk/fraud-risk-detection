/**
 * 认证 API（对齐 D05 §3）
 */
import { post, get } from './request'
import type { LoginRequest, TokenResponse, UserInfo } from '@/types/auth'
import type { PageQuery, PageResult } from '@/types/api'

/** 用户名密码登录 */
export function login(payload: LoginRequest) {
  return post<TokenResponse>('/auth/login', payload)
}

/** 刷新 token（标准路径依赖 HttpOnly Cookie，body 参数仅为 API 直连兼容） */
export function refreshToken(refreshToken?: string) {
  return post<TokenResponse>('/auth/refresh', refreshToken ? { refresh_token: refreshToken } : {})
}

/** 退出登录 */
export function logout() {
  return post<void>('/auth/logout')
}

/** 获取当前用户 profile */
export function fetchProfile() {
  return get<UserInfo>('/auth/profile')
}

/** 签发一次性 WebSocket 连接票据（30s 有效，单次消费） */
export function createWsTicket() {
  return post<{ ticket: string; expires_in: number }>('/auth/ws-ticket')
}

/** OAuth2 客户端凭证模式获取 token（D05 §3.1） */
export function fetchToken(payload: {
  grant_type: 'client_credentials' | 'password' | 'refresh_token'
  client_id?: string
  client_secret?: string
  scope?: string
}) {
  return post<TokenResponse>('/auth/token', payload)
}

/** 用户列表（仅 TENANT_ADMIN） */
export function listUsers(query: PageQuery) {
  return get<PageResult<UserInfo>>('/auth/users', query as Record<string, unknown>)
}
