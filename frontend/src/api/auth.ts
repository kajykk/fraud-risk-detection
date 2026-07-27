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

/** 刷新 token */
export function refreshToken(refreshToken: string) {
  return post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken })
}

/** 退出登录 */
export function logout() {
  return post<void>('/auth/logout')
}

/** 获取当前用户 profile */
export function fetchProfile() {
  return get<UserInfo>('/auth/profile')
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
