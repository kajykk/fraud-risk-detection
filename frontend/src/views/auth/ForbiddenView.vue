<script setup lang="ts">
/**
 * 403 无权限页
 * - 当前账号无访问该页面/接口的权限
 * - 返回首页 / 重新登录
 */
import { useRouter } from 'vue-router'
import { ElButton, ElResult } from 'element-plus'

const router = useRouter()
</script>

<template>
  <div class="forbidden-page">
    <el-result icon="warning" title="403 无权限" sub-title="当前账号没有访问该页面的权限，请联系租户管理员。">
      <template #extra>
        <el-button type="primary" @click="router.push('/dashboard')">返回首页</el-button>
        <el-button @click="router.push('/login')">重新登录</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.forbidden-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #f5f7fa;
}
</style>
