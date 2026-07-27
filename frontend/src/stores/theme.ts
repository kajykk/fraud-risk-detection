/**
 * 主题状态（亮/暗 + Element Plus 尺寸）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useDark, useToggle } from '@vueuse/core'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(useDark())
  const toggleDark = useToggle(isDark)
  const size = ref<'large' | 'default' | 'small'>('default')
  const sidebarCollapsed = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setSize(s: 'large' | 'default' | 'small') {
    size.value = s
  }

  return {
    isDark,
    size,
    sidebarCollapsed,
    toggleDark,
    toggleSidebar,
    setSize
  }
})
