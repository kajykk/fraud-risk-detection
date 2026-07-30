<script setup lang="ts">
/**
 * GNN 团伙检测（D06 §9）
 * 功能：
 *   1. k-hop 邻居查询（默认 2 跳），vis-network 可视化
 *   2. 触发团伙检测异步任务（LOUVAIN/LABEL_PROP/WALKTRAP）
 *   3. 任务状态轮询与结果展示
 *   4. 团伙详情查看（关联案件 ID）
 */
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElInputNumber,
  ElButton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElMessage,
  ElLoading
} from 'element-plus'
import { Network, type Options as NetworkOptions } from 'vis-network'
import { DataSet } from 'vis-data'
import {
  getRelated,
  detectCommunity,
  getCommunityTask,
  getCommunity,
  type GraphNode,
  type GraphEdge,
  type CommunityDetectionTask,
  type CommunityDetail
} from '@/api/gnn'
import { GnnAlgorithm } from '@/types/enum'
import { formatAmount, formatDate, formatPercent } from '@/utils/format'

const route = useRoute()
const seedInput = ref(String(route.query.seed || ''))
const kHop = ref(2)
const edgeTypes = ref('USES,PAYS_TO,FROM_IP,BINDS_TO')
const timeWindowHours = ref(72)
const nodeLimit = ref(200)
const graphLoading = ref(false)

const nodesDs = new DataSet<GraphNode & { id: string; label: string }>()
const edgesDs = new DataSet<GraphEdge & { id: string }>()
const networkContainer = ref<HTMLElement | null>(null)
let network: Network | null = null

const nodeTypeColor: Record<string, string> = {
  Account: '#0b5fff',
  Merchant: '#67c23a',
  Device: '#e6a23c',
  IP: '#909399',
  Card: '#f56c6c'
}

const networkOptions: NetworkOptions = {
  nodes: { shape: 'dot', size: 16, font: { size: 12 } },
  edges: { arrows: 'to', color: '#c0c4cc', font: { size: 10, align: 'middle' } },
  physics: { stabilization: { iterations: 200 } },
  interaction: { hover: true, tooltipDelay: 200 }
}

function initNetwork() {
  if (!networkContainer.value || network) return
  network = new Network(networkContainer.value, { nodes: nodesDs, edges: edgesDs }, networkOptions)
}

async function fetchRelated() {
  if (!seedInput.value.trim()) {
    ElMessage.warning('请输入种子节点 ID')
    return
  }
  graphLoading.value = true
  const svc = ElLoading.service({ lock: true, text: '查询子图...' })
  try {
    const res = await getRelated(seedInput.value.trim(), {
      k: kHop.value,
      edge_types: edgeTypes.value,
      time_window_hours: timeWindowHours.value,
      limit: nodeLimit.value
    })
    nodesDs.clear()
    edgesDs.clear()
    const seedNode: GraphNode & { id: string; label: string } = {
      ...res.seed_node,
      id: res.seed_node.id,
      label: `${res.seed_node.type}::${res.seed_node.id}`
    }
    nodesDs.add(seedNode)
    for (const n of res.nodes) {
      if (n.id === seedNode.id) continue
      nodesDs.add({
        ...n,
        id: n.id,
        label: `${n.type}::${n.id}`,
        color: nodeTypeColor[n.type] || '#909399'
      } as any)
    }
    for (const e of res.edges) {
      edgesDs.add({
        ...e,
        id: `${e.from}-${e.to}-${e.type}`,
        label: e.type
      } as any)
    }
    if (!network) initNetwork()
    ElMessage.success(`已加载 ${res.total_nodes} 个节点（耗时 ${res.evaluated_at_ms}ms）`)
  } finally {
    graphLoading.value = false
    svc.close()
  }
}

// 团伙检测
const detectForm = reactive({
  seed_account_id: '',
  depth: 3,
  time_window_hours: 168,
  min_confidence: 0.7,
  algorithm: GnnAlgorithm.LOUVAIN
})
const currentTask = ref<CommunityDetectionTask | null>(null)
const communityDetail = ref<CommunityDetail | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function startDetect() {
  if (!detectForm.seed_account_id.trim()) {
    detectForm.seed_account_id = seedInput.value
    if (!detectForm.seed_account_id.trim()) {
      ElMessage.warning('请输入种子账户 ID')
      return
    }
  }
  const svc = ElLoading.service({ lock: true, text: '提交检测任务...' })
  try {
    currentTask.value = await detectCommunity({
      seed_account_id: detectForm.seed_account_id,
      depth: detectForm.depth,
      time_window_hours: detectForm.time_window_hours,
      min_confidence: detectForm.min_confidence,
      algorithm: detectForm.algorithm
    })
    ElMessage.success(`检测任务已提交：${currentTask.value.task_id}`)
    startPolling()
  } finally {
    svc.close()
  }
}

