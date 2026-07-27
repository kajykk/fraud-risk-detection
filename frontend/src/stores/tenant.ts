/**
 * 租户状态
 * 对齐 D05 §2.2（tenant_id 来源优先级）与 D06 §12.2（租户配置）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TenantInfo } from '@/types/auth'

export const useTenantStore = defineStore('tenant', () => {
  const currentTenant = ref<TenantInfo | null>(null)
  const accessibleTenants = ref<TenantInfo[]>([])
  const loading = ref(false)

  function setCurrentTenant(tenant: TenantInfo) {
    currentTenant.value = tenant
  }

  function setAccessibleTenants(list: TenantInfo[]) {
    accessibleTenants.value = list
  }

  async function switchTenant(tenantId: string) {
    // TENANT_ADMIN 跨租户切换（admin:* scope，需后端校验）
    const target = accessibleTenants.value.find((t) => t.tenant_id === tenantId)
    if (target) {
      setCurrentTenant(target)
    }
  }

  return {
    currentTenant,
    accessibleTenants,
    loading,
    setCurrentTenant,
    setAccessibleTenants,
    switchTenant
  }
})
