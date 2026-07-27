<script setup lang="ts">
/**
 * Webhook 管理（D06 §12.4 + D05 §11）
 * 功能：注册 / 编辑 / 注销 / 测试投递 / 投递记录查看
 * 权限：TENANT_ADMIN（全租户）/ MERCHANT_ADMIN（自有商户，RLS 强制）
 */
import { onMounted, ref, reactive } from 'vue'
import {
  ElCard,
  ElTable,
  ElTableColumn,
  ElTag,
  ElButton,
  ElPagination,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElSwitch,
  ElSelect,
  ElOption,
  ElMessage,
  ElMessageBox,
  ElEmpty,
  ElLoading
} from 'element-plus'
import {
  listWebhooks,
  createWebhook,
  updateWebhook,
  deleteWebhook,
  testWebhook,
  listWebhookDeliveries,
  type WebhookListItem,
  type WebhookDelivery
} from '@/api/webhook'
import { WebhookStatus, WebhookDeliveryStatus } from '@/types/enum'
import { formatDate, formatRelative } from '@/utils/format'

const loading = ref(false)
const list = ref<WebhookListItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20 })

const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const form = reactive<{
  url: string
  events: string[]
  secret: string
  challenge_expected: boolean
}>({
  url: '',
  events: ['transaction.scored', 'transaction.denied'],
  secret: '',
  challenge_expected: true
})

const eventOptions = [
  'transaction.scored',
  'transaction.denied',
  'transaction.review',
  'case.created',
  'case.closed',
  'gang.detected',
  'report.ready',
  'privacy.export.ready',
  'privacy.deletion.completed'
]

const deliveriesVisible = ref(false)
const deliveries = ref<WebhookDelivery[]>([])
const deliveriesTotal = ref(0)
const deliveriesQuery = reactive<{ webhookId: string; page: number; page_size: number }>({
  webhookId: '',
  page: 1,
  page_size: 20
})

async function fetchData() {
  loading.value = true
  const svc = ElLoading.service({ lock: true, text: '加载中...' })
  try {
    const res = await listWebhooks(query)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
    svc.close()
  }
}

function openCreate() {
  editingId.value = null
  form.url = ''
  form.events = ['transaction.scored', 'transaction.denied']
  form.secret = ''
  form.challenge_expected = true
  dialogVisible.value = true
}

function openEdit(row: WebhookListItem) {
  editingId.value = row.id
  form.url = row.url
  form.events = [...row.events]
  form.secret = ''
  form.challenge_expected = false
  dialogVisible.value = true
}

async function submit() {
  if (!form.url.trim() || !form.events.length) {
    ElMessage.warning('请填写 URL 与订阅事件')
    return
  }
  if (!editingId.value && !form.secret.trim()) {
    ElMessage.warning('请填写签名 secret')
    return
  }
  const svc = ElLoading.service({ lock: true, text: '保存中...' })
  try {
    if (editingId.value) {
      await updateWebhook(editingId.value, {
        url: form.url,
        events: form.events,
        secret: form.secret || undefined,
        challenge_expected: form.challenge_expected
      })
      ElMessage.success('已更新')
    } else {
      await createWebhook({
        url: form.url,
        events: form.events,
        secret: form.secret,
        challenge_expected: form.challenge_expected
      })
      ElMessage.success('已注册')
    }
    dialogVisible.value = false
    await fetchData()
  } finally {
    svc.close()
  }
}

async function remove(row: WebhookListItem) {
  await ElMessageBox.confirm(`确认注销 Webhook「${row.url}」？`, '注销确认', { type: 'warning' })
  const svc = ElLoading.service({ lock: true, text: '注销中...' })
  try {
    await deleteWebhook(row.id)
    ElMessage.success('已注销')
    await fetchData()
  } finally {
    svc.close()
  }
}

async function test(row: WebhookListItem) {
  const { value } = await ElMessageBox.prompt('输入测试事件类型', '测试投递', {
    inputValue: row.events[0] || 'transaction.scored'
  })
  const svc = ElLoading.service({ lock: true, text: '发送中...' })
  try {
    await testWebhook(row.id, { event_type: value })
    ElMessage.success('测试投递已发送')
  } finally {
    svc.close()
  }
}

async function openDeliveries(row: WebhookListItem) {
  deliveriesQuery.webhookId = row.id
  deliveriesQuery.page = 1
  deliveriesVisible.value = true
  await fetchDeliveries()
}

async function fetchDeliveries() {
  const svc = ElLoading.service({ lock: true, text: '加载投递记录...' })
  try {
    const res = await listWebhookDeliveries(deliveriesQuery.webhookId, deliveriesQuery)
    deliveries.value = res.items
    deliveriesTotal.value = res.total
  } finally {
    svc.close()
  }
}

