<script setup lang="ts">
import { ElConfigProvider, ElLoading } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

// 全局 loading 指令（路由切换/请求时可调用）
ElLoading.service({ lock: true, text: '加载中...', background: 'rgba(0,0,0,0.4)' })
</script>

<template>
  <ElConfigProvider :locale="zhCn" :size="themeStore.size">
    <RouterView v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </RouterView>
  </ElConfigProvider>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