function startPolling() {
  stopPolling()
  if (!currentTask.value) return
  pollTimer = setInterval(async () => {
    if (!currentTask.value) return
    try {
      const t = await getCommunityTask(currentTask.value.task_id)
      currentTask.value = t
      if (t.status === 'SUCCEEDED' && t.communities?.length) {
        ElMessage.success(`检测完成，识别 ${t.communities.length} 个团伙`)
        await loadCommunity(t.communities[0])
        stopPolling()
      } else if (t.status === 'FAILED' || t.status === 'TIMEOUT') {
        ElMessage.error(`检测${t.status === 'TIMEOUT' ? '超时' : '失败'}`)
        stopPolling()
      }
    } catch {
      stopPolling()
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadCommunity(communityId: string) {
  const svc = ElLoading.service({ lock: true, text: '加载团伙详情...' })
  try {
    communityDetail.value = await getCommunity(communityId)
  } finally {
    svc.close()
  }
}

watch(
  () => route.query.community,
  (cid) => {
    if (typeof cid === 'string' && cid) loadCommunity(cid)
  }
)

onMounted(() => {
  initNetwork()
  if (route.query.community) {
    loadCommunity(String(route.query.community))
  }
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <template #header>k-hop 子图查询</template>
      <ElForm :inline="true" :model="{}">
        <ElFormItem label="种子节点 ID">
          <ElInput v-model="seedInput" placeholder="如 user_999 / mch_001" style="width: 240px" />
        </ElFormItem>
        <ElFormItem label="跳数 K">
          <ElInputNumber v-model="kHop" :min="1" :max="4" />
        </ElFormItem>
        <ElFormItem label="边类型">
          <ElInput v-model="edgeTypes" placeholder="逗号分隔" style="width: 280px" />
        </ElFormItem>
        <ElFormItem label="时间窗(小时)">
          <ElInputNumber v-model="timeWindowHours" :min="1" :max="720" />
        </ElFormItem>
        <ElFormItem label="节点上限">
          <ElInputNumber v-model="nodeLimit" :min="10" :max="1000" :step="50" />
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" :loading="graphLoading" @click="fetchRelated">查询子图</ElButton>
        </ElFormItem>
      </ElForm>
      <div ref="networkContainer" style="height: 420px; border: 1px solid #ebeef5; background: #fafafa" />
    </ElCard>

    <div class="frd-gnn-grid">
      <ElCard shadow="never" class="frd-card-margin">
        <template #header>团伙检测任务</template>
        <ElForm :model="detectForm" label-width="120px">
          <ElFormItem label="种子账户 ID">
            <ElInput v-model="detectForm.seed_account_id" placeholder="留空则使用上方种子节点" />
          </ElFormItem>
          <ElFormItem label="深度">
            <ElInputNumber v-model="detectForm.depth" :min="1" :max="6" />
          </ElFormItem>
          <ElFormItem label="时间窗(小时)">
            <ElInputNumber v-model="detectForm.time_window_hours" :min="1" :max="2160" />
          </ElFormItem>
          <ElFormItem label="最小置信度">
            <ElInputNumber v-model="detectForm.min_confidence" :min="0" :max="1" :step="0.05" />
          </ElFormItem>
          <ElFormItem label="算法">
            <ElSelect v-model="detectForm.algorithm" style="width: 100%">
              <ElOption v-for="a in Object.values(GnnAlgorithm)" :key="a" :label="a" :value="a" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem>
            <ElButton type="primary" @click="startDetect">提交检测</ElButton>
          </ElFormItem>
        </ElForm>

        <div v-if="currentTask" style="margin-top: 12px">
          <ElDescriptions :column="1" border size="small">
            <ElDescriptionsItem label="任务 ID">{{ currentTask.task_id }}</ElDescriptionsItem>
            <ElDescriptionsItem label="状态">
              <ElTag :type="currentTask.status === 'SUCCEEDED' ? 'success' : currentTask.status === 'FAILED' ? 'danger' : 'warning'">
                {{ currentTask.status }}
              </ElTag>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="进度">{{ formatPercent(currentTask.progress || 0) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="识别团伙数">{{ currentTask.communities?.length || 0 }}</ElDescriptionsItem>
          </ElDescriptions>
        </div>
      </ElCard>

      <ElCard shadow="never">
        <template #header>团伙详情</template>
        <ElEmpty v-if="!communityDetail" description="暂无团伙详情" :image-size="60" />
        <div v-else>
          <ElDescriptions :column="2" border size="small">
            <ElDescriptionsItem label="团伙 ID">{{ communityDetail.community_id }}</ElDescriptionsItem>
            <ElDescriptionsItem label="置信度">{{ formatPercent(communityDetail.confidence) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="规模">{{ communityDetail.size }}</ElDescriptionsItem>
            <ElDescriptionsItem label="算法">{{ communityDetail.algorithm }}</ElDescriptionsItem>
            <ElDescriptionsItem label="涉及金额">{{ formatAmount(communityDetail.total_amount) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="检测时间">{{ formatDate(communityDetail.detected_at) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="关联案件 ID">
              <span v-if="communityDetail.case_id">{{ communityDetail.case_id }}</span>
              <span v-else>-</span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="模型 ID">{{ communityDetail.model_id }}</ElDescriptionsItem>
          </ElDescriptions>
          <div style="margin-top: 12px; font-weight: 600; margin-bottom: 8px">团伙成员</div>
          <ElTable :data="communityDetail.nodes" stripe size="small" max-height="280">
            <ElTableColumn prop="id" label="节点 ID" min-width="180" />
            <ElTableColumn prop="type" label="类型" width="100" />
            <ElTableColumn label="风险分" width="100" align="right">
              <template #default="{ row }">{{ row.risk_score?.toFixed(4) ?? '-' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="centrality" label="中心度" width="100" align="right" />
          </ElTable>
        </div>
      </ElCard>
    </div>
  </div>
</template>

<style scoped>
.frd-gnn-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 1200px) {
  .frd-gnn-grid {
    grid-template-columns: 1fr;
  }
}
</style>
