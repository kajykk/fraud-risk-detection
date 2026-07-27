<script setup lang="ts">
/**
 * 交易列表（实时监控）
 * 对齐 D06 §5（实时交易监控）与 D05 §4.6
 */
import { onMounted, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
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
  ElLoading
} from 'element-plus'
import { listTransactions } from '@/api/transaction'
import type { TransactionDetail } from '@/types/transaction'
import { Decision, RiskBand } from '@/types/enum'
import { DECISION_LABELS, DECISION_TAG_TYPE, RISK_BAND_LABELS, RISK_BAND_TAG_TYPE, formatAmount, formatRiskScore, formatDate } from '@/utils/format'

const router = useRouter()
const loading = ref(false)
const list = ref<TransactionDetail[]>([])
const total = ref(0)

const query = reactive({
  external_tx_id: '',
  decision: '' as Decision | '',
  risk_band: '' as RiskBand | '',
  page: 1,
  page_size: 20
})

async function fetchData() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const params = {
      ...query,
      decision: query.decision || undefined,
      risk_band: query.risk_band || undefined
    }
    const res = await listTransactions(params)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
    svc.close()
  }
}

function handleSearch() {
  query.page = 1
  fetchData()
}

function handleReset() {
  query.external_tx_id = ''
  query.decision = ''
  query.risk_band = ''
  query.page = 1
  fetchData()
}

function goDetail(row: TransactionDetail) {
  router.push(`/transactions/${encodeURIComponent(row.external_tx_id)}`)
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <ElForm :inline="true" :model="query">
        <ElFormItem label="交易号">
          <ElInput v-model="query.external_tx_id" placeholder="external_tx_id" clearable />
        </ElFormItem>
        <ElFormItem label="决策">
          <ElSelect v-model="query.decision" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="d in Object.values(Decision)" :key="d" :label="DECISION_LABELS[d]" :value="d" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="风险等级">
          <ElSelect v-model="query.risk_band" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="r in Object.values(RiskBand)" :key="r" :label="RISK_BAND_LABELS[r]" :value="r" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" @click="handleSearch">查询</ElButton>
          <ElButton @click="handleReset">重置</ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe @row-dblclick="goDetail">
        <ElTableColumn prop="external_tx_id" label="交易号" min-width="180" />
        <ElTableColumn prop="tx_type" label="类型" width="90" />
        <ElTableColumn label="金额" width="120">
          <template #default="{ row }">{{ formatAmount(row.metadata?.amount as number) }}</template>
        </ElTableColumn>
        <ElTableColumn label="决策" width="110">
          <template #default="{ row }">
            <ElTag :type="DECISION_TAG_TYPE[row.decision as Decision]">{{ DECISION_LABELS[row.decision as Decision] }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="风险评分" width="100">
          <template #default="{ row }">{{ formatRiskScore(row.risk_score) }}</template>
        </ElTableColumn>
        <ElTableColumn label="风险等级" width="100">
          <template #default="{ row }">
            <ElTag :type="RISK_BAND_TAG_TYPE[row.risk_band as RiskBand]">{{ RISK_BAND_LABELS[row.risk_band as RiskBand] }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="channel" label="渠道" width="80" />
        <ElTableColumn label="时间" width="180">
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
