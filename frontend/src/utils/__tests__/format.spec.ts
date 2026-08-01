// 格式化工具单元测试（D07：前端 vitest）
import { describe, expect, it } from 'vitest'
import {
  formatAmount,
  formatDate,
  formatPercent,
  formatRelative,
  formatRiskScore
} from '@/utils/format'

describe('formatAmount', () => {
  it('分 → 元（CNY 符号）', () => {
    expect(formatAmount(128800)).toBe('¥1,288.00')
    expect(formatAmount(1)).toBe('¥0.01')
    expect(formatAmount(0)).toBe('¥0.00')
  })

  it('null/undefined/NaN 返回 -', () => {
    expect(formatAmount(null)).toBe('-')
    expect(formatAmount(undefined)).toBe('-')
    expect(formatAmount(Number.NaN)).toBe('-')
  })
})

describe('formatRiskScore', () => {
  it('保留 4 位小数', () => {
    expect(formatRiskScore(0.123456)).toBe('0.1235')
    expect(formatRiskScore(0)).toBe('0.0000')
    expect(formatRiskScore(1)).toBe('1.0000')
  })

  it('空值返回 -', () => {
    expect(formatRiskScore(null)).toBe('-')
  })
})

describe('formatPercent', () => {
  it('比例 → 百分比', () => {
    expect(formatPercent(0.12)).toBe('12.00%')
    expect(formatPercent(0.1234, 3)).toBe('12.340%')
  })

  it('空值返回 -', () => {
    expect(formatPercent(undefined)).toBe('-')
  })
})

describe('formatDate', () => {
  it('ISO 8601 → 本地日期时间', () => {
    const out = formatDate('2026-07-27T08:00:00Z')
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
  })

  it('仅日期模式', () => {
    const out = formatDate('2026-07-27T08:00:00Z', false)
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('空值/非法输入返回原样', () => {
    expect(formatDate(null)).toBe('-')
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('formatRelative', () => {
  it('分钟级相对时间', () => {
    const past = new Date(Date.now() - 3 * 60 * 1000).toISOString()
    expect(formatRelative(past)).toBe('3 分钟前')
  })

  it('空值返回 -', () => {
    expect(formatRelative(null)).toBe('-')
  })
})
