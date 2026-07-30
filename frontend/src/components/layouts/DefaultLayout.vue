<script setup lang="ts">
/**
 * 默认布局：侧边栏 + 顶栏 + 内容区
 * 侧边栏菜单根据角色过滤；顶栏含用户信息、租户切换、退出登录、折叠/展开
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElContainer,
  ElAside,
  ElHeader,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElIcon,
  ElDropdown,
  ElDropdownMenu,
  ElDropdownItem,
  ElAvatar,
  ElTag,
  ElButton,
  ElTooltip,
  ElBadge
} from 'element-plus'
import {
  Fold,
  Expand,
  Setting,
  SwitchButton,
  Bell,
  Moon,
  Sunny
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useTenantStore } from '@/stores/tenant'
import { menuItems, type MenuItem } from '@/router/routes'
import { hasRole } from '@/utils/permission'
import { getRoleLabel } from '@/utils/permission'
import { TENANT_PLAN_LABELS } from '@/utils/format'
import type { UserRole } from '@/types/enum'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const tenantStore = useTenantStore()

// 按角色过滤菜单
const visibleMenus = computed<MenuItem[]>(() => {
  const roles = authStore.roles as UserRole[]
  return menuItems.filter((m) => !m.roles || hasRole(roles, m.roles))
})

const activeMenu = computed(() => `/${String(route.path.split('/')[1] || 'dashboard')}`)

const userName = computed(() => authStore.user?.display_name || authStore.user?.username || '用户')
const userInitial = computed(() => userName.value.charAt(0).toUpperCase())
const roleLabels = computed(() => (authStore.roles || []).map(getRoleLabel).join(' / '))

const tenantLabel = computed(() => {
  const t = tenantStore.currentTenant
  if (!t) return '当前租户'
  return `${t.name}（${TENANT_PLAN_LABELS[t.plan] || t.plan}）`
})

function handleSelect(index: string) {
  router.push(index)
}

async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

function handleCommand(command: string) {
  if (command === 'logout') handleLogout()
  else if (command === 'settings') router.push('/settings')
  else if (command.startsWith('tenant:')) {
    tenantStore.switchTenant(command.slice(7))
  }
}
</script>

<template>
  <ElContainer class="frd-layout">
    <ElAside :width="themeStore.sidebarCollapsed ? '64px' : '220px'" class="frd-aside">
      <div class="frd-logo">
        <span v-if="!themeStore.sidebarCollapsed" class="frd-logo-text">FRD 控制台</span>
        <span v-else class="frd-logo-mini">FRD</span>
      </div>
      <ElMenu
        :default-active="activeMenu"
        :collapse="themeStore.sidebarCollapsed"
        :collapse-transition="false"
        background-color="#001529"
        text-color="#cfd8e3"
        active-text-color="#ffffff"
        @select="handleSelect"
      >
        <ElMenuItem v-for="m in visibleMenus" :key="m.path" :index="m.path">
          <ElIcon v-if="m.icon"><component :is="m.icon" /></ElIcon>
          <template #title>{{ m.title }}</template>
        </ElMenuItem>
      </ElMenu>
    </ElAside>

    <ElContainer>
      <ElHeader class="frd-header">
        <div class="frd-header-left">
          <ElButton text @click="themeStore.toggleSidebar()">
            <ElIcon :size="20">
              <Expand v-if="themeStore.sidebarCollapsed" />
              <Fold v-else />
            </ElIcon>
          </ElButton>
        </div>

        <div class="frd-header-right">
          <ElTooltip :content="themeStore.isDark ? '切换亮色' : '切换暗色'">
            <ElButton text @click="themeStore.toggleDark()">
              <ElIcon :size="18">
                <Sunny v-if="themeStore.isDark" />
                <Moon v-else />
              </ElIcon>
            </ElButton>
          </ElTooltip>

          <ElBadge :value="3" :max="99">
            <ElButton text>
              <ElIcon :size="18"><Bell /></ElIcon>
            </ElButton>
          </ElBadge>

          <ElDropdown trigger="click" @command="handleCommand">
            <span class="frd-user">
              <ElAvatar :size="32">{{ userInitial }}</ElAvatar>
              <span class="frd-user-meta">
                <span class="frd-user-name">{{ userName }}</span>
                <ElTag size="small" type="info" effect="plain">{{ roleLabels }}</ElTag>
              </span>
            </span>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem disabled>{{ tenantLabel }}</ElDropdownItem>
                <ElDropdownItem
                  v-for="t in tenantStore.accessibleTenants"
                  :key="t.tenant_id"
                  :command="`tenant:${t.tenant_id}`"
                >
                  切换到 {{ t.name }}
                </ElDropdownItem>
                <ElDropdownItem divided :command="'settings'">
                  <ElIcon><Setting /></ElIcon> 个人设置
                </ElDropdownItem>
                <ElDropdownItem :command="'logout'">
                  <ElIcon><SwitchButton /></ElIcon> 退出登录
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </ElHeader>

      <ElMain class="frd-main">
        <RouterView v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </ElMain>
    </ElContainer>
  </ElContainer>
</template>

<style scoped>
.frd-layout {
  height: 100vh;
}
.frd-aside {
  background-color: #001529;
  transition: width 0.2s;
  overflow: hidden;
}
.frd-logo {
  height: var(--frd-header-height);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  border-bottom: 1px solid #1f2d3d;
}
.frd-logo-text {
  font-size: 16px;
}
.frd-logo-mini {
  font-size: 18px;
  font-weight: 700;
}
.frd-header {
  background: #fff;
  border-bottom: 1px solid #e6e8eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--frd-header-height);
  padding: 0 16px;
}
.frd-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.frd-user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.frd-user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.frd-user-name {
  font-size: 14px;
  color: #303133;
}
.frd-main {
  background: var(--frd-bg);
  padding: 16px;
  overflow: auto;
}
</style>
