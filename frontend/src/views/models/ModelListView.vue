<script setup lang="ts">
/**
 * 模型治理列表（D06 §8）
 * 模型状态：REGISTERED → CANARY → ACTIVE → RETIRED
 * 含漂移指标展示
 */
import { onMounted, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElCard,
  ElButton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElPagination,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElLoading
} from 'element-plus'
import { listModels, triggerKillSwitch } from '@/api/model'
import type { ModelListItem } from '@/types/model'
import { ModelStatus } from '@/types/enum'
import { MODEL_STATUS_LABELS, formatDate, formatPercent } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const list = ref<ModelListItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 20
})

async function fetchData() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const res = await listModels(query)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
    svc.close()
  }
}

function goDetail(row: ModelListItem) {
  router.push(`/models/${row.model_id}`)
}

function statusTagType(s: ModelStatus): 'info' | 'warning' | 'success' | 'danger' {
  if (s === ModelStatus.ACTIVE) return 'success'
  if (s === ModelStatus.CANARY) return 'warning'
  if (s === ModelStatus.RETIRED) return 'info'
  return 'info'
}

async function onGlobalKillSwitch() {
  try {
    const { value } = await ElMessageBox.prompt('输入 L1 全局熔断原因', '紧急熔断确认', {
      inputType: 'textarea',
      confirmButtonText: '熔断',
      cancelButtonText: '取消',
      inputPlaceholder: '说明熔断原因（将记录到审计日志）'
    })
    if (!value?.trim()) {
      return
    }
    const durationRes = await ElMessageBox.prompt('熔断时长（分钟）', '熔断时长', {
      inputType: 'number',
      inputValue: '30'
    })
    const duration = Number(durationRes.value) || 30
    const svc = ElLoading.service({ lock: true, text: '触发熔断...' })
    try {
      await triggerKillSwitch({
        level: 'L1_GLOBAL',
        scope: '*',
        reason: value,
        duration_minutes: duration,
        approver_id: auth.user?.user_id || ''
      })
      ElMessage.success('已触发全局熔断')
    } finally {
      svc.close()
    }
  } catch {
    /* 用户取消 */
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <div class="frd-flex-between">
        <div>
          <ElInput
            v-model="query.page_size"
            placeholder="页大小"
            style="width: 100px; margin-right: 12px"
          />
          <ElButton type="primary" @click="fetchData">刷新</ElButton>
        </div>
        <ElButton type="danger" @click="onGlobalKillSwitch">L1 全局熔断</ElButton>
      </div>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe @row-dblclick="goDetail">
        <ElTableColumn prop="name" label="模型名称" min-width="180" />
        <ElTableColumn prop="model_id" label="模型 ID" width="220" />
        <ElTableColumn prop="version" label="版本" width="120" />
        <ElTableColumn label="类型" width="120">
          <template #default="{ row }">
            <ElTag>{{ row.type }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="110">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.status as ModelStatus)">
              {{ MODEL_STATUS_LABELS[row.status as ModelStatus] }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="AUC" width="100" align="right">
          <template #default="{ row }">{{ row.auc?.toFixed(4) ?? '-' }}</template>
        </ElTableColumn>
        <ElTableColumn label="Recall@1%" width="120" align="right">
          <template #default="{ row }">{{ formatPercent(row.recall_at_1pct) }}</template>
        </ElTableColumn>
        <ElTableColumn label="流量占比" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.traffic_share) }}</template>
        </ElTableColumn>
        <ElTableColumn label="晋升时间" width="170">
          <template #default="{ row }">{{ formatDate(row.promoted_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <ElButton text type="primary" @click="goDetail(row)">详情</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="fetchData"
        @size-change="fetchData"
        style="margin-top: 16px; justify-content: flex-end"
      />
    </ElCard>
  </div>
</template>
