<script setup lang="ts">
/**
 * 案件列表（D06 §6.1）
 * 支持视图：全部案件 / 我的待办 / 未分配 / 已逾期 / 已关闭
 */
import { onMounted, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElSelect,
  ElOption,
  ElButton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElPagination,
  ElRadioGroup,
  ElRadioButton,
  ElLoading
} from 'element-plus'
import { listCases } from '@/api/case'
import type { CaseListItem } from '@/types/case'
import { CaseStatus, CaseLevel } from '@/types/enum'
import { CASE_STATUS_LABELS, CASE_LEVEL_LABELS, formatDate } from '@/utils/format'

const router = useRouter()
const loading = ref(false)
const list = ref<CaseListItem[]>([])
const total = ref(0)

const query = reactive({
  view: 'all',
  status: '' as CaseStatus | '',
  priority: '' as CaseLevel | '',
  page: 1,
  page_size: 20
})

async function fetchData() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const params = {
      ...query,
      status: query.status || undefined,
      priority: query.priority || undefined
    }
    const res = await listCases(params)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
    svc.close()
  }
}

function goDetail(row: CaseListItem) {
  router.push(`/cases/${row.case_id}`)
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <ElRadioGroup v-model="query.view" @change="fetchData" style="margin-bottom: 12px">
        <ElRadioButton value="all">全部案件</ElRadioButton>
        <ElRadioButton value="todo">我的待办</ElRadioButton>
        <ElRadioButton value="unassigned">未分配</ElRadioButton>
        <ElRadioButton value="overdue">已逾期</ElRadioButton>
        <ElRadioButton value="closed">已关闭</ElRadioButton>
      </ElRadioGroup>

      <ElForm :inline="true" :model="query">
        <ElFormItem label="状态">
          <ElSelect v-model="query.status" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="s in Object.values(CaseStatus)" :key="s" :label="CASE_STATUS_LABELS[s]" :value="s" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="优先级">
          <ElSelect v-model="query.priority" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="p in Object.values(CaseLevel)" :key="p" :label="CASE_LEVEL_LABELS[p]" :value="p" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" @click="fetchData">查询</ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe @row-dblclick="goDetail">
        <ElTableColumn prop="case_id" label="案件 ID" min-width="180" />
        <ElTableColumn label="优先级" width="100">
          <template #default="{ row }">
            <ElTag :type="row.priority === 'P0' || row.priority === 'P1' ? 'danger' : 'info'">
              {{ CASE_LEVEL_LABELS[row.priority as CaseLevel] }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="110">
          <template #default="{ row }">{{ CASE_STATUS_LABELS[row.status as CaseStatus] }}</template>
        </ElTableColumn>
        <ElTableColumn prop="assignee_name" label="处理人" width="120" />
        <ElTableColumn label="SLA 截止" width="180">
          <template #default="{ row }">{{ formatDate(row.sla_deadline) }}</template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
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
