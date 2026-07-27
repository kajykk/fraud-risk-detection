<script setup lang="ts">
/**
 * 模型详情（D06 §8.4-8.5）
 * 含：基本信息、性能指标、漂移指标、金丝雀推进/回滚、紧急熔断、退役
 */
import { computed, onMounted, ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElTag,
  ElButton,
  ElTable,
  ElTableColumn,
  ElProgress,
  ElInput,
  ElInputNumber,
  ElDialog,
  ElForm,
  ElFormItem,
  ElMessage,
  ElMessageBox,
  ElEmpty,
  ElLoading
} from 'element-plus'
import {
  getModel,
  getModelDrift,
  startCanary,
  promoteModel,
  rollbackModel,
  retireModel,
  getKillSwitchState
} from '@/api/model'
import type { ModelDetail, ModelDrift, KillSwitchState } from '@/types/model'
import { ModelStatus } from '@/types/enum'
import { MODEL_STATUS_LABELS, formatDate, formatPercent } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const modelId = String(route.params.modelId)

const detail = ref<ModelDetail | null>(null)
const drift = ref<ModelDrift | null>(null)
const killSwitches = ref<KillSwitchState[]>([])
const loading = ref(false)

const canaryDialogVisible = ref(false)
const canaryForm = reactive<{ traffic_percentage: number; observation_hours: number }>({
  traffic_percentage: 5,
  observation_hours: 72
})

const rollbackDialogVisible = ref(false)
const rollbackForm = reactive<{ target_model_id: string; reason: string }>({
  target_model_id: '',
  reason: ''
})

const retireDialogVisible = ref(false)
const retireForm = reactive<{ reason: string; data_retention_days: number }>({
  reason: '',
  data_retention_days: 90
})

const driftStatus = computed(() => drift.value?.drift_status || '-')
const driftColor = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  switch (drift.value?.drift_status) {
    case 'LOW':
      return 'success'
    case 'MEDIUM':
      return 'warning'
    case 'HIGH':
    case 'CRITICAL':
      return 'danger'
    default:
      return 'info'
  }
})

async function fetchAll() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const [d, dr, ks] = await Promise.all([
      getModel(modelId),
      getModelDrift(modelId).catch(() => null),
      getKillSwitchState().catch(() => [] as KillSwitchState[])
    ])
    detail.value = d
    drift.value = dr
    killSwitches.value = ks
  } finally {
    loading.value = false
    svc.close()
  }
}

function statusTagType(s: ModelStatus): 'info' | 'warning' | 'success' | 'danger' {
  if (s === ModelStatus.ACTIVE) return 'success'
  if (s === ModelStatus.CANARY) return 'warning'
  return 'info'
}

function openCanary() {
  canaryForm.traffic_percentage = 5
  canaryForm.observation_hours = 72
  canaryDialogVisible.value = true
}

async function submitCanary() {
  if (!detail.value) return
  const svc = ElLoading.service({ lock: true, text: '提交金丝雀...' })
  try {
    await startCanary(modelId, {
      candidate_model_id: modelId,
      traffic_percentage: canaryForm.traffic_percentage,
      observation_hours: canaryForm.observation_hours,
      approver_id: auth.user?.user_id || ''
    })
    ElMessage.success('金丝雀已启动')
    canaryDialogVisible.value = false
    await fetchAll()
  } finally {
    svc.close()
  }
}

function openPromote() {
  ElMessageBox.confirm('确认将模型晋升为 ACTIVE？此操作不可回滚至 CANARY 状态。', '晋升确认', {
    type: 'warning'
  })
    .then(async () => {
      const svc = ElLoading.service({ lock: true, text: '晋升中...' })
      try {
        await promoteModel(modelId, { approver_id: auth.user?.user_id || '' })
        ElMessage.success('已晋升')
        await fetchAll()
      } finally {
        svc.close()
      }
    })
    .catch(() => {})
}

function openRollback() {
  rollbackForm.target_model_id = ''
  rollbackForm.reason = ''
  rollbackDialogVisible.value = true
}

