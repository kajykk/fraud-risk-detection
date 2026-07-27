<script setup lang="ts">
/**
 * 仪表盘
 * - 4 个 KPI 卡片：今日交易量 / 欺诈拦截量 / 通过率 / 申诉量（假数据占位）
 * - 2 个 ECharts 占位：趋势图（折线）+ 决策分布（饼图）
 * - 角色差异化显示：
 *   - MERCHANT_ADMIN：商户维度（自有商户）
 *   - RISK_MANAGER：团队维度（团队 KPI）
 *   - 其他：租户全局维度
 * 对齐 D06 §4（控制台概览）与 §13.2（商户仪表盘）
 */
import { computed, onMounted, ref, onBeforeUnmount } from 'vue'
import {
  ElCard,
  ElRow,
  ElCol,
  ElStatistic,
  ElTag,
  ElEmpty,
  ElDescriptions,
  ElDescriptionsItem
} from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { useAuthStore } from '@/stores/auth'
import { UserRole } from '@/types/enum'
import { formatPercent, formatAmount } from '@/utils/format'

use([CanvasRenderer, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent])

const authStore = useAuthStore()

const isMerchant = computed(() => authStore.roles.includes(UserRole.MERCHANT_ADMIN))
const isRiskManager = computed(() => authStore.roles.includes(UserRole.RISK_MANAGER))

const dimensionLabel = computed(() => {
  if (isMerchant.value) return '商户维度'
  if (isRiskManager.value) return '团队维度'
  return '租户全局'
})

// KPI 卡片占位数据（D06 §4.2 关键指标卡）
const kpi = ref({
  today_transactions: 128450,
  blocked_count: 850,
  case_count: 12,
  model_auc: 0.942,
  p99_latency_ms: 87,
  drift_psi_7d: 0.15,
  fraud_loss_prevented_cents: 5680000000,
  actual_loss_cents: 12000000,
  pass_rate: 0.985,
  appeal_count: 7
})

// 趋势图（近 7 天）
const trendOption = computed(() => ({
  title: { text: `${dimensionLabel.value} · 近 7 天交易与拦截趋势`, left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'axis' },
  legend: { data: ['交易量', '拦截量', '案件数'], bottom: 0 },
  grid: { left: 40, right: 20, top: 50, bottom: 40 },
  xAxis: {
    type: 'category',
    data: ['07-21', '07-22', '07-23', '07-24', '07-25', '07-26', '07-27']
  },
  yAxis: [
    { type: 'value', name: '交易量' },
    { type: 'value', name: '拦截量' }
  ],
  series: [
    { name: '交易量', type: 'line', smooth: true, data: [120000, 125000, 130000, 128000, 132000, 127000, 128450] },
    { name: '拦截量', type: 'line', smooth: true, yAxisIndex: 1, data: [820, 880, 910, 870, 930, 800, 850] },
    { name: '案件数', type: 'line', smooth: true, yAxisIndex: 1, data: [10, 14, 11, 13, 9, 15, 12] }
  ]
}))

// 决策分布饼图（对齐 D05 §4.1 decision 枚举）
const decisionOption = computed(() => ({
  title: { text: `${dimensionLabel.value} · 决策分布`, left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'item' },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      data: [
        { value: 126500, name: 'ALLOW 放行', itemStyle: { color: '#67c23a' } },
        { value: 1100, name: 'REVIEW 人工审核', itemStyle: { color: '#e6a23c' } },
        { value: 850, name: 'DENY 拒绝', itemStyle: { color: '#f56c6c' } },
        { value: 200, name: 'CHALLENGE 二次验证', itemStyle: { color: '#909399' } }
      ]
    }
  ]
}))

// 团队 KPI（仅 RISK_MANAGER 可见，对齐 D06 §14.6）
const teamKpi = ref([
  { member: '分析师 A', open_cases: 8, closed_this_week: 12, sla_rate: 0.96, accuracy: 0.92 },
  { member: '分析师 B', open_cases: 15, closed_this_week: 9, sla_rate: 0.88, accuracy: 0.9 },
  { member: '分析师 C', open_cases: 6, closed_this_week: 14, sla_rate: 0.98, accuracy: 0.94 }
])

