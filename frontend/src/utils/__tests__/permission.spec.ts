// 权限校验工具单元测试（对齐 D06 §2.1 角色矩阵）
import { describe, expect, it } from 'vitest'
import { hasRole, hasPermission, getRoleLabel, requireApproverId } from '@/utils/permission'
import { UserRole } from '@/types/enum'

const {
  TENANT_ADMIN,
  MERCHANT_ADMIN,
  RISK_ANALYST,
  RISK_MANAGER,
  AUDITOR,
  COMPLIANCE_OFFICER,
  DEVOPS_OPS
} = UserRole

describe('hasRole', () => {
  it('未指定 required（空数组/不传）时允许所有角色', () => {
    expect(hasRole([RISK_ANALYST], undefined)).toBe(true)
    expect(hasRole([RISK_ANALYST], [])).toBe(true)
    expect(hasRole([], [])).toBe(true)
  })

  it('用户无角色时一律拒绝', () => {
    expect(hasRole([], [RISK_ANALYST])).toBe(false)
    expect(hasRole(undefined as unknown as UserRole[], [RISK_ANALYST])).toBe(false)
  })

  it('命中任一 required 角色即通过', () => {
    expect(hasRole([RISK_ANALYST], [RISK_MANAGER, RISK_ANALYST])).toBe(true)
    expect(hasRole([AUDITOR], [RISK_MANAGER, RISK_ANALYST])).toBe(false)
  })

  it('多角色用户任一满足即通过', () => {
    expect(hasRole([RISK_ANALYST, AUDITOR], [AUDITOR])).toBe(true)
  })
})

describe('hasPermission', () => {
  it('未指定 required 时允许所有权限', () => {
    expect(hasPermission([], undefined)).toBe(true)
    expect(hasPermission([], [])).toBe(true)
  })

  it('用户无权限时一律拒绝', () => {
    expect(hasPermission([], ['score:write'])).toBe(false)
    expect(hasPermission(undefined as unknown as string[], ['score:write'])).toBe(false)
  })

  it('命中任一 required 权限即通过', () => {
    expect(hasPermission(['score:read', 'rule:write'], ['rule:write', 'case:delete'])).toBe(true)
    expect(hasPermission(['score:read'], ['rule:write'])).toBe(false)
  })
})

describe('getRoleLabel', () => {
  it('已知角色返回中文标签', () => {
    expect(getRoleLabel(TENANT_ADMIN)).toBe('租户管理员')
    expect(getRoleLabel(COMPLIANCE_OFFICER)).toBe('合规官')
    expect(getRoleLabel(DEVOPS_OPS)).toBe('运维工程师')
    expect(getRoleLabel(MERCHANT_ADMIN)).toBe('商户管理员')
    expect(getRoleLabel(RISK_MANAGER)).toBe('风控经理')
  })

  it('未知角色回退原值', () => {
    expect(getRoleLabel('NON_EXISTENT_ROLE' as UserRole)).toBe('NON_EXISTENT_ROLE')
  })
})

describe('requireApproverId（四眼审计必填）', () => {
  it('有效 userId 直接返回', () => {
    expect(requireApproverId('user-123')).toBe('user-123')
  })

  it('空/空白/缺失时返回 null（应终止操作，不静默上送）', () => {
    expect(requireApproverId(null)).toBeNull()
    expect(requireApproverId(undefined)).toBeNull()
    expect(requireApproverId('')).toBeNull()
    expect(requireApproverId('   ')).toBeNull()
  })
})