function statusTag(s: WebhookStatus): 'info' | 'success' | 'warning' | 'danger' {
  if (s === WebhookStatus.ACTIVE) return 'success'
  if (s === WebhookStatus.PENDING_VERIFICATION) return 'warning'
  if (s === WebhookStatus.VERIFICATION_FAILED) return 'danger'
  return 'info'
}

function deliveryTag(s: WebhookDeliveryStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (s === WebhookDeliveryStatus.SUCCESS) return 'success'
  if (s === WebhookDeliveryStatus.RETRYING) return 'warning'
  if (s === WebhookDeliveryStatus.DEAD_LETTERED) return 'danger'
  return 'info'
}

onMounted(fetchData)
</script>

<template>
  <div class="frd-page-container">
    <ElCard shadow="never" class="frd-card-margin">
      <div class="frd-flex-between">
        <span style="font-weight: 600">Webhook 列表</span>
        <ElButton type="primary" @click="openCreate">注册 Webhook</ElButton>
      </div>
    </ElCard>

    <ElCard shadow="never">
      <ElTable :data="list" v-loading="loading" stripe>
        <ElTableColumn prop="url" label="URL" min-width="280" />
        <ElTableColumn label="订阅事件" min-width="220">
          <template #default="{ row }">
            <ElTag v-for="e in row.events" :key="e" style="margin-right: 4px; margin-bottom: 4px">{{ e }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="140">
          <template #default="{ row }">
            <ElTag :type="statusTag(row.status as WebhookStatus)">{{ row.status }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="最近投递" width="170">
          <template #default="{ row }">{{ formatDate(row.last_delivery_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="最近状态" width="120">
          <template #default="{ row }">
            <ElTag v-if="row.last_delivery_status" :type="deliveryTag(row.last_delivery_status as WebhookDeliveryStatus)">
              {{ row.last_delivery_status }}
            </ElTag>
            <span v-else>-</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <ElButton text type="primary" @click="openEdit(row)">编辑</ElButton>
            <ElButton text type="warning" @click="test(row)">测试</ElButton>
            <ElButton text type="info" @click="openDeliveries(row)">投递记录</ElButton>
            <ElButton text type="danger" @click="remove(row)">注销</ElButton>
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

    <ElDialog v-model="dialogVisible" :title="editingId ? '编辑 Webhook' : '注册 Webhook'" width="560px">
      <ElForm :model="form" label-width="120px">
        <ElFormItem label="URL" required>
          <ElInput v-model="form.url" placeholder="https://example.com/webhook" />
        </ElFormItem>
        <ElFormItem label="订阅事件" required>
          <ElSelect v-model="form.events" multiple filterable allow-create style="width: 100%">
            <ElOption v-for="e in eventOptions" :key="e" :label="e" :value="e" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="签名 Secret" :required="!editingId">
          <ElInput
            v-model="form.secret"
            type="password"
            show-password
            :placeholder="editingId ? '留空表示不更新' : 'HMAC-SHA256 签名密钥'"
          />
        </ElFormItem>
        <ElFormItem label="Challenge 验证">
          <ElSwitch v-model="form.challenge_expected" />
          <span style="margin-left: 8px; color: #909399">注册时进行 challenge-response 验证</span>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="submit">{{ editingId ? '更新' : '注册' }}</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="deliveriesVisible" title="投递记录" width="900px">
      <ElEmpty v-if="!deliveries.length" description="暂无投递记录" :image-size="80" />
      <ElTable v-else :data="deliveries" stripe size="small">
        <ElTableColumn prop="delivery_id" label="投递 ID" min-width="200" />
        <ElTableColumn prop="event_type" label="事件" width="180" />
        <ElTableColumn label="状态" width="110">
          <template #default="{ row }">
            <ElTag :type="deliveryTag(row.status as WebhookDeliveryStatus)">{{ row.status }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="是否测试" width="90">
          <template #default="{ row }">{{ row.is_test ? '是' : '否' }}</template>
        </ElTableColumn>
        <ElTableColumn label="尝试次数" width="90" align="right">
          <template #default="{ row }">{{ row.attempts?.length || 0 }}</template>
        </ElTableColumn>
        <ElTableColumn label="投递时间" width="170">
          <template #default="{ row }">{{ formatDate(row.delivered_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="死信时间" width="170">
          <template #default="{ row }">{{ formatDate(row.dead_lettered_at) }}</template>
        </ElTableColumn>
      </ElTable>
      <ElPagination
        v-model:current-page="deliveriesQuery.page"
        v-model:page-size="deliveriesQuery.page_size"
        :total="deliveriesTotal"
        layout="total, prev, pager, next"
        @current-change="fetchDeliveries"
        style="margin-top: 12px; justify-content: flex-end"
      />
    </ElDialog>
  </div>
</template>
