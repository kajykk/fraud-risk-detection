<script setup lang="ts">
/**
 * PIPL 合规工作台（D06 §11 + D05 §13）
 * 三个标签页：
 *   1. 同意管理（查询/撤回）
 *   2. 数据导出（申请/状态查询）
 *   3. 数据删除 / 更正（申请/状态查询）
 * 严格限定 TENANT_ADMIN / COMPLIANCE_OFFICER 可访问（路由层已校验）
 */
import { ref, reactive } from 'vue'
import {
  ElCard,
  ElTabs,
  ElTabPane,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElButton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElDatePicker,
  ElRadioGroup,
  ElRadio,
  ElSwitch,
  ElMessage,
  ElMessageBox,
  ElLoading
} from 'element-plus'
import {
  getConsent,
  withdrawConsent,
  requestDataExport,
  getDataExportStatus,
  requestDeletion,
  getDeletionStatus,
  requestRectification,
  type ConsentRecord,
  type ConsentListResult,
  type DataExportTask,
  type DeletionRequest
} from '@/api/pipl'
import { ConsentStatus, ConsentPurpose } from '@/types/enum'
import { CONSENT_STATUS_LABELS, formatDate } from '@/utils/format'

const activeTab = ref('consent')

// ===== 同意管理 =====
const consentQuery = reactive<{ user_id: string; purpose: ConsentPurpose | ''; status: ConsentStatus | '' }>({
  user_id: '',
  purpose: '',
  status: ''
})
const consentResult = ref<ConsentListResult | null>(null)
const consentLoading = ref(false)

async function fetchConsents() {
  if (!consentQuery.user_id.trim()) {
    ElMessage.warning('请输入用户 ID')
    return
  }
  consentLoading.value = true
  const svc = ElLoading.service({ lock: true, text: '查询中...' })
  try {
    consentResult.value = await getConsent(consentQuery.user_id, {
      purpose: consentQuery.purpose || undefined,
      status: consentQuery.status || undefined,
      include_history: true
    })
  } finally {
    consentLoading.value = false
    svc.close()
  }
}

async function onWithdraw(c: ConsentRecord) {
  try {
    const { value } = await ElMessageBox.prompt('输入撤回原因', '撤回同意', {
      inputType: 'textarea',
      confirmButtonText: '撤回',
      cancelButtonText: '取消'
    })
    const svc = ElLoading.service({ lock: true, text: '撤回中...' })
    try {
      // verification_token 由 COMPLIANCE_OFFICER 通过验证流程获取，此处占位
      await withdrawConsent({
        user_id: c.user_id,
        verification_token: 'officer-verified',
        consent_id: c.consent_id,
        withdrawal_reason: value ? 'OTHER' : undefined,
        effective_immediately: true
      })
      ElMessage.success('已撤回')
      await fetchConsents()
    } finally {
      svc.close()
    }
  } catch {
    /* 用户取消 */
  }
}

// ===== 数据导出 =====
const exportForm = reactive<{
  user_id: string
  scope: string
  format: 'JSON' | 'CSV' | 'XLSX'
  start_date: string
  end_date: string
}>({
  user_id: '',
  scope: 'all',
  format: 'JSON',
  start_date: '',
  end_date: ''
})
const exportTask = ref<DataExportTask | null>(null)
const exportStatusQuery = ref('')

async function submitExport() {
  if (!exportForm.user_id.trim()) {
    ElMessage.warning('请输入用户 ID')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '提交导出申请...' })
  try {
    exportTask.value = await requestDataExport({
      user_id: exportForm.user_id,
      verification_token: 'officer-verified',
      scope: exportForm.scope,
      format: exportForm.format,
      start_date: exportForm.start_date || undefined,
      end_date: exportForm.end_date || undefined
    })
    ElMessage.success(`导出任务已提交：${exportTask.value.task_id}`)
  } finally {
    svc.close()
  }
}

async function queryExportStatus() {
  if (!exportStatusQuery.value.trim()) {
    ElMessage.warning('请输入任务 ID')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '查询状态...' })
  try {
    exportTask.value = await getDataExportStatus(exportStatusQuery.value.trim())
  } finally {
    svc.close()
  }
}

