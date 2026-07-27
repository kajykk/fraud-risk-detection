/**
 * 通用 API 响应与分页类型
 * 对齐 D05 §2.3 响应格式与 §2.4 分页约定
 */

/** 业务状态码（D05 §12.1，OK 表示成功） */
export type BizCode = string

/** 统一响应体（D05 §2.3） */
export interface ApiResponse<T = unknown> {
  code: BizCode
  message: string
  data: T
  request_id: string
  trace_id?: string
  timestamp: string
}

/** 分页数据结构（D05 §2.4） */
export interface PageResult<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

/** 分页查询参数 */
export interface PageQuery {
  page?: number
  page_size?: number
  sort?: string
}

/** 字段级校验错误（D05 §12.2） */
export interface FieldViolation {
  field: string
  rule: string
  value: unknown
}

/** 限流响应头（D05 §2.7） */
export interface RateLimitHeaders {
  'X-RateLimit-Limit': number
  'X-RateLimit-Remaining': number
  'X-RateLimit-Reset': number
  'Retry-After'?: number
}
