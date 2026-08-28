/**
 * 认证状态（token / user / roles / permissions）
 * 对齐 D05 §3 与 D06 §2.1（7 角色）
 *
 * Token 生命周期（XSS 加固）：
 * - access token 仅存内存（request.ts 模块级 holder），刷新后经
 *   BroadcastChannel 同步到其他标签页；
 * - refresh token 为 HttpOnly Cookie，本 store 不接触其值；
 * - 页面刷新后由路由守卫触发 initSession() 静默恢复会话。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '@/api/auth'
import {
  broadcastLogout,
  getAccessToken,
  purgeLegacyTokenStorage,
  setAccessToken
} from '@/api/request'
import type { LoginRequest, UserInfo } from '@/types/auth'
import type { UserRole } from '@/types/enum'

/** 解析 JWT exp（仅读取声明用于续期调度，不做签名校验） */
function jwtExp(token: string): number | null {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const json = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))) as { exp?: number }
    return typeof json.exp === 'number' ? json.exp : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  // state：access token 仅内存持有（holder 为单一事实源，ref 用于响应式）
  const token = ref<string | null>(getAccessToken())
  const user = ref<UserInfo | null>(null)
  const roles = ref<UserRole[]>([])
  const permissions = ref<string[]>([])
  const loading = ref(false)

  // 会话引导去重 + 主动续期定时器
  let initPromise: Promise<boolean> | null = null
  let renewTimer: ReturnType<typeof setTimeout> | null = null

  // getters
  const isAuthenticated = computed(() => !!token.value)
  const currentUser = computed(() => user.value)

  function hasRole(role: UserRole | UserRole[]): boolean {
    if (!roles.value.length) return false
    const targets = Array.isArray(role) ? role : [role]
    return targets.some((r) => roles.value.includes(r))
  }

  function hasPermission(perm: string | string[]): boolean {
    if (!permissions.value.length) return false
    const targets = Array.isArray(perm) ? perm : [perm]
    return targets.some((p) => permissions.value.includes(p))
  }

  function scheduleProactiveRenewal(): void {
    if (renewTimer) {
      clearTimeout(renewTimer)
      renewTimer = null
    }
    const current = token.value
    if (!current) return
    const exp = jwtExp(current)
    if (!exp) return
    // 过期前 60s 续期；下限 30s 防止时钟漂移导致风暴
    const delay = Math.max(30_000, exp * 1000 - Date.now() - 60_000)
    renewTimer = setTimeout(() => {
      void refresh().catch(() => {
        /* 失败留给 401 拦截路径处理 */
      })
    }, delay)
  }

  function applyToken(accessToken: string): void {
    setAccessToken(accessToken)
    token.value = accessToken
    scheduleProactiveRenewal()
  }

  function clearToken() {
    setAccessToken(null, false)
    broadcastLogout()
    purgeLegacyTokenStorage()
    if (renewTimer) {
      clearTimeout(renewTimer)
      renewTimer = null
    }
    token.value = null
    user.value = null
    roles.value = []
    permissions.value = []
  }

  function setUser(userInfo: UserInfo) {
    user.value = userInfo
    roles.value = userInfo.roles || []
    permissions.value = userInfo.permissions || []
  }

  // actions
  async function login(payload: LoginRequest) {
    loading.value = true
    try {
      const res = await authApi.login(payload)
      applyToken(res.access_token)
      await fetchProfile()
      return res
    } finally {
      loading.value = false
    }
  }

  async function fetchProfile() {
    const profile = await authApi.fetchProfile()
    setUser(profile)
    return profile
  }

  async function refresh() {
    // RT 位于 HttpOnly Cookie：同源请求自动携带，无需传 body；
    // 旋转后的新 AT 经 request.ts 广播同步其他标签页
    const res = await authApi.refreshToken('')
    applyToken(res.access_token)
    return res
  }

  /**
   * 会话静默引导（页面刷新/首次进入受保护路由时调用）：
   * 内存无 AT → 用 Cookie 中的 RT 换取新 AT 并拉取 profile。
   * 返回 true 表示会话已恢复。并发调用共享同一 Promise。
   */
  function initSession(): Promise<boolean> {
    if (token.value) return Promise.resolve(true)
    if (initPromise) return initPromise
    initPromise = (async () => {
      try {
        await refresh()
        await fetchProfile()
        return true
      } catch {
        clearToken()
        return false
      } finally {
        initPromise = null
      }
    })()
    return initPromise
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // 即使后端调用失败也清除本地状态
    } finally {
      clearToken()
    }
  }

  return {
    // state
    token,
    user,
    roles,
    permissions,
    loading,
    // getters
    isAuthenticated,
    currentUser,
    hasRole,
    hasPermission,
    // actions
    setToken: applyToken,
    clearToken,
    setUser,
    login,
    fetchProfile,
    refresh,
    initSession,
    logout
  }
})