onMounted(() => {
  // TODO: 调用 GET /reports/summary 拉取真实 KPI
})
onBeforeUnmount(() => {})
</script>

<template>
  <div class="frd-page-container">
    <div class="frd-dimension-tag">
      <ElTag :type="isMerchant ? 'warning' : isRiskManager ? 'success' : 'primary'">
        当前视角：{{ dimensionLabel }}
      </ElTag>
    </div>

    <!-- 4 KPI 卡片（D06 §4.2 / §13.2） -->
    <ElRow :gutter="16" class="frd-card-margin">
      <ElCol :xs="24" :sm="12" :md="6">
        <ElCard shadow="hover">
          <ElStatistic title="今日交易量" :value="kpi.today_transactions" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :sm="12" :md="6">
        <ElCard shadow="hover">
          <ElStatistic title="欺诈拦截量" :value="kpi.blocked_count" :value-style="{ color: '#f56c6c' }" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :sm="12" :md="6">
        <ElCard shadow="hover">
          <ElStatistic title="通过率" :value="kpi.pass_rate * 100" :precision="2" suffix="%" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :sm="12" :md="6">
        <ElCard shadow="hover">
          <ElStatistic title="申诉量" :value="kpi.appeal_count" :value-style="{ color: '#e6a23c' }" />
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- 次级指标（模型 AUC / P99 / PSI） -->
    <ElRow :gutter="16" class="frd-card-margin">
      <ElCol :xs="24" :sm="12" :md="8">
        <ElCard shadow="hover">
          <ElStatistic title="模型 AUC" :value="kpi.model_auc" :precision="4" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :sm="12" :md="8">
        <ElCard shadow="hover">
          <ElStatistic title="P99 延迟 (ms)" :value="kpi.p99_latency_ms" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :sm="12" :md="8">
        <ElCard shadow="hover">
          <ElStatistic title="漂移 PSI 7d" :value="kpi.drift_psi_7d" :precision="2" />
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- 趋势 + 饼图 -->
    <ElRow :gutter="16" class="frd-card-margin">
      <ElCol :xs="24" :md="14">
        <ElCard shadow="hover">
          <VChart :option="trendOption" autoresize style="height: 320px" />
        </ElCard>
      </ElCol>
      <ElCol :xs="24" :md="10">
        <ElCard shadow="hover">
          <VChart :option="decisionOption" autoresize style="height: 320px" />
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- 拦截挽回金额 -->
    <ElRow :gutter="16" class="frd-card-margin">
      <ElCol :span="24">
        <ElCard shadow="hover">
          <ElDescriptions :column="3" border>
            <ElDescriptionsItem label="欺诈挽回金额">
              {{ formatAmount(kpi.fraud_loss_prevented_cents) }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="实际损失金额">
              {{ formatAmount(kpi.actual_loss_cents) }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="通过率">
              {{ formatPercent(kpi.pass_rate) }}
            </ElDescriptionsItem>
          </ElDescriptions>
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- RISK_MANAGER 团队 KPI（D06 §14.6） -->
    <ElCard v-if="isRiskManager" shadow="hover" class="frd-card-margin">
      <template #header>团队 KPI 看板（近 7 天）</template>
      <ElDescriptions v-for="m in teamKpi" :key="m.member" :column="4" border class="frd-card-margin">
        <ElDescriptionsItem label="分析师">{{ m.member }}</ElDescriptionsItem>
        <ElDescriptionsItem label="当前待办">{{ m.open_cases }}</ElDescriptionsItem>
        <ElDescriptionsItem label="本周结案">{{ m.closed_this_week }}</ElDescriptionsItem>
        <ElDescriptionsItem label="SLA 达成率">{{ formatPercent(m.sla_rate) }}</ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <!-- MERCHANT_ADMIN 商户维度提示（D06 §13） -->
    <ElCard v-if="isMerchant" shadow="hover">
      <template #header>商户维度说明</template>
      <ElEmpty description="所有数据仅限自有商户范围（PostgreSQL RLS 强制隔离）" />
    </ElCard>
  </div>
</template>

<style scoped>
.frd-dimension-tag {
  margin-bottom: 16px;
}
</style>
