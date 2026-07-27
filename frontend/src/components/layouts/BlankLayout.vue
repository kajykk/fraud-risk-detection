<script setup lang="ts">
/**
 * 空白布局：用于登录页 / 无权限页
 */
</script>

<template>
  <div class="frd-blank-layout">
    <RouterView />
  </div>
</template>

<style scoped>
.frd-blank-layout {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0b5fff 0%, #1e88e5 100%);
}
</style>
