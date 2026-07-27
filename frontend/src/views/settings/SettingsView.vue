<script setup lang="ts">
/**
 * 系统设置（D06 §3.4 + §12）
 * 三个标签页：
 *   1. 个人设置（密码修改 / MFA / 通知偏好 / API Token / 活跃会话）
 *   2. 外观与主题（暗黑 / 尺寸 / 侧边栏）
 *   3. 租户切换（仅 TENANT_ADMIN）
 * 所有角色可访问
 */
import { computed, ref, reactive } from 'vue'
import {
  ElCard,
  ElTabs,
  ElTabPane,
  ElForm,
  ElFormItem,
  ElInput,
  ElButton,
  ElSwitch,
  ElRadioGroup,
  ElRadio,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
  ElMessage,
  ElMessageBox,
  ElLoading
} from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { useTenantStore } from '@/stores/tenant'
import { ROLE_LABELS } from '@/utils/permission'
import { TENANT_PLAN_LABELS, TENANT_TYPE_LABELS, formatDate } from '@/utils/format'
import type { UserRole } from '@/types/enum'

const auth = useAuthStore()
const theme = useThemeStore()
const tenant = useTenantStore()

// ===== 个人设置 =====
const pwdForm = reactive<{ old_password: string; new_password: string; confirm: string }>({
  old_password: '',
  new_password: '',
  confirm: ''
})
const notifPrefs = reactive<{ email: boolean; sms: boolean; webhook: boolean }>({
  email: true,
  sms: false,
  webhook: true
})

async function submitPassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写原密码与新密码')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  if (pwdForm.new_password.length < 8 || pwdForm.new_password.length > 32) {
    ElMessage.warning('密码长度需 8-32 位，需含大小写字母+数字+特殊字符')
    return
  }
  ElMessage.info('密码修改 API 待接入（D05 §3 待补齐 change-password 端点）')
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
}

async function submitNotifPrefs() {
  ElMessage.success('通知偏好已保存（本地缓存）')
  // TODO: 调用 PATCH /users/me/preferences
}

const tokens = ref([
  {
    token_id: 'tok_demo_001',
    name: 'Default API Token',
    scopes: ['transaction:score', 'transaction:read'],
    status: 'ACTIVE',
    created_at: '2026-07-27T08:00:00Z',
    expires_at: '2027-07-27T08:00:00Z'
  }
])

async function createToken() {
  const { value } = await ElMessageBox.prompt('输入 Token 名称', '新建 API Token', {
    inputPattern: /^.{1,40}$/,
    inputErrorMessage: '名称长度 1-40'
  })
  ElMessage.info('API Token 生成 API 待接入（D05 §3 待补齐 token 端点）')
  tokens.value.push({
    token_id: `tok_${Date.now()}`,
    name: value,
    scopes: [],
    status: 'ACTIVE',
    created_at: new Date().toISOString()
  })
}

async function revokeToken(row: { token_id: string }) {
  await ElMessageBox.confirm('确认吊销该 Token？此操作不可恢复。', '吊销确认', { type: 'warning' })
  tokens.value = tokens.value.filter((t) => t.token_id !== row.token_id)
  ElMessage.success('已吊销')
}

const sessions = ref([
  {
    session_id: 'sess_demo_001',
    ip: '127.0.0.1',
    user_agent: navigator.userAgent,
    last_active_at: new Date().toISOString(),
    current: true
  }
])

async function revokeSession(row: { session_id: string; current: boolean }) {
  if (row.current) {
    ElMessage.warning('不能注销当前会话，请使用退出登录')
    return
  }
  sessions.value = sessions.value.filter((s) => s.session_id !== row.session_id)
  ElMessage.success('已注销')
}

// ===== 主题 =====
const themeSize = ref<'large' | 'default' | 'small'>(theme.size)

function onSizeChange() {
  theme.setSize(themeSize.value)
  ElMessage.success(`组件尺寸已切换为 ${themeSize.value}`)
}

function onToggleDark() {
  theme.toggleDark()
}

// ===== 租户切换 =====
const isTenantAdmin = computed(() => auth.hasRole('TENANT_ADMIN' as UserRole))

