<script setup lang="ts">
/**
 * 审计日志（D06 §11.1）
 * 权限：TENANT_ADMIN / AUDITOR / COMPLIANCE_OFFICER
 * 功能：查询条件 + 表格 + 详情抽屉（before/after diff）
 */
import { onMounted, ref, reactive } from 'vue'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElDatePicker,
  ElButton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElPagination,
  ElDrawer,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElLoading,
  ElMessage
} from 'element-plus'
import { listAuditLogs, type AuditLogItem, type AuditLogQuery } from '@/api/audit'
import { formatDate } from '@/utils/format'

const loading = ref(false)
const list = ref<AuditLogItem[]>([])
const total = ref(0)

const query = reactive<AuditLogQuery & { page: number; page_size: number }>({
  actor_id: '',
  resource_type: '',
  resource_id: '',
  action: '',
  trace_id: '',
  start_time: '' as string,
  end_time: '' as string,
  page: 1,
  page_size: 20
})

const dateRange = ref<[string, string] | null>(null)

const detailVisible = ref(false)
const detail = ref<AuditLogItem | null>(null)

const resourceTypeOptions = [
  'TRANSACTION',
  'SCORE',
  'RULE',
  'MODEL',
  'CASE',
  'WEBHOOK',
  'CONSENT',
  'DELETION_REQUEST',
  'USER',
  'TENANT',
  'KILL_SWITCH'
]
const actionOptions = ['CREATE', 'UPDATE', 'DELETE', 'PROMOTE', 'ROLLBACK', 'LOGIN', 'LOGOUT', 'EXPORT', 'GRANT', 'WITHDRAW']
const resultTagType: Record<string, 'success' | 'warning' | 'danger'> = {
  SUCCESS: 'success',
  FAILURE: 'warning',
  DENIED: 'danger'
}

async function fetchData() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    if (dateRange.value) {
      query.start_time = dateRange.value[0]
      query.end_time = dateRange.value[1]
    } else {
      query.start_time = ''
      query.end_time = ''
    }
    const params = {
      ...query,
      actor_id: query.actor_id || undefined,
      resource_type: query.resource_type || undefined,
      resource_id: query.resource_id || undefined,
      action: query.action || undefined,
      trace_id: query.trace_id || undefined,
      start_time: query.start_time || undefined,
      end_time: query.end_time || undefined
    }
    const res = await listAuditLogs(params)
    list.value = res.items
    total.value = res.total
    if (!res.items.length) ElMessage.info('未查询到审计日志')
  } finally {
    loading.value = false
    svc.close()
  }
}

function showDetail(row: AuditLogItem) {
  detail.value = row
  detailVisible.value = true
}

function resetQuery() {
  query.actor_id = ''
  query.resource_type = ''
  query.resource_id = ''
  query.action = ''
  query.trace_id = ''
  dateRange.value = null
  query.page = 1
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <ElForm :inline="true" :model="query">
        <ElFormItem label="操作人 ID">
          <ElInput v-model="query.actor_id" clearable style="width: 180px" />
        </ElFormItem>
        <ElFormItem label="资源类型">
          <ElSelect v-model="query.resource_type" placeholder="全部" clearable filterable style="width: 180px">
            <ElOption v-for="r in resourceTypeOptions" :key="r" :label="r" :value="r" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="资源 ID">
          <ElInput v-model="query.resource_id" clearable style="width: 200px" />
        </ElFormItem>
        <ElFormItem label="动作">
          <ElSelect v-model="query.action" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="a in actionOptions" :key="a" :label="a" :value="a" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="Trace ID">
          <ElInput v-model="query.trace_id" clearable style="width: 200px" />
        </ElFormItem>
        <ElFormItem label="时间范围">
          <ElDatePicker
            v-model="dateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            style="width: 360px"
          />
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" @click="fetchData">查询</ElButton>
          <ElButton @click="resetQuery">重置</ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe @row-click="showDetail">
        <ElTableColumn prop="occurred_at" label="发生时间" width="170">
          <template #default="{ row }">{{ formatDate(row.occurred_at) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="actor_name" label="操作人" width="140">
          <template #default="{ row }">{{ row.actor_name || row.actor_id }}</template>
        </ElTableColumn>
        <ElTableColumn prop="actor_role" label="角色" width="160" />
        <ElTableColumn prop="action" label="动作" width="120" />
        <ElTableColumn prop="resource_type" label="资源类型" width="140" />
        <ElTableColumn prop="resource_id" label="资源 ID" min-width="200" />
        <ElTableColumn label="结果" width="100">
          <template #default="{ row }">
            <ElTag :type="resultTagType[row.result] || 'info'">{{ row.result }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="ip_address" label="IP" width="140" />
        <ElTableColumn prop="trace_id" label="Trace ID" min-width="200" />
      </ElTable>

      <ElPagination
        v-model:current-page="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        :page-sizes="[20, 50, 100, 200]"
        @current-change="fetchData"
        @size-change="fetchData"
        style="margin-top: 16px; justify-content: flex-end"
      />
    </ElCard>

    <ElDrawer v-model="detailVisible" title="审计日志详情" size="640px">
      <ElEmpty v-if="!detail" description="无数据" :image-size="80" />
      <div v-else>
        <ElDescriptions :column="1" border size="small">
          <ElDescriptionsItem label="日志 ID">{{ detail.log_id }}</ElDescriptionsItem>
          <ElDescriptionsItem label="发生时间">{{ formatDate(detail.occurred_at) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="操作人">{{ detail.actor_name || detail.actor_id }}（{{ detail.actor_role || '-' }}）</ElDescriptionsItem>
          <ElDescriptionsItem label="租户 ID">{{ detail.tenant_id }}</ElDescriptionsItem>
          <ElDescriptionsItem label="动作">{{ detail.action }}</ElDescriptionsItem>
          <ElDescriptionsItem label="资源类型">{{ detail.resource_type }}</ElDescriptionsItem>
          <ElDescriptionsItem label="资源 ID">{{ detail.resource_id || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="结果">
            <ElTag :type="resultTagType[detail.result] || 'info'">{{ detail.result }}</ElTag>
          </ElDescriptionsItem>
          <ElDescriptionsItem label="IP">{{ detail.ip_address || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="User-Agent">{{ detail.user_agent || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="Trace ID">{{ detail.trace_id || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="Request ID">{{ detail.request_id || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="哈希链(前)">{{ detail.hash_chain_prev || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="哈希链(当前)">{{ detail.hash_current || '-' }}</ElDescriptionsItem>
        </ElDescriptions>

        <div style="margin-top: 16px; font-weight: 600; margin-bottom: 8px">变更前</div>
        <pre style="background: #f5f7fa; padding: 8px; border-radius: 4px; max-height: 200px; overflow: auto">{{
          JSON.stringify(detail.before, null, 2)
        }}</pre>
        <div style="margin-top: 12px; font-weight: 600; margin-bottom: 8px">变更后</div>
        <pre style="background: #f5f7fa; padding: 8px; border-radius: 4px; max-height: 200px; overflow: auto">{{
          JSON.stringify(detail.after, null, 2)
        }}</pre>
      </div>
    </ElDrawer>
  </div>
</template>
