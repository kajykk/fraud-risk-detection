/**
 * 格式化工具（金额 / 日期 / 枚举标签 + 着色 class）
 * 对齐 D05 §2.5（ISO 8601 UTC）与 D06 §5.2（风险着色）
 */
import type {
  Decision,
  RiskBand,
  CaseStatus,
  CaseLevel,
  RuleStatus,
  ModelStatus,
  ConsentStatus,
  AppealStatus,
  TenantPlan,
  TenantType,
  Channel,
  TxType
} from '@/types/enum'

/**
 * 金额格式化（分 → 元）
 * baseline §4.1 amount 字段单位为分（BIGINT）
 */
export function formatAmount(cents: number | undefined | null, currency = 'CNY'): string {
  if (cents === undefined || cents === null || Number.isNaN(cents)) return '-'
  const yuan = cents / 100
  const symbol = currency === 'CNY' ? '¥' : ''
  return `${symbol}${yuan.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * 风险评分格式化（DECIMAL(5,4)，0.0000-1.0000）
 */
export function formatRiskScore(score: number | undefined | null): string {
  if (score === undefined || score === null || Number.isNaN(score)) return '-'
  return score.toFixed(4)
}

/**
 * 百分比格式化（0.12 → 12.00%）
 */
export function formatPercent(ratio: number | undefined | null, digits = 2): string {
  if (ratio === undefined || ratio === null || Number.isNaN(ratio)) return '-'
  return `${(ratio * 100).toFixed(digits)}%`
}

/**
 * 日期格式化（ISO 8601 UTC → 本地展示）
 */
export function formatDate(iso: string | undefined | null, withTime = true): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  if (!withTime) return date
  return `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 相对时间（如"3 分钟前"） */
export function formatRelative(iso: string | undefined | null): string {
  if (!iso) return '-'
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return iso
  const diff = Date.now() - d
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return `${sec} 秒前`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.floor(hour / 24)
  return `${day} 天前`
}

// ===== 枚举标签 =====

export const DECISION_LABELS: Record<Decision, string> = {
  ALLOW: '放行',
  REVIEW: '人工审核',
  DENY: '拒绝',
  CHALLENGE: '二次验证'
}

export const DECISION_TAG_TYPE: Record<Decision, 'success' | 'warning' | 'danger' | 'info'> = {
  ALLOW: 'success',
  REVIEW: 'warning',
  DENY: 'danger',
  CHALLENGE: 'info'
}

export const RISK_BAND_LABELS: Record<RiskBand, string> = {
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重'
}

export const RISK_BAND_TAG_TYPE: Record<RiskBand, 'success' | 'warning' | 'danger' | 'info'> = {
  LOW: 'success',
  MEDIUM: 'warning',
  HIGH: 'danger',
  CRITICAL: 'danger'
}

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  OPEN: '待处理',
  IN_REVIEW: '处理中',
  CONFIRMED: '已确认',
  CLOSED: '已结案',
  FALSE_ALARM: '误报'
}

export const CASE_LEVEL_LABELS: Record<CaseLevel, string> = {
  P0: 'P0 紧急',
  P1: 'P1 高',
  P2: 'P2 中',
  P3: 'P3 低'
}

export const RULE_STATUS_LABELS: Record<RuleStatus, string> = {
  DRAFT: '草稿',
  CANARY: '灰度',
  ACTIVE: '已生效',
  RETIRED: '已下线'
}

export const MODEL_STATUS_LABELS: Record<ModelStatus, string> = {
  REGISTERED: '已注册',
  CANARY: '金丝雀',
  ACTIVE: '生产中',
  RETIRED: '已退役'
}

export const CONSENT_STATUS_LABELS: Record<ConsentStatus, string> = {
  GRANTED: '已授予',
  WITHDRAWN: '已撤回',
  EXPIRED: '已过期'
}

export const APPEAL_STATUS_LABELS: Record<AppealStatus, string> = {
  PENDING: '待处理',
  APPROVED: '已通过',
  REJECTED: '已拒绝',
  WITHDRAWN: '已撤回'
}

export const TENANT_PLAN_LABELS: Record<TenantPlan, string> = {
  STANDARD: '标准版',
  PRO: '专业版',
  ENTERPRISE: '企业版'
}

export const TENANT_TYPE_LABELS: Record<TenantType, string> = {
  BANK: '银行',
  PAYMENT: '支付机构',
  MERCHANT: '商户'
}

export const CHANNEL_LABELS: Record<Channel, string> = {
  WEB: '网页',
  APP: 'APP',
  POS: 'POS',
  API: 'API',
  QR: '扫码'
}

export const TX_TYPE_LABELS: Record<TxType, string> = {
  PURCHASE: '消费',
  WITHDRAW: '取现',
  REFUND: '退款',
  TRANSFER: '转账',
  TOPUP: '充值',
  PAYMENT: '付款'
}