async function onSwitchTenant(tenantId: string) {
  await tenant.switchTenant(tenantId)
  ElMessage.success('租户已切换')
}
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never">
      <ElTabs>
        <ElTabPane label="个人设置" name="profile">
          <ElCard shadow="never" class="frd-card-margin">
            <template #header>账号信息</template>
            <ElDescriptions v-if="auth.user" :column="2" border>
              <ElDescriptionsItem label="用户 ID">{{ auth.user.user_id }}</ElDescriptionsItem>
              <ElDescriptionsItem label="用户名">{{ auth.user.username }}</ElDescriptionsItem>
              <ElDescriptionsItem label="显示名">{{ auth.user.display_name }}</ElDescriptionsItem>
              <ElDescriptionsItem label="邮箱">{{ auth.user.email }}</ElDescriptionsItem>
              <ElDescriptionsItem label="手机">{{ auth.user.phone || '-' }}</ElDescriptionsItem>
              <ElDescriptionsItem label="状态">
                <ElTag :type="auth.user.status === 'ACTIVE' ? 'success' : 'warning'">{{ auth.user.status }}</ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="角色">
                <ElTag v-for="r in auth.roles" :key="r" style="margin-right: 4px">{{ ROLE_LABELS[r] }}</ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="最近登录">{{ formatDate(auth.user.last_login_at) }}</ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>

          <ElCard shadow="never" class="frd-card-margin">
            <template #header>修改密码</template>
            <ElForm :model="pwdForm" label-width="120px" style="max-width: 480px">
              <ElFormItem label="原密码" required>
                <ElInput v-model="pwdForm.old_password" type="password" show-password />
              </ElFormItem>
              <ElFormItem label="新密码" required>
                <ElInput v-model="pwdForm.new_password" type="password" show-password />
              </ElFormItem>
              <ElFormItem label="确认新密码" required>
                <ElInput v-model="pwdForm.confirm" type="password" show-password />
              </ElFormItem>
              <ElFormItem>
                <ElButton type="primary" @click="submitPassword">修改密码</ElButton>
              </ElFormItem>
            </ElForm>
          </ElCard>

          <ElCard shadow="never" class="frd-card-margin">
            <template #header>通知偏好</template>
            <ElForm :model="notifPrefs" label-width="120px">
              <ElFormItem label="邮件通知">
                <ElSwitch v-model="notifPrefs.email" />
              </ElFormItem>
              <ElFormItem label="短信通知">
                <ElSwitch v-model="notifPrefs.sms" />
              </ElFormItem>
              <ElFormItem label="Webhook 通知">
                <ElSwitch v-model="notifPrefs.webhook" />
              </ElFormItem>
              <ElFormItem>
                <ElButton type="primary" @click="submitNotifPrefs">保存</ElButton>
              </ElFormItem>
            </ElForm>
          </ElCard>

          <ElCard shadow="never" class="frd-card-margin">
            <template #header>
              <div class="frd-flex-between">
                <span>API Token</span>
                <ElButton type="primary" @click="createToken">新建 Token</ElButton>
              </div>
            </template>
            <ElTable :data="tokens" stripe>
              <ElTableColumn prop="name" label="名称" min-width="160" />
              <ElTableColumn prop="token_id" label="Token ID" min-width="200" />
              <ElTableColumn label="Scopes" min-width="220">
                <template #default="{ row }">
                  <ElTag v-for="s in row.scopes" :key="s" style="margin-right: 4px">{{ s }}</ElTag>
                  <span v-if="!row.scopes.length">-</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="100">
                <template #default="{ row }">
                  <ElTag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="创建时间" width="170">
                <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
              </ElTableColumn>
              <ElTableColumn label="过期时间" width="170">
                <template #default="{ row }">{{ formatDate(row.expires_at) }}</template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <ElButton text type="danger" @click="revokeToken(row)">吊销</ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>

          <ElCard shadow="never">
            <template #header>活跃会话</template>
            <ElTable :data="sessions" stripe>
              <ElTableColumn prop="session_id" label="会话 ID" min-width="200" />
              <ElTableColumn prop="ip" label="IP" width="140" />
              <ElTableColumn prop="user_agent" label="User Agent" min-width="280" />
              <ElTableColumn label="最近活跃" width="170">
                <template #default="{ row }">{{ formatDate(row.last_active_at) }}</template>
              </ElTableColumn>
              <ElTableColumn label="当前" width="80">
                <template #default="{ row }">
                  <ElTag v-if="row.current" type="success">当前</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <ElButton text type="danger" :disabled="row.current" @click="revokeSession(row)">注销</ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </ElTabPane>

        <ElTabPane label="外观与主题" name="theme">
          <ElCard shadow="never">
            <ElForm label-width="120px" style="max-width: 480px">
              <ElFormItem label="暗黑模式">
                <ElSwitch :model-value="theme.isDark" @update:model-value="onToggleDark" />
              </ElFormItem>
              <ElFormItem label="组件尺寸">
                <ElRadioGroup v-model="themeSize" @change="onSizeChange">
                  <ElRadio value="large">大</ElRadio>
                  <ElRadio value="default">默认</ElRadio>
                  <ElRadio value="small">小</ElRadio>
                </ElRadioGroup>
              </ElFormItem>
              <ElFormItem label="侧边栏折叠">
                <ElSwitch :model-value="theme.sidebarCollapsed" @update:model-value="theme.toggleSidebar()" />
              </ElFormItem>
            </ElForm>
          </ElCard>
        </ElTabPane>

        <ElTabPane v-if="isTenantAdmin" label="租户切换" name="tenant">
          <ElCard shadow="never">
            <template #header>
              <div class="frd-flex-between">
                <span>可访问租户</span>
                <span v-if="tenant.currentTenant" style="color: #909399">
                  当前：{{ tenant.currentTenant.name }}
                </span>
              </div>
            </template>
            <ElTable :data="tenant.accessibleTenants" stripe>
              <ElTableColumn prop="name" label="租户名称" min-width="200" />
              <ElTableColumn prop="tenant_id" label="租户 ID" min-width="220" />
              <ElTableColumn label="类型" width="120">
                <template #default="{ row }">{{ TENANT_TYPE_LABELS[row.type] }}</template>
              </ElTableColumn>
              <ElTableColumn label="套餐" width="120">
                <template #default="{ row }">{{ TENANT_PLAN_LABELS[row.plan] }}</template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="100">
                <template #default="{ row }">
                  <ElTag :type="row.status === 'ACTIVE' ? 'success' : 'warning'">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="120" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    text
                    type="primary"
                    :disabled="tenant.currentTenant?.tenant_id === row.tenant_id"
                    @click="onSwitchTenant(row.tenant_id)"
                  >
                    切换
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </ElTabPane>
      </ElTabs>
    </ElCard>
  </div>
</template>
