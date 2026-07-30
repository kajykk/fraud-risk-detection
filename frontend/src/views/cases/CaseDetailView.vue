<script setup lang="ts">
/**
 * 案件详情（D06 §6.3）
 * 顶部：案件 ID、状态、优先级、SLA 倒计时
 * 左侧：关联交易、关联团伙、关联账户
 * 右侧：时间线、备注、附件
 * 操作：状态流转、添加备注、结案
 */
import { computed, onMounted, ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElTag,
  ElButton,
  ElTimeline,
  ElTimelineItem,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElDialog,
  ElSelect,
  ElOption,
  ElInputNumber,
  ElSwitch,
  ElMessage,
  ElMessageBox,
  ElLoading
} from 'element-plus'
import { getCase, getCaseTimeline, listCaseComments, addCaseComment, updateCase, closeCase } from '@/api/case'
import type { CaseDetail, CaseTimelineEvent, CaseComment } from '@/types/case'
import { CaseStatus } from '@/types/enum'
import {
  CASE_STATUS_LABELS,
  CASE_LEVEL_LABELS,
  formatDate,
  formatAmount,
  formatRelative
} from '@/utils/format'

const route = useRoute()
const router = useRouter()
const caseId = String(route.params.caseId)

const detail = ref<CaseDetail | null>(null)
const timeline = ref<CaseTimelineEvent[]>([])
const comments = ref<CaseComment[]>([])
const loading = ref(false)

const commentDraft = ref('')
const commentMentions = ref<string[]>([])

const statusDialogVisible = ref(false)
const statusForm = reactive<{ status: CaseStatus; comment: string }>({
  status: CaseStatus.OPEN,
  comment: ''
})

const closeDialogVisible = ref(false)
const closeForm = reactive<{
  conclusion: 'CONFIRMED_FRAUD' | 'FALSE_ALARM' | 'INCONCLUSIVE'
  loss_amount: number | undefined
  recovery_amount: number | undefined
  reportable_to_aml: boolean
  comment: string
}>({
  conclusion: 'CONFIRMED_FRAUD',
  loss_amount: undefined,
  recovery_amount: undefined,
  reportable_to_aml: false,
  comment: ''
})

const slaCountdown = computed(() => {
  if (!detail.value?.sla_deadline) return null
  const deadline = new Date(detail.value.sla_deadline).getTime()
  const now = Date.now()
  const diff = deadline - now
  if (diff <= 0) return { overdue: true, text: '已逾期' }
  const hours = Math.floor(diff / 3_600_000)
  const minutes = Math.floor((diff % 3_600_000) / 60_000)
  return { overdue: false, text: `${hours}小时 ${minutes}分钟` }
})

const isClosed = computed(() => detail.value?.status === CaseStatus.CLOSED)

async function fetchAll() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const [d, t, c] = await Promise.all([
      getCase(caseId),
      getCaseTimeline(caseId).catch(() => [] as CaseTimelineEvent[]),
      listCaseComments(caseId).catch(() => [] as CaseComment[])
    ])
    detail.value = d
    timeline.value = t
    comments.value = c
  } finally {
    loading.value = false
    svc.close()
  }
}

async function submitComment() {
  if (!commentDraft.value.trim()) {
    ElMessage.warning('请输入备注内容')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '提交中...' })
  try {
    const created = await addCaseComment(caseId, commentDraft.value, commentMentions.value)
    comments.value.push(created)
    commentDraft.value = ''
    commentMentions.value = []
    ElMessage.success('备注已提交')
  } finally {
    svc.close()
  }
}

function openStatusDialog() {
  if (!detail.value) return
  statusForm.status = detail.value.status
  statusForm.comment = ''
  statusDialogVisible.value = true
}

async function submitStatus() {
  const svc = ElLoading.service({ lock: true, text: '提交中...' })
  try {
    await updateCase(caseId, { status: statusForm.status, comment: statusForm.comment })
    ElMessage.success('状态已更新')
    statusDialogVisible.value = false
    await fetchAll()
  } finally {
    svc.close()
  }
}

