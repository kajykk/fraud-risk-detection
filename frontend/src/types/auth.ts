/**
 * 认证 / 用户 / 角色 / 权限类型
 * 对齐 D05 §3（认证与授权）与 D06 §2.1（7 角色矩阵）
 */
import type { UserRole } from './enum'
import type { TenantType, TenantPlan } from './enum'

/** 用户基础信息 */
export interface UserInfo {
  user_id: string
  username: string
  email: string
  phone?: string
  display_name: string
  avatar_url?: string
  tenant_id: string
  roles: UserRole[]
  permissions: string[]
  merchant_id?: string
  business_unit?: string
  status: 'ACTIVE' | 'DISABLED' | 'LOCKED'
  last_login_at?: string
  created_at: string
}

/** 登录请求（用户名 + 密码 + MFA） */
export interface LoginRequest {
  username: string
  password: string
  mfa_code?: string
  trust_device?: boolean
}

/** Token 响应（D05 §3.1） */
export interface TokenResponse {
  access_token: string
  refresh_token?: string
  token_type: 'Bearer'
  expires_in: number
  scope?: string
}

/** JWT 载荷（D05 §3.2） */
export interface JwtPayload {
  sub: string
  tenant_id: string
  roles: UserRole[]
  scope?: string
  iat: number
  exp: number
  jti: string
}

/** 租户信息 */
export interface TenantInfo {
  tenant_id: string
  name: string
  type: TenantType
  plan: TenantPlan
  status: 'ACTIVE' | 'SUSPENDED' | 'TERMINATED'
  timezone: string
  language: 'zh-CN' | 'en-US'
  currency: string
  contact_email: string
  contact_phone?: string
  created_at: string
}

/** 个人设置 */
export interface UserProfile {
  notification_prefs: {
    email: boolean
    sms: boolean
    webhook: boolean
  }
  api_tokens: ApiToken[]
  active_sessions: ActiveSession[]
}

export interface ApiToken {
  token_id: string
  name: string
  scopes: string[]
  status: 'ACTIVE' | 'DISABLED' | 'EXPIRED'
  created_at: string
  last_used_at?: string
  expires_at?: string
}

export interface ActiveSession {
  session_id: string
  ip: string
  user_agent: string
  last_active_at: string
  current: boolean
}
