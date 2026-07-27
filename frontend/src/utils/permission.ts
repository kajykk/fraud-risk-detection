/**
 * 权限校验工具（hasRole / hasPermission）
 * 对齐 D06 §2.1 角色矩阵
 */
import type { UserRole } from '@/types/enum'

/**
 * 判断当前用户是否拥有指定角色之一
 * @param userRoles 当前用户的角色列表
 * @param required 允许的角色（数组=任一满足；空数组/不传=允许所有）
 */
export function hasRole(userRoles: UserRole[], required?: UserRole[]): boolean {
  if (!required || required.length === 0) return true
  if (!userRoles || userRoles.length === 0) return false
  return required.some((r) => userRoles.includes(r))
}

/**
 * 判断当前用户是否拥有指定权限之一
 */
export function hasPermission(userPerms: string[], required?: string[]): boolean {
  if (!required || required.length === 0) return true
  if (!userPerms || userPerms.length === 0) return false
  return required.some((p) => userPerms.includes(p))
}

/**
 * 角色中文标签（对齐 D06 §1.1）
 */
export const ROLE_LABELS: Record<UserRole, string> = {
  TENANT_ADMIN: '租户管理员',
  MERCHANT_ADMIN: '商户管理员',
  RISK_ANALYST: '风控分析师',
  RISK_MANAGER: '风控经理',
  AUDITOR: '审计员',
  COMPLIANCE_OFFICER: '合规官',
  DEVOPS_OPS: '运维工程师'
}

export function getRoleLabel(role: UserRole): string {
  return ROLE_LABELS[role] || role
}