async function submitRollback() {
  if (!rollbackForm.target_model_id.trim() || !rollbackForm.reason.trim()) {
    ElMessage.warning('请填写目标模型 ID 与回滚原因')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '回滚中...' })
  try {
    await rollbackModel(modelId, {
      target_model_id: rollbackForm.target_model_id,
      reason: rollbackForm.reason,
      approver_id: auth.user?.user_id || ''
    })
    ElMessage.success('已回滚')
    rollbackDialogVisible.value = false
    await fetchAll()
  } finally {
    svc.close()
  }
}

function openRetire() {
  retireForm.reason = ''
  retireForm.data_retention_days = 90
  retireDialogVisible.value = true
}

async function submitRetire() {
  if (!retireForm.reason.trim()) {
    ElMessage.warning('请填写退役原因')
    return
  }
  await ElMessageBox.confirm('退役后模型将不再参与评分，确认退役？', '退役确认', { type: 'warning' })
  const svc = ElLoading.service({ lock: true, text: '退役中...' })
  try {
    await retireModel(modelId, {
      reason: retireForm.reason,
      approver_id: auth.user?.user_id || '',
      data_retention_days: retireForm.data_retention_days
    })
    ElMessage.success('已退役')
    retireDialogVisible.value = false
    await fetchAll()
  } finally {
    svc.close()
  }
}

onMounted(fetchAll)
</script>

