<script setup lang="ts">
/**
 * 交易详情（D06 §5.4 标签页：基本信息 / 模型解释 / 规则命中 / 图关系 / 历史行为 / 案件关联 / 反馈）
 */
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElTag,
  ElTabs,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElButton,
  ElEmpty,
  ElMessage,
  ElSkeleton
} from 'element-plus'
import { getTransaction, triggerShap, getShapResult, feedbackLabel } from '@/api/transaction'
import type { TransactionDetail, ShapResult } from '@/types/transaction'
import { Decision, RiskBand, FeedbackLabel } from '@/types/enum'
import {
  DECISION_LABELS,
  DECISION_TAG_TYPE,
  RISK_BAND_LABELS,
  RISK_BAND_TAG_TYPE,
  formatAmount,
  formatRiskScore,
  formatDate
} from '@/utils/format'

const route = useRoute()
const router = useRouter()
const txId = String(route.params.externalTxId)

const detail = ref<TransactionDetail | null>(null)
const shap = ref<ShapResult | null>(null)
const loading = ref(true)
const shapLoading = ref(false)

async function fetchDetail() {
  loading.value = true
  try {
    detail.value = await getTransaction(txId)
  } finally {
    loading.value = false
  }
}

async function fetchShap() {
  if (!detail.value) return
  shapLoading.value = true
  try {
    await triggerShap(detail.value.decision_id)
    shap.value = await getShapResult(detail.value.decision_id)
  } catch {
    // SHAP 可能尚未就绪
  } finally {
    shapLoading.value = false
  }
}

async function markFraud(label: FeedbackLabel) {
  await feedbackLabel({
    external_tx_id: txId,
    label,
    label_source: 'MANUAL_REVIEW',
    labeled_at: new Date().toISOString(),
    evidence: 'manual review from detail page'
  })
  ElMessage.success(label === FeedbackLabel.FRAUD ? '已标记为欺诈' : '已标记为非欺诈')
}

function goCase() {
  if (detail.value?.case_id) router.push(`/cases/${detail.value.case_id}`)
}

onMounted(fetchDetail)
</script>

<template>
  <div class="frd-page-container">
    <ElSkeleton :loading="loading" :rows="6" animated>
      <template #default>
        <ElCard v-if="detail" shadow="never" class="frd-card-margin">
          <template #header>
            <div class="frd-flex-between">
              <span>交易详情 · {{ detail.external_tx_id }}</span>
              <div>
                <ElTag :type="DECISION_TAG_TYPE[detail.decision]" size="large">{{ DECISION_LABELS[detail.decision] }}</ElTag>
                <ElTag :type="RISK_BAND_TAG_TYPE[detail.risk_band]" size="large" style="margin-left: 8px">
                  {{ RISK_BAND_LABELS[detail.risk_band] }} {{ formatRiskScore(detail.risk_score) }}
                </ElTag>
              </div>
            </div>
          </template>
          <ElDescriptions :column="3" border>
            <ElDescriptionsItem label="决策">{{ DECISION_LABELS[detail.decision] }}</ElDescriptionsItem>
            <ElDescriptionsItem label="风险评分">{{ formatRiskScore(detail.risk_score) }}</ElDescriptionsItem>
            <ElDescriptionsItem label="风险等级">{{ RISK_BAND_LABELS[detail.risk_band] }}</ElDescriptionsItem>
            <ElDescriptionsItem label="交易类型">{{ detail.tx_type }}</ElDescriptionsItem>
            <ElDescriptionsItem label="渠道">{{ detail.channel }}</ElDescriptionsItem>
            <ElDescriptionsItem label="3DS 验证">{{ detail.is_3ds_verified ? '是' : '否' }}</ElDescriptionsItem>
            <ElDescriptionsItem label="模型版本">{{ detail.model_version }}</ElDescriptionsItem>
            <ElDescriptionsItem label="决策 ID">{{ detail.decision_id }}</ElDescriptionsItem>
            <ElDescriptionsItem label="发生时间">{{ formatDate(detail.created_at) }}</ElDescriptionsItem>
          </ElDescriptions>
        </ElCard>

        <ElCard shadow="never" class="frd-card-margin">
          <ElTabs>
            <ElTabPane label="规则命中">
              <ElTable :data="detail?.rule_hits || []" stripe>
                <ElTableColumn prop="rule_id" label="规则 ID" width="120" />
                <ElTableColumn prop="rule_name" label="规则名称" />
                <ElTableColumn prop="severity" label="严重级别" width="120" />
              </ElTable>
              <ElEmpty v-if="!detail?.rule_hits?.length" description="未命中规则" />
            </ElTabPane>

            <ElTabPane label="模型解释（SHAP）">
              <ElButton type="primary" :loading="shapLoading" @click="fetchShap" style="margin-bottom: 12px">
                触发 SHAP 计算
              </ElButton>
              <ElTable v-if="shap" :data="shap.features" stripe>
                <ElTableColumn prop="name" label="特征" />
                <ElTableColumn prop="value" label="值" width="120" />
                <ElTableColumn prop="shap" label="SHAP 贡献" width="120" />
              </ElTable>
              <ElEmpty v-else description="点击上方按钮触发 SHAP 异步计算" />
            </ElTabPane>

            <ElTabPane label="案件关联">
              <ElButton v-if="detail?.case_id" type="primary" @click="goCase">查看案件 {{ detail.case_id }}</ElButton>
              <ElEmpty v-else description="未关联案件" />
            </ElTabPane>

            <ElTabPane label="反馈">
              <ElButton type="danger" @click="markFraud(FeedbackLabel.FRAUD)">标记为欺诈</ElButton>
              <ElButton type="success" @click="markFraud(FeedbackLabel.NOT_FRAUD)" style="margin-left: 8px">
                标记为非欺诈
              </ElButton>
            </ElTabPane>
          </ElTabs>
        </ElCard>
      </template>
    </ElSkeleton>
  </div>
</template>
