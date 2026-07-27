<script setup lang="ts">
/**
 * 登录页
 * - Element Plus Form：用户名 + 密码 + 可选 MFA
 * - 登录按钮调用 authStore.login
 * - 登录成功跳转 /dashboard（或 redirect 参数）
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElButton,
  ElCheckbox,
  ElMessage,
  type FormInstance,
  type FormRules
} from 'element-plus'
import { User, Lock, Key } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  mfa_code: '',
  trust_device: false
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 32, message: '密码长度 8-32 位', trigger: 'blur' }
  ]
}

async function handleLogin() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  try {
    await authStore.login({
      username: form.username,
      password: form.password,
      mfa_code: form.mfa_code || undefined,
      trust_device: form.trust_device
    })
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
  } catch {
    // 错误提示已在 axios 拦截器统一处理
  }
}
</script>

<template>
  <ElCard class="frd-login-card" shadow="always">
    <div class="frd-login-header">
      <h1 class="frd-login-title">FRD 金融反欺诈系统</h1>
      <p class="frd-login-subtitle">Fraud Risk Detection Console</p>
    </div>

    <ElForm ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="handleLogin">
      <ElFormItem label="用户名" prop="username">
        <ElInput v-model="form.username" :prefix-icon="User" placeholder="请输入用户名 / 邮箱" clearable />
      </ElFormItem>

      <ElFormItem label="密码" prop="password">
        <ElInput
          v-model="form.password"
          :prefix-icon="Lock"
          type="password"
          placeholder="请输入密码"
          show-password
          clearable
        />
      </ElFormItem>

      <ElFormItem label="MFA 动态码（可选）">
        <ElInput v-model="form.mfa_code" :prefix-icon="Key" placeholder="6 位动态码" maxlength="6" />
      </ElFormItem>

      <ElFormItem>
        <ElCheckbox v-model="form.trust_device">信任此设备 7 天</ElCheckbox>
      </ElFormItem>

      <ElButton
        type="primary"
        :loading="authStore.loading"
        class="frd-login-btn"
        @click="handleLogin"
      >
        登录
      </ElButton>
    </ElForm>

    <div class="frd-login-footer">
      <span>连续 5 次密码错误，账号锁定 15 分钟</span>
    </div>
  </ElCard>
</template>

<style scoped>
.frd-login-card {
  width: 420px;
  padding: 24px 32px;
  border-radius: 8px;
}
.frd-login-header {
  text-align: center;
  margin-bottom: 24px;
  color: #303133;
}
.frd-login-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
}
.frd-login-subtitle {
  margin: 0;
  font-size: 12px;
  color: #909399;
}
.frd-login-btn {
  width: 100%;
}
.frd-login-footer {
  margin-top: 16px;
  text-align: center;
  font-size: 12px;
  color: #909399;
}
</style>
