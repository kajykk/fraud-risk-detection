<script setup lang="ts">
/**
 * 规则编辑/新建（D06 §7.3）
 * 含 DSL 校验与试运行
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElInputNumber,
  ElButton,
  ElDatePicker,
  ElMessage,
  ElMessageBox,
  ElLoading
} from 'element-plus'
import {
  getRule,
  createRule,
  updateRule,
  createRuleVersion,
  validateRuleDsl
} from '@/api/rule'
import type { ValidateRuleDslResult } from '@/types/rule'
import { RuleStatus, RuleAction, RuleSeverity, Channel } from '@/types/enum'
import { RULE_STATUS_LABELS, formatDate } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const ruleId = computed(() => (route.params.ruleId ? String(route.params.ruleId) : ''))
const isCreate = computed(() => !ruleId.value)
const isEditExisting = computed(() => !isCreate.value)

const form = reactive({
  name: '',
  description: '',
  dsl: '# CEL DSL 示例：\n# amount > 10000 && ip_geo.country != "CN"\n',
  severity: RuleSeverity.WARN,
  action: RuleAction.REVIEW,
  valid_from: '' as string,
  valid_to: '' as string | null,
  channels: [] as Channel[]
})

const currentStatus = ref<RuleStatus | null>(null)
const currentVersion = ref<number | null>(null)
const validateResult = ref<ValidateRuleDslResult | null>(null)
const submitting = ref(false)

async function loadDetail() {
  if (!ruleId.value) return
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const d = await getRule(ruleId.value)
    form.name = d.name
    form.description = d.description || ''
    form.dsl = d.dsl
    form.severity = d.severity
    form.action = d.action
    form.valid_from = d.valid_from || ''
    form.valid_to = d.valid_to ?? ''
    form.channels = d.scope?.channels || []
    currentStatus.value = d.status
    currentVersion.value = d.version
  } finally {
    svc.close()
  }
}

async function onValidate() {
  const svc = ElLoading.service({ lock: true, text: '校验中...' })
  try {
    validateResult.value = await validateRuleDsl(ruleId.value || 'preview', { dsl: form.dsl })
    if (validateResult.value.valid) {
      ElMessage.success('DSL 校验通过')
    } else {
      ElMessage.error(`DSL 校验失败：${validateResult.value.syntax_errors.join('; ')}`)
    }
  } finally {
    svc.close()
  }
}

async function onSubmit() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写规则名称')
    return
  }
  if (!form.dsl.trim()) {
    ElMessage.warning('请填写 DSL')
    return
  }
  const payload = {
    name: form.name,
    description: form.description || undefined,
    dsl: form.dsl,
    severity: form.severity,
    action: form.action,
    valid_from: form.valid_from || undefined,
    valid_to: form.valid_to ?? undefined,
    scope: form.channels.length ? { channels: form.channels } : undefined
  }
  submitting.value = true
  const svc = ElLoading.service({ lock: true, text: '保存中...' })
  try {
    if (isCreate.value) {
      await createRule(payload)
      ElMessage.success('规则已创建（DRAFT）')
      router.push('/rules')
    } else {
      // 已存在规则：若状态为 DRAFT 则直接更新；否则基于当前版本创建新草稿版本
      if (currentStatus.value === RuleStatus.DRAFT) {
        await updateRule(ruleId.value!, payload)
      } else {
        await ElMessageBox.confirm(
          `当前规则状态为 ${RULE_STATUS_LABELS[currentStatus.value!]}（v${currentVersion.value}），将创建新版本草稿。`,
          '新建版本确认',
          { type: 'warning' }
        )
        await createRuleVersion(ruleId.value!, {
          dsl: form.dsl,
          severity: form.severity,
          action: form.action,
          change_summary: `更新规则「${form.name}」`
        })
      }
      ElMessage.success('已保存')
      await loadDetail()
    }
  } finally {
    submitting.value = false
    svc.close()
  }
}

onMounted(loadDetail)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <template #header>
        <div class="frd-flex-between">
          <span>{{ isCreate ? '新建规则' : `编辑规则 ${ruleId}` }}</span>
          <div>
            <ElTag v-if="currentStatus" style="margin-right: 8px">
              {{ RULE_STATUS_LABELS[currentStatus] }} · v{{ currentVersion }}
            </ElTag>
            <ElButton @click="router.back()">返回</ElButton>
          </div>
        </div>
      </template>

      <ElForm :model="form" label-width="120px">
        <ElFormItem label="规则名称" required>
          <ElInput v-model="form.name" placeholder="如：大额异地交易阻断规则" maxlength="120" show-word-limit />
        </ElFormItem>
        <ElFormItem label="描述">
          <ElInput v-model="form.description" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </ElFormItem>
        <ElFormItem label="DSL 表达式" required>
          <ElInput
            v-model="form.dsl"
            type="textarea"
            :rows="10"
            placeholder="CEL DSL 表达式"
            style="font-family: 'Courier New', monospace"
          />
        </ElFormItem>
        <ElFormItem label="严重级别">
          <ElSelect v-model="form.severity" style="width: 200px">
            <ElOption v-for="s in Object.values(RuleSeverity)" :key="s" :label="s" :value="s" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="动作">
          <ElSelect v-model="form.action" style="width: 200px">
            <ElOption label="阻断 BLOCK" :value="RuleAction.BLOCK" />
            <ElOption label="复审 REVIEW" :value="RuleAction.REVIEW" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="生效时间">
          <ElDatePicker
            v-model="form.valid_from"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="生效起"
            style="width: 220px"
          />
          <span style="margin: 0 8px">至</span>
          <ElDatePicker
            v-model="form.valid_to"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="生效止（可空）"
            style="width: 220px"
          />
        </ElFormItem>
        <ElFormItem label="适用渠道">
          <ElSelect v-model="form.channels" multiple placeholder="全部渠道" style="width: 100%">
            <ElOption v-for="c in Object.values(Channel)" :key="c" :label="c" :value="c" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <ElButton @click="onValidate">校验 DSL</ElButton>
          <ElButton type="primary" :loading="submitting" @click="onSubmit">
            {{ isCreate ? '创建' : '保存' }}
          </ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard v-if="validateResult" shadow="never">
      <template #header>DSL 校验结果</template>
      <div>校验状态：{{ validateResult.valid ? '通过' : '失败' }}</div>
      <div v-if="validateResult.syntax_errors?.length" style="color: var(--frd-danger); margin-top: 8px">
        {{ validateResult.syntax_errors.join('; ') }}
      </div>
      <div v-if="validateResult.sample_hits?.length" style="margin-top: 12px">
        <div style="font-weight: 600; margin-bottom: 4px">样本命中</div>
        <div v-for="h in validateResult.sample_hits" :key="h.external_tx_id" style="padding: 2px 0">
          {{ h.external_tx_id }} —— {{ h.matched ? '命中' : '未命中' }}（{{ h.evaluated_at_ms }}ms）
        </div>
      </div>
    </ElCard>
  </div>
</template>