// ===== 数据删除 / 更正 =====
const deleteForm = reactive<{
  user_id: string
  scope: string
  reason: 'USER_REQUEST' | 'CONSENT_WITHDRAWN' | 'DATA_RETENTION_EXPIRED' | 'LEGAL_OBLIGATION_END'
  retain_for_aml: boolean
  legal_hold_review: boolean
}>({
  user_id: '',
  scope: 'all',
  reason: 'USER_REQUEST',
  retain_for_aml: true,
  legal_hold_review: true
})
const deletionTask = ref<DeletionRequest | null>(null)
const deletionStatusQuery = ref('')

async function submitDeletion() {
  if (!deleteForm.user_id.trim()) {
    ElMessage.warning('请输入用户 ID')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '提交删除申请...' })
  try {
    deletionTask.value = await requestDeletion({
      user_id: deleteForm.user_id,
      verification_token: 'officer-verified',
      scope: deleteForm.scope.split(',').map((s) => s.trim()).filter(Boolean),
      reason: deleteForm.reason,
      retain_for_aml: deleteForm.retain_for_aml,
      legal_hold_review: deleteForm.legal_hold_review
    })
    ElMessage.success(`删除申请已提交：${deletionTask.value.request_id}`)
  } finally {
    svc.close()
  }
}

async function queryDeletionStatus() {
  if (!deletionStatusQuery.value.trim()) {
    ElMessage.warning('请输入申请 ID')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '查询状态...' })
  try {
    deletionTask.value = await getDeletionStatus(deletionStatusQuery.value.trim())
  } finally {
    svc.close()
  }
}

// 数据更正
const rectifyForm = reactive<{ user_id: string; field: string; current_value: string; corrected_value: string; evidence: string }>({
  user_id: '',
  field: '',
  current_value: '',
  corrected_value: '',
  evidence: ''
})
const rectifyLoading = ref(false)

