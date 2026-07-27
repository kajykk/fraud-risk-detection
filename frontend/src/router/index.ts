/**
 * 路由配置 + 导航守卫
 * 对齐 D06 §2.1 角色权限矩阵
 *
 * 全局前置守卫：
 * 1. 检查 token（未登录跳转 /login）
 * 2. 检查角色权限（无权限跳转 /403）
 */
import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import { routes } from './routes'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/types/enum'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

// 免登录白名单
const WHITELIST = ['/login', '/403']

function isPublic(to: RouteLocationNormalized): boolean {
  return to.meta?.public === true || WHITELIST.includes(to.path)
}

function checkRole(userRoles: UserRole[], required?: UserRole[]): boolean {
  if (!required || required.length === 0) return true
  return required.some((r) => userRoles.includes(r))
}

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  // 设置页面标题
  const title = to.meta?.title as string | undefined
  document.title = title ? `${title} - FRD 金融反欺诈系统` : 'FRD 金融反欺诈系统'

  // 公共页面直接放行
  if (isPublic(to)) {
    // 已登录用户访问登录页 → 跳转首页
    if (to.path === '/login' && authStore.isAuthenticated) {
      next({ path: '/dashboard' })
      return
    }
    next()
    return
  }

  // 未登录 → 跳转登录页（带 redirect）
  if (!authStore.isAuthenticated) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 已登录但 user 信息缺失 → 拉取 profile
  if (!authStore.user) {
    try {
      await authStore.fetchProfile()
    } catch {
      await authStore.logout()
      next({ path: '/login', query: { redirect: to.fullPath } })
      return
    }
  }

  // 角色权限校验
  const requiredRoles = to.meta?.roles as UserRole[] | undefined
  if (!checkRole(authStore.roles, requiredRoles)) {
    next({ path: '/403' })
    return
  }

  next()
})

export default router