<template>
  <div class="frd-page-container" v-loading="loading">
    <ElCard shadow="never" class="frd-card-margin">
      <template #header>
        <div class="frd-flex-between">
          <div>
            <span style="font-weight: 600; margin-right: 12px">{{ detail?.name }}</span>
            <ElTag v-if="detail" :type="statusTagType(detail.status)">
              {{ MODEL_STATUS_LABELS[detail.status] }}
            </ElTag>
            <ElTag style="margin-left: 8px">{{ detail?.type }}</ElTag>
            <ElTag style="margin-left: 8px">v{{ detail?.version }}</ElTag>
          </div>
          <div>
            <ElButton @click="router.push('/models')">返回列表</ElButton>
            <ElButton
              v-if="detail && (detail.status === ModelStatus.REGISTERED || detail.status === ModelStatus.CANARY)"
              type="warning"
              @click="openCanary"
            >
              启动/调整金丝雀
            </ElButton>
            <ElButton
              v-if="detail && detail.status === ModelStatus.CANARY"
              type="success"
              @click="openPromote"
            >
              晋升 ACTIVE
            </ElButton>
            <ElButton v-if="detail && detail.status !== ModelStatus.RETIRED" type="danger" @click="openRollback">
              紧急回滚
            </ElButton>
            <ElButton
              v-if="detail && detail.status !== ModelStatus.RETIRED"
              type="info"
              @click="openRetire"
            >
              退役
            </ElButton>
          </div>
        </div>
      </template>

      <ElDescriptions v-if="detail" :column="3" border>
        <ElDescriptionsItem label="模型 ID">{{ detail.model_id }}</ElDescriptionsItem>
        <ElDescriptionsItem label="名称">{{ detail.name }}</ElDescriptionsItem>
        <ElDescriptionsItem label="版本">{{ detail.version }}</ElDescriptionsItem>
        <ElDescriptionsItem label="运行时">{{ detail.runtime || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="入口">{{ detail.entrypoint || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="流量占比">{{ formatPercent(detail.traffic_share) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="注册时间">{{ formatDate(detail.registered_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="晋升时间">{{ formatDate(detail.promoted_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="训练时间">{{ formatDate(detail.trained_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="Artifacts SHA-256" :span="3">
          <code style="word-break: break-all">{{ detail.artifacts_sha256 }}</code>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="Artifacts 路径" :span="3">
          <code style="word-break: break-all">{{ detail.artifacts_path }}</code>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="描述" :span="3">{{ detail.description || '-' }}</ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <div class="frd-model-grid">
      <ElCard shadow="never" class="frd-card-margin">
        <template #header>性能指标</template>
        <ElDescriptions v-if="detail" :column="2" border>
          <ElDescriptionsItem label="AUC">{{ detail.metrics.auc?.toFixed(4) ?? '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="PR-AUC">{{ detail.metrics.pr_auc?.toFixed(4) ?? '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="Precision@1%">
            {{ formatPercent(detail.metrics.precision_at_1pct) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="Recall@1%">
            {{ formatPercent(detail.metrics.recall_at_1pct) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="KS">{{ detail.metrics.ks?.toFixed(4) ?? '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="F1">{{ detail.metrics.f1?.toFixed(4) ?? '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="MCC">{{ detail.metrics.mcc?.toFixed(4) ?? '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="PSI 7d">
            {{ detail.metrics.psi_7d?.toFixed(4) ?? '-' }}
          </ElDescriptionsItem>
        </ElDescriptions>
      </ElCard>

      <ElCard shadow="never">
        <template #header>
          <div class="frd-flex-between">
            <span>漂移监控</span>
            <ElTag :type="driftColor">{{ driftStatus }}</ElTag>
          </div>
        </template>
        <ElEmpty v-if="!drift" description="暂无漂移数据" :image-size="60" />
        <div v-else>
          <ElDescriptions :column="2" border>
            <ElDescriptionsItem label="PSI 1d">{{ drift.psi_1d.toFixed(4) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="PSI 7d">{{ drift.psi_7d.toFixed(4) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="KL 散度">{{ drift.kl_divergence.toFixed(4) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="最近检查">{{ formatDate(drift.last_checked_at) }}</ElDescriptionsItem>
          </ElDescriptions>
          <div style="margin-top: 12px; font-weight: 600; margin-bottom: 8px">特征级漂移</div>
          <ElTable :data="drift.feature_drifts" stripe size="small" max-height="320">
            <ElTableColumn prop="feature" label="特征" min-width="160" />
            <ElTableColumn prop="psi" label="PSI" width="100" align="right">
              <template #default="{ row }">{{ row.psi.toFixed(4) }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="100">
              <template #default="{ row }">
                <ElTag :type="row.status === 'HEALTHY' ? 'success' : row.status === 'WARNING' ? 'warning' : 'danger'">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
          </ElTable>
        </div>
      </ElCard>
    </div>

    <ElCard shadow="never" class="frd-card-margin">
      <template #header>Kill Switch 状态（L1-L4）</template>
      <ElEmpty v-if="!killSwitches.length" description="无活跃 Kill Switch" :image-size="60" />
      <ElTable v-else :data="killSwitches" stripe>
        <ElTableColumn prop="level" label="级别" width="120" />
        <ElTableColumn prop="scope" label="作用域" min-width="160" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="row.active ? 'danger' : 'info'">{{ row.active ? '活跃' : '冷却' }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="reason" label="原因" min-width="200" />
        <ElTableColumn label="触发时间" width="170">
          <template #default="{ row }">{{ formatDate(row.triggered_at) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="duration_minutes" label="时长(分钟)" width="110" align="right" />
      </ElTable>
    </ElCard>

    <ElDialog v-model="canaryDialogVisible" title="启动/调整金丝雀" width="480px">
      <ElForm :model="canaryForm" label-width="120px">
        <ElFormItem label="流量百分比">
          <ElInputNumber v-model="canaryForm.traffic_percentage" :min="1" :max="100" :step="5" style="width: 100%" />
        </ElFormItem>
        <ElFormItem label="观察时长(小时)">
          <ElInputNumber v-model="canaryForm.observation_hours" :min="24" :max="168" :step="24" style="width: 100%" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="canaryDialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="submitCanary">确认</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="rollbackDialogVisible" title="紧急回滚" width="520px">
      <ElForm :model="rollbackForm" label-width="120px">
        <ElFormItem label="目标模型 ID" required>
          <ElInput v-model="rollbackForm.target_model_id" placeholder="回滚目标模型 ID" />
        </ElFormItem>
        <ElFormItem label="回滚原因" required>
          <ElInput v-model="rollbackForm.reason" type="textarea" :rows="3" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="rollbackDialogVisible = false">取消</ElButton>
        <ElButton type="danger" @click="submitRollback">确认回滚</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="retireDialogVisible" title="退役模型" width="520px">
      <ElForm :model="retireForm" label-width="140px">
        <ElFormItem label="退役原因" required>
          <ElInput v-model="retireForm.reason" type="textarea" :rows="3" />
        </ElFormItem>
        <ElFormItem label="数据保留(天)">
          <ElInputNumber v-model="retireForm.data_retention_days" :min="0" :max="365" style="width: 100%" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="retireDialogVisible = false">取消</ElButton>
        <ElButton type="info" @click="submitRetire">确认退役</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.frd-model-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1200px) {
  .frd-model-grid {
    grid-template-columns: 1fr;
  }
}
</style>