async function submitRectification() {
  if (!rectifyForm.user_id.trim() || !rectifyForm.field.trim()) {
    ElMessage.warning('请填写用户 ID 与字段')
    return
  }
  rectifyLoading.value = true
  const svc = ElLoading.service({ lock: true, text: '提交更正申请...' })
  try {
    await requestRectification({
      user_id: rectifyForm.user_id,
      verification_token: 'officer-verified',
      reason: 'USER_REQUEST',
      corrections: [
        {
          resource_type: 'USER_PROFILE',
          resource_id: rectifyForm.user_id,
          field: rectifyForm.field,
          current_value: rectifyForm.current_value,
          corrected_value: rectifyForm.corrected_value,
          evidence: rectifyForm.evidence
        }
      ]
    })
    ElMessage.success('更正申请已提交')
    rectifyForm.field = ''
    rectifyForm.current_value = ''
    rectifyForm.corrected_value = ''
    rectifyForm.evidence = ''
  } finally {
    rectifyLoading.value = false
    svc.close()
  }
}
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never">
      <ElTabs v-model="activeTab">
        <!-- 同意管理 -->
        <ElTabPane label="同意管理" name="consent">
          <ElForm :inline="true" :model="consentQuery">
            <ElFormItem label="用户 ID">
              <ElInput v-model="consentQuery.user_id" placeholder="如 user_999" style="width: 220px" />
            </ElFormItem>
            <ElFormItem label="用途">
              <ElSelect v-model="consentQuery.purpose" placeholder="全部" clearable style="width: 200px">
                <ElOption v-for="p in Object.values(ConsentPurpose)" :key="p" :label="p" :value="p" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="状态">
              <ElSelect v-model="consentQuery.status" placeholder="全部" clearable style="width: 160px">
                <ElOption v-for="s in Object.values(ConsentStatus)" :key="s" :label="CONSENT_STATUS_LABELS[s]" :value="s" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem>
              <ElButton type="primary" :loading="consentLoading" @click="fetchConsents">查询</ElButton>
            </ElFormItem>
          </ElForm>

          <ElEmpty v-if="!consentResult" description="请输入用户 ID 后查询" :image-size="80" />
          <div v-else>
            <ElDescriptions :column="4" border size="small" style="margin-bottom: 12px">
              <ElDescriptionsItem label="活跃同意">{{ consentResult.summary.active_count }}</ElDescriptionsItem>
              <ElDescriptionsItem label="已撤回">{{ consentResult.summary.withdrawn_count }}</ElDescriptionsItem>
              <ElDescriptionsItem label="已过期">{{ consentResult.summary.expired_count }}</ElDescriptionsItem>
              <ElDescriptionsItem label="总数">{{ consentResult.total }}</ElDescriptionsItem>
            </ElDescriptions>
            <ElTable :data="consentResult.items" stripe>
              <ElTableColumn prop="consent_id" label="同意 ID" min-width="200" />
              <ElTableColumn prop="purpose" label="用途" width="180" />
              <ElTableColumn prop="legal_basis" label="法律基础" min-width="160" />
              <ElTableColumn label="状态" width="100">
                <template #default="{ row }">
                  <ElTag :type="row.status === ConsentStatus.GRANTED ? 'success' : row.status === ConsentStatus.WITHDRAWN ? 'danger' : 'info'">
                    {{ CONSENT_STATUS_LABELS[row.status as ConsentStatus] }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="授予时间" width="170">
                <template #default="{ row }">{{ formatDate(row.granted_at) }}</template>
              </ElTableColumn>
              <ElTableColumn label="过期时间" width="170">
                <template #default="{ row }">{{ formatDate(row.expires_at) }}</template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    v-if="row.status === ConsentStatus.GRANTED"
                    text
                    type="danger"
                    @click="onWithdraw(row)"
                  >
                    撤回
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
          </div>
        </ElTabPane>

        <!-- 数据导出 -->
        <ElTabPane label="数据导出" name="export">
          <div class="frd-pipl-grid">
            <ElCard shadow="never">
              <template #header>提交导出申请</template>
              <ElForm :model="exportForm" label-width="100px">
                <ElFormItem label="用户 ID" required>
                  <ElInput v-model="exportForm.user_id" />
                </ElFormItem>
                <ElFormItem label="范围">
                  <ElInput v-model="exportForm.scope" placeholder="如 all / transactions,consents" />
                </ElFormItem>
                <ElFormItem label="格式">
                  <ElSelect v-model="exportForm.format" style="width: 100%">
                    <ElOption label="JSON" value="JSON" />
                    <ElOption label="CSV" value="CSV" />
                    <ElOption label="XLSX" value="XLSX" />
                  </ElSelect>
                </ElFormItem>
                <ElFormItem label="起始日期">
                  <ElDatePicker v-model="exportForm.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
                </ElFormItem>
                <ElFormItem label="结束日期">
                  <ElDatePicker v-model="exportForm.end_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
                </ElFormItem>
                <ElFormItem>
                  <ElButton type="primary" @click="submitExport">提交申请</ElButton>
                </ElFormItem>
              </ElForm>
            </ElCard>

            <ElCard shadow="never">
              <template #header>查询导出状态</template>
              <ElForm :inline="true">
                <ElFormItem>
                  <ElInput v-model="exportStatusQuery" placeholder="任务 ID" style="width: 280px" />
                </ElFormItem>
                <ElFormItem>
                  <ElButton @click="queryExportStatus">查询</ElButton>
                </ElFormItem>
              </ElForm>
              <ElEmpty v-if="!exportTask" description="暂无导出任务" :image-size="80" />
              <ElDescriptions v-else :column="1" border size="small">
                <ElDescriptionsItem label="任务 ID">{{ exportTask.task_id }}</ElDescriptionsItem>
                <ElDescriptionsItem label="用户 ID">{{ exportTask.user_id }}</ElDescriptionsItem>
                <ElDescriptionsItem label="状态">
                  <ElTag>{{ exportTask.status }}</ElTag>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="下载链接" v-if="exportTask.download_url">
                  <a :href="exportTask.download_url" target="_blank">下载</a>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="过期时间">{{ formatDate(exportTask.expires_at) }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </div>
        </ElTabPane>

        <!-- 数据删除 / 更正 -->
        <ElTabPane label="数据删除 / 更正" name="delete">
          <div class="frd-pipl-grid">
            <ElCard shadow="never">
              <template #header>提交删除申请</template>
              <ElForm :model="deleteForm" label-width="120px">
                <ElFormItem label="用户 ID" required>
                  <ElInput v-model="deleteForm.user_id" />
                </ElFormItem>
                <ElFormItem label="范围">
                  <ElInput v-model="deleteForm.scope" placeholder="逗号分隔，如 transactions,consents" />
                </ElFormItem>
                <ElFormItem label="原因">
                  <ElSelect v-model="deleteForm.reason" style="width: 100%">
                    <ElOption label="用户请求" value="USER_REQUEST" />
                    <ElOption label="同意撤回" value="CONSENT_WITHDRAWN" />
                    <ElOption label="保留期到期" value="DATA_RETENTION_EXPIRED" />
                    <ElOption label="法律义务结束" value="LEGAL_OBLIGATION_END" />
                  </ElSelect>
                </ElFormItem>
                <ElFormItem label="AML 保留">
                  <ElSwitch v-model="deleteForm.retain_for_aml" />
                  <span style="margin-left: 8px; color: #909399">反洗钱 7 年保留</span>
                </ElFormItem>
                <ElFormItem label="法律 hold 复核">
                  <ElSwitch v-model="deleteForm.legal_hold_review" />
                </ElFormItem>
                <ElFormItem>
                  <ElButton type="danger" @click="submitDeletion">提交删除</ElButton>
                </ElFormItem>
              </ElForm>
            </ElCard>

            <ElCard shadow="never">
              <template #header>查询删除状态</template>
              <ElForm :inline="true">
                <ElFormItem>
                  <ElInput v-model="deletionStatusQuery" placeholder="申请 ID" style="width: 280px" />
                </ElFormItem>
                <ElFormItem>
                  <ElButton @click="queryDeletionStatus">查询</ElButton>
                </ElFormItem>
              </ElForm>
              <ElEmpty v-if="!deletionTask" description="暂无删除任务" :image-size="80" />
              <ElDescriptions v-else :column="1" border size="small">
                <ElDescriptionsItem label="申请 ID">{{ deletionTask.request_id }}</ElDescriptionsItem>
                <ElDescriptionsItem label="状态">
                  <ElTag>{{ deletionTask.status }}</ElTag>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="已删除">{{ deletionTask.deleted_count ?? 0 }}</ElDescriptionsItem>
                <ElDescriptionsItem label="已匿名化">{{ deletionTask.anonymized_count ?? 0 }}</ElDescriptionsItem>
                <ElDescriptionsItem label="保留">{{ deletionTask.retained_count ?? 0 }}</ElDescriptionsItem>
                <ElDescriptionsItem label="保留原因">{{ deletionTask.retention_reason || '-' }}</ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </div>

          <ElCard shadow="never" style="margin-top: 16px">
            <template #header>数据更正申请</template>
            <ElForm :model="rectifyForm" label-width="120px" :inline="true">
              <ElFormItem label="用户 ID" required>
                <ElInput v-model="rectifyForm.user_id" style="width: 200px" />
              </ElFormItem>
              <ElFormItem label="字段" required>
                <ElInput v-model="rectifyForm.field" placeholder="如 display_name" style="width: 200px" />
              </ElFormItem>
              <ElFormItem label="当前值">
                <ElInput v-model="rectifyForm.current_value" style="width: 200px" />
              </ElFormItem>
              <ElFormItem label="更正值">
                <ElInput v-model="rectifyForm.corrected_value" style="width: 200px" />
              </ElFormItem>
              <ElFormItem label="证据">
                <ElInput v-model="rectifyForm.evidence" placeholder="证据材料引用" style="width: 240px" />
              </ElFormItem>
              <ElFormItem>
                <ElButton type="primary" :loading="rectifyLoading" @click="submitRectification">提交更正</ElButton>
              </ElFormItem>
            </ElForm>
          </ElCard>
        </ElTabPane>
      </ElTabs>
    </ElCard>
  </div>
</template>

<style scoped>
.frd-pipl-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 1200px) {
  .frd-pipl-grid {
    grid-template-columns: 1fr;
  }
}
</style>
