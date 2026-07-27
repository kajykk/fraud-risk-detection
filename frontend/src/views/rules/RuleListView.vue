<script setup lang="ts">
/**
 * 规则列表（D06 §7.1）
 * 规则生命周期：DRAFT → CANARY → ACTIVE → RETIRED
 * 操作：新建、编辑、灰度推进、回滚、下线
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
  ElMessageBox,
  ElMessage,
  ElLoading
} from 'element-plus'
import { listRules, deleteRule, promoteRule, rollbackRule, retireRule } from '@/api/rule'
import type { RuleListItem } from '@/types/rule'
import { RuleStatus, RuleAction, RuleSeverity, Channel } from '@/types/enum'
import {
  RULE_STATUS_LABELS,
  formatDate,
  formatPercent
} from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const list = ref<RuleListItem[]>([])
const total = ref(0)

const query = reactive({
  status: '' as RuleStatus | '',
  action: '' as RuleAction | '',
  severity: '' as RuleSeverity | '',
  channel: '' as Channel | '',
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
      action: query.action || undefined,
      severity: query.severity || undefined,
      channel: query.channel || undefined
    }
    const res = await listRules(params)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
    svc.close()
  }
}

function goEdit(row: RuleListItem) {
  router.push(`/rules/${row.rule_id}/edit`)
}

function goCreate() {
  router.push('/rules/create')
}

async function promote(row: RuleListItem) {
  try {
    const { value } = await ElMessageBox.prompt('输入灰度百分比（0-100）', '灰度推进', {
      inputType: 'number',
      inputValue: '5',
      confirmButtonText: '推进',
      cancelButtonText: '取消'
    })
    const canaryPct = Math.min(100, Math.max(0, Number(value) || 0))
    const svc = ElLoading.service({ lock: true, text: '提交中...' })
    try {
      await promoteRule(row.rule_id, {
        from_status: row.status,
        to_status: row.status === RuleStatus.DRAFT ? RuleStatus.CANARY : RuleStatus.ACTIVE,
        canary_percentage: canaryPct,
        approver_id: auth.user?.user_id || ''
      })
      ElMessage.success('已推进')
      await fetchData()
    } finally {
      svc.close()
    }
  } catch {
    /* 用户取消 */
  }
}

async function rollback(row: RuleListItem) {
  try {
    const { value } = await ElMessageBox.prompt('输入回滚原因', '紧急回滚', {
      inputType: 'textarea',
      confirmButtonText: '回滚',
      cancelButtonText: '取消'
    })
    if (!value?.trim()) {
      ElMessage.warning('请填写回滚原因')
      return
    }
    const svc = ElLoading.service({ lock: true, text: '提交中...' })
    try {
      await rollbackRule(row.rule_id, {
        reason: value,
        approver_id: auth.user?.user_id || ''
      })
      ElMessage.success('已回滚')
      await fetchData()
    } finally {
      svc.close()
    }
  } catch {
    /* 用户取消 */
  }
}

async function retire(row: RuleListItem) {
  try {
    const { value } = await ElMessageBox.prompt('输入下线原因', '下线规则', {
      inputType: 'textarea',
      confirmButtonText: '下线',
      cancelButtonText: '取消'
    })
    if (!value?.trim()) {
      ElMessage.warning('请填写下线原因')
      return
    }
    const svc = ElLoading.service({ lock: true, text: '提交中...' })
    try {
      await retireRule(row.rule_id, value)
      ElMessage.success('已下线')
      await fetchData()
    } finally {
      svc.close()
    }
  } catch {
    /* 用户取消 */
  }
}

async function remove(row: RuleListItem) {
  await ElMessageBox.confirm(`确认软删除规则「${row.name}」？`, '删除确认', {
    type: 'warning'
  })
  const svc = ElLoading.service({ lock: true, text: '删除中...' })
  try {
    await deleteRule(row.rule_id)
    ElMessage.success('已删除')
    await fetchData()
  } finally {
    svc.close()
  }
}

function statusTagType(s: RuleStatus): 'info' | 'warning' | 'success' | 'danger' {
  if (s === RuleStatus.ACTIVE) return 'success'
  if (s === RuleStatus.CANARY) return 'warning'
  if (s === RuleStatus.RETIRED) return 'info'
  return 'info'
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <ElForm :inline="true" :model="query">
        <ElFormItem label="状态">
          <ElSelect v-model="query.status" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="s in Object.values(RuleStatus)" :key="s" :label="RULE_STATUS_LABELS[s]" :value="s" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="动作">
          <ElSelect v-model="query.action" placeholder="全部" clearable style="width: 140px">
            <ElOption label="阻断 BLOCK" :value="RuleAction.BLOCK" />
            <ElOption label="复审 REVIEW" :value="RuleAction.REVIEW" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="严重级别">
          <ElSelect v-model="query.severity" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="s in Object.values(RuleSeverity)" :key="s" :label="s" :value="s" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="渠道">
          <ElSelect v-model="query.channel" placeholder="全部" clearable style="width: 140px">
            <ElOption v-for="c in Object.values(Channel)" :key="c" :label="c" :value="c" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" @click="fetchData">查询</ElButton>
          <ElButton type="success" @click="goCreate">新建规则</ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe>
        <ElTableColumn prop="name" label="规则名称" min-width="180" />
        <ElTableColumn prop="rule_id" label="规则 ID" width="200" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.status as RuleStatus)">
              {{ RULE_STATUS_LABELS[row.status as RuleStatus] }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="version" label="版本" width="80" />
        <ElTableColumn label="动作" width="100">
          <template #default="{ row }">
            <ElTag :type="row.action === RuleAction.BLOCK ? 'danger' : 'warning'">
              {{ row.action === RuleAction.BLOCK ? '阻断' : '复审' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="severity" label="严重级" width="90" />
        <ElTableColumn label="24h 命中" width="110" align="right">
          <template #default="{ row }">{{ row.hit_count_24h }}</template>
        </ElTableColumn>
        <ElTableColumn label="误报率" width="110" align="right">
          <template #default="{ row }">{{ formatPercent(row.false_positive_rate) }}</template>
        </ElTableColumn>
        <ElTableColumn label="更新时间" width="170">
          <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <ElButton text type="primary" @click="goEdit(row)">编辑</ElButton>
            <ElButton
              v-if="row.status === RuleStatus.DRAFT || row.status === RuleStatus.CANARY"
              text
              type="warning"
              @click="promote(row)"
            >
              推进
            </ElButton>
            <ElButton v-if="row.status !== RuleStatus.DRAFT" text type="danger" @click="rollback(row)">
              回滚
            </ElButton>
            <ElButton v-if="row.status === RuleStatus.ACTIVE || row.status === RuleStatus.CANARY" text type="info" @click="retire(row)">
              下线
            </ElButton>
            <ElButton v-if="row.status === RuleStatus.DRAFT" text type="danger" @click="remove(row)">
              删除
            </ElButton>
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