function openCloseDialog() {
  closeForm.conclusion = 'CONFIRMED_FRAUD'
  closeForm.loss_amount = undefined
  closeForm.recovery_amount = undefined
  closeForm.reportable_to_aml = false
  closeForm.comment = ''
  closeDialogVisible.value = true
}

async function submitClose() {
  await ElMessageBox.confirm('结案后案件进入只读状态，确认结案？', '结案确认', {
    type: 'warning',
    confirmButtonText: '确认结案',
    cancelButtonText: '取消'
  })
  const svc = ElLoading.service({ lock: true, text: '结案中...' })
  try {
    await closeCase(caseId, {
      conclusion: closeForm.conclusion,
      loss_amount: closeForm.loss_amount,
      recovery_amount: closeForm.recovery_amount,
      reportable_to_aml: closeForm.reportable_to_aml,
      comment: closeForm.comment
    })
    ElMessage.success('案件已结案')
    closeDialogVisible.value = false
    await fetchAll()
  } finally {
    svc.close()
  }
}

function goTransaction(txId: string) {
  router.push(`/transactions/${txId}`)
}

onMounted(fetchAll)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin" v-loading="loading">
      <template #header>
        <div class="frd-flex-between">
          <div>
            <span style="font-weight: 600; margin-right: 12px">{{ detail?.case_id }}</span>
            <ElTag v-if="detail" :type="detail.priority === 'P0' || detail.priority === 'P1' ? 'danger' : 'info'">
              {{ CASE_LEVEL_LABELS[detail.priority] }}
            </ElTag>
            <ElTag v-if="detail" style="margin-left: 8px" :type="isClosed ? 'info' : 'success'">
              {{ CASE_STATUS_LABELS[detail.status] }}
            </ElTag>
            <ElTag
              v-if="slaCountdown"
              :type="slaCountdown.overdue ? 'danger' : 'warning'"
              style="margin-left: 8px"
            >
              SLA：{{ slaCountdown.text }}
            </ElTag>
          </div>
          <div>
            <ElButton @click="router.push('/cases')">返回列表</ElButton>
            <ElButton v-if="!isClosed" type="primary" @click="openStatusDialog">状态流转</ElButton>
            <ElButton v-if="!isClosed" type="danger" @click="openCloseDialog">结案</ElButton>
          </div>
        </div>
      </template>

      <ElDescriptions v-if="detail" :column="3" border>
        <ElDescriptionsItem label="标题">{{ detail.title || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="处理人">{{ detail.assignee_name || '未分配' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="创建时间">{{ formatDate(detail.created_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="SLA 截止">{{ formatDate(detail.sla_deadline) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="关联团伙">
          <ElButton
            v-if="detail.related_community_id"
            text
            type="primary"
            @click="router.push(`/gnn?community=${detail.related_community_id}`)"
          >
            {{ detail.related_community_id }}
          </ElButton>
          <span v-else>-</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="是否上报反洗钱">
          {{ detail.reportable_to_aml ? '是' : '否' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="损失金额">{{ formatAmount(detail.loss_amount_cents) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="挽回金额">{{ formatAmount(detail.recovery_amount_cents) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="结案结论">{{ detail.conclusion || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="描述" :span="3">{{ detail.description || '-' }}</ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <div class="frd-case-grid">
      <ElCard shadow="never" class="frd-card-margin">
        <template #header>关联交易</template>
        <ElEmpty v-if="!detail?.related_tx_ids?.length" description="无关联交易" :image-size="60" />
        <div v-else>
          <ElButton
            v-for="tx in detail.related_tx_ids"
            :key="tx"
            text
            type="primary"
            @click="goTransaction(tx)"
            style="display: block; margin-bottom: 4px"
          >
            {{ tx }}
          </ElButton>
        </div>
        <template v-if="detail?.related_account_ids?.length">
          <div style="margin-top: 12px; font-weight: 600">关联账户</div>
          <div v-for="acc in detail.related_account_ids" :key="acc" style="padding: 4px 0">{{ acc }}</div>
        </template>
      </ElCard>

      <ElCard shadow="never" class="frd-card-margin">
        <template #header>时间线</template>
        <ElEmpty v-if="!timeline.length" description="无时间线" :image-size="60" />
        <ElTimeline v-else>
          <ElTimelineItem
            v-for="e in timeline"
            :key="e.event_id"
            :timestamp="formatDate(e.created_at)"
            :type="e.event_type === 'CLOSED' ? 'success' : e.event_type === 'SLA_ESCALATED' ? 'danger' : 'primary'"
          >
            <div style="font-weight: 600">{{ e.event_type }} · {{ e.actor_name }}</div>
            <div style="color: #606266">{{ e.description }}</div>
          </ElTimelineItem>
        </ElTimeline>
      </ElCard>

      <ElCard shadow="never">
        <template #header>备注</template>
        <ElEmpty v-if="!comments.length" description="暂无备注" :image-size="60" />
        <div v-else style="max-height: 320px; overflow-y: auto">
          <div v-for="c in comments" :key="c.comment_id" style="padding: 8px 0; border-bottom: 1px solid #ebeef5">
            <div class="frd-flex-between">
              <span style="font-weight: 600">{{ c.author_name }}</span>
              <span style="color: #909399; font-size: 12px">{{ formatRelative(c.created_at) }}</span>
            </div>
            <div style="margin-top: 4px; white-space: pre-wrap">{{ c.content }}</div>
          </div>
        </div>
        <ElForm v-if="!isClosed" style="margin-top: 12px" label-position="top">
          <ElFormItem label="新增备注">
            <ElInput v-model="commentDraft" type="textarea" :rows="3" placeholder="输入备注内容，@提及同事" />
          </ElFormItem>
          <ElFormItem>
            <ElButton type="primary" @click="submitComment">提交备注</ElButton>
          </ElFormItem>
        </ElForm>
      </ElCard>
    </div>

    <ElDialog v-model="statusDialogVisible" title="状态流转" width="480px">
      <ElForm :model="statusForm" label-width="80px">
        <ElFormItem label="目标状态">
          <ElSelect v-model="statusForm.status" style="width: 100%">
            <ElOption
              v-for="s in Object.values(CaseStatus)"
              :key="s"
              :label="CASE_STATUS_LABELS[s]"
              :value="s"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="备注">
          <ElInput v-model="statusForm.comment" type="textarea" :rows="3" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="statusDialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="submitStatus">确认</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="closeDialogVisible" title="结案" width="560px">
      <ElForm :model="closeForm" label-width="120px">
        <ElFormItem label="结案结论">
          <ElSelect v-model="closeForm.conclusion" style="width: 100%">
            <ElOption label="确认欺诈" value="CONFIRMED_FRAUD" />
            <ElOption label="误报" value="FALSE_ALARM" />
            <ElOption label="证据不足" value="INCONCLUSIVE" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="损失金额（分）">
          <ElInputNumber v-model="closeForm.loss_amount" :min="0" :step="100" style="width: 100%" />
        </ElFormItem>
        <ElFormItem label="挽回金额（分）">
          <ElInputNumber v-model="closeForm.recovery_amount" :min="0" :step="100" style="width: 100%" />
        </ElFormItem>
        <ElFormItem label="上报反洗钱">
          <ElSwitch v-model="closeForm.reportable_to_aml" />
        </ElFormItem>
        <ElFormItem label="结案说明">
          <ElInput v-model="closeForm.comment" type="textarea" :rows="3" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="closeDialogVisible = false">取消</ElButton>
        <ElButton type="danger" @click="submitClose">确认结案</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.frd-case-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}
@media (max-width: 1200px) {
  .frd-case-grid {
    grid-template-columns: 1fr;
  }
}
</style>
