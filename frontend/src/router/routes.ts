/**
 * 路由表（含角色权限 meta）
 * 角色权限矩阵严格对齐 D06 V1.1 §2.1（7 角色 × 功能模块）
 *
 * 7 角色：TENANT_ADMIN / MERCHANT_ADMIN / RISK_ANALYST / RISK_MANAGER / AUDITOR / COMPLIANCE_OFFICER / DEVOPS_OPS
 *
 * meta.roles 含义：
 * - undefined / 空数组：所有已登录角色可访问
 * - 非空数组：仅数组内角色可访问
 * - meta.public = true：无需登录（登录页）
 * - meta.layout：'blank' | 'default'
 */
import type { RouteRecordRaw } from 'vue-router'
import { UserRole } from '@/types/enum'

/** 全部 7 角色（用于 /dashboard /settings 等所有角色可访问的页面） */
const ALL_ROLES: UserRole[] = [
  UserRole.TENANT_ADMIN,
  UserRole.MERCHANT_ADMIN,
  UserRole.RISK_ANALYST,
  UserRole.RISK_MANAGER,
  UserRole.AUDITOR,
  UserRole.COMPLIANCE_OFFICER,
  UserRole.DEVOPS_OPS
]

/** 除商户管理员外的角色（/transactions 评分查询） */
const ALL_EXCEPT_MERCHANT: UserRole[] = [
  UserRole.TENANT_ADMIN,
  UserRole.RISK_ANALYST,
  UserRole.RISK_MANAGER,
  UserRole.AUDITOR,
  UserRole.COMPLIANCE_OFFICER,
  UserRole.DEVOPS_OPS
]

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { public: true, layout: 'blank', title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/components/layouts/DefaultLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { roles: ALL_ROLES, title: '控制台概览', icon: 'Odometer' }
      },
      {
        path: 'transactions',
        name: 'transactions',
        component: () => import('@/views/transactions/TransactionListView.vue'),
        meta: { roles: ALL_EXCEPT_MERCHANT, title: '交易监控', icon: 'Money' }
      },
      {
        path: 'transactions/:externalTxId',
        name: 'transaction-detail',
        component: () => import('@/views/transactions/TransactionDetailView.vue'),
        meta: { roles: ALL_EXCEPT_MERCHANT, title: '交易详情', hidden: true }
      },
      {
        path: 'cases',
        name: 'cases',
        component: () => import('@/views/cases/CaseListView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.RISK_ANALYST, UserRole.RISK_MANAGER, UserRole.AUDITOR],
          title: '案件管理',
          icon: 'FolderOpened'
        }
      },
      {
        path: 'cases/:caseId',
        name: 'case-detail',
        component: () => import('@/views/cases/CaseDetailView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.RISK_ANALYST, UserRole.RISK_MANAGER, UserRole.AUDITOR],
          title: '案件详情',
          hidden: true
        }
      },
      {
        path: 'rules',
        name: 'rules',
        component: () => import('@/views/rules/RuleListView.vue'),
        meta: { roles: [UserRole.TENANT_ADMIN, UserRole.RISK_MANAGER], title: '规则引擎', icon: 'SetUp' }
      },
      {
        path: 'rules/:ruleId/edit',
        name: 'rule-edit',
        component: () => import('@/views/rules/RuleEditView.vue'),
        meta: { roles: [UserRole.TENANT_ADMIN, UserRole.RISK_MANAGER], title: '规则编辑', hidden: true }
      },
      {
        path: 'rules/create',
        name: 'rule-create',
        component: () => import('@/views/rules/RuleEditView.vue'),
        meta: { roles: [UserRole.TENANT_ADMIN, UserRole.RISK_MANAGER], title: '新建规则', hidden: true }
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('@/views/models/ModelListView.vue'),
        meta: { roles: [UserRole.TENANT_ADMIN, UserRole.RISK_MANAGER], title: '模型治理', icon: 'Cpu' }
      },
      {
        path: 'models/:modelId',
        name: 'model-detail',
        component: () => import('@/views/models/ModelDetailView.vue'),
        meta: { roles: [UserRole.TENANT_ADMIN, UserRole.RISK_MANAGER], title: '模型详情', hidden: true }
      },
      {
        path: 'gnn',
        name: 'gnn',
        component: () => import('@/views/gnn/CommunityView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.RISK_ANALYST, UserRole.RISK_MANAGER],
          title: 'GNN 团伙检测',
          icon: 'Share'
        }
      },
      {
        path: 'pipl',
        name: 'pipl',
        component: () => import('@/views/pipl/PiplDashboardView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.COMPLIANCE_OFFICER],
          title: 'PIPL 合规',
          icon: 'Lock'
        }
      },
      {
        path: 'webhooks',
        name: 'webhooks',
        component: () => import('@/views/webhooks/WebhookListView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.MERCHANT_ADMIN],
          title: 'Webhook',
          icon: 'Connection'
        }
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/audit/AuditLogView.vue'),
        meta: {
          roles: [UserRole.TENANT_ADMIN, UserRole.AUDITOR, UserRole.COMPLIANCE_OFFICER],
          title: '审计日志',
          icon: 'Document'
        }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: { roles: ALL_ROLES, title: '系统设置', icon: 'Setting' }
      }
    ]
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { public: true, layout: 'blank', title: '无权限' }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: '/dashboard'
  }
]

/** 侧边栏菜单项（仅展示非 hidden 路由） */
export interface MenuItem {
  path: string
  name: string
  title: string
  icon?: string
  roles?: UserRole[]
}

export const menuItems: MenuItem[] = routes
  .flatMap((r) => (r.children ? (r.children as RouteRecordRaw[]) : [r]))
  .filter((r) => !r.meta?.hidden)
  .map((r) => ({
    path: r.path === 'dashboard' ? '/dashboard' : `/${r.path}`,
    name: String(r.name),
    title: String(r.meta?.title ?? r.name),
    icon: r.meta?.icon as string | undefined,
    roles: r.meta?.roles as UserRole[] | undefined
  }))
