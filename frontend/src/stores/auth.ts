/**
 * 认证状态（token / user / roles / permissions）
 * 对齐 D05 §3 与 D06 §2.1（7 角色）
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as authApi from '@/api/auth'
import { STORAGE_KEY_TOKEN, STORAGE_KEY_REFRESH_TOKEN } from '@/api/request'
import type { LoginRequest, UserInfo } from '@/types/auth'
import type { UserRole } from '@/types/enum'

export const useAuthStore = defineStore('auth', () => {
  // state
  const token = ref<string | null>(localStorage.getItem(STORAGE_KEY_TOKEN))
  const refreshToken = ref<string | null>(localStorage.getItem(STORAGE_KEY_REFRESH_TOKEN))
  const user = ref<UserInfo | null>(null)
  const roles = ref<UserRole[]>([])
  const permissions = ref<string[]>([])
  const loading = ref(false)

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

  function setToken(accessToken: string, refreshTokenValue?: string) {
    token.value = accessToken
    localStorage.setItem(STORAGE_KEY_TOKEN, accessToken)
    if (refreshTokenValue) {
      refreshToken.value = refreshTokenValue
      localStorage.setItem(STORAGE_KEY_REFRESH_TOKEN, refreshTokenValue)
    }
  }

  function clearToken() {
    token.value = null
    refreshToken.value = null
    localStorage.removeItem(STORAGE_KEY_TOKEN)
    localStorage.removeItem(STORAGE_KEY_REFRESH_TOKEN)
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
      setToken(res.access_token, res.refresh_token)
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
    if (!refreshToken.value) throw new Error('无 refresh token')
    const res = await authApi.refreshToken(refreshToken.value)
    setToken(res.access_token, res.refresh_token)
    return res
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // 即使后端调用失败也清除本地状态
    } finally {
      clearToken()
      user.value = null
      roles.value = []
      permissions.value = []
    }
  }

  return {
    // state
    token,
    refreshToken,
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
    setToken,
    clearToken,
    setUser,
    login,
    fetchProfile,
    refresh,
    logout
  }
})
