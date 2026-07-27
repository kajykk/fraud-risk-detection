/**
 * FRD 统一枚举字典
 *
 * 严格对齐 FRD-BASELINE-V1.1 §3（统一枚举字典）与 D04 V1.1（数据库设计）。
 * 所有枚举值采用大写下划线命名（baseline §3.6 注：tenant_pci_scope 为小写例外）。
 *
 * 不得在本文件外自行定义枚举字面量，确保跨文档单一事实源。
 */

// baseline §3.1 决策枚举（评分最终决策，4 值）
export enum Decision {
  ALLOW = 'ALLOW',
  REVIEW = 'REVIEW',
  DENY = 'DENY',
  CHALLENGE = 'CHALLENGE'
}

// baseline §3.2 案件状态
export enum CaseStatus {
  OPEN = 'OPEN',
  IN_REVIEW = 'IN_REVIEW',
  CONFIRMED = 'CONFIRMED',
  CLOSED = 'CLOSED',
  FALSE_ALARM = 'FALSE_ALARM'
}

// baseline §3.3 模型状态
export enum ModelStatus {
  REGISTERED = 'REGISTERED',
  CANARY = 'CANARY',
  ACTIVE = 'ACTIVE',
  RETIRED = 'RETIRED'
}

// baseline §3.4 规则状态 + 规则动作
export enum RuleStatus {
  DRAFT = 'DRAFT',
  CANARY = 'CANARY',
  ACTIVE = 'ACTIVE',
  RETIRED = 'RETIRED'
}

// baseline §3.4 单条规则触发动作（2 值，区别于 decision 4 值）
export enum RuleAction {
  BLOCK = 'BLOCK',
  REVIEW = 'REVIEW'
}

// 规则严重级别（D05 §5.1）
export enum RuleSeverity {
  INFO = 'INFO',
  WARN = 'WARN',
  BLOCK = 'BLOCK'
}

// baseline §3.5 风险等级
export enum RiskBand {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  CRITICAL = 'CRITICAL'
}

// baseline §3.6 租户类型 + 套餐 + PCI 范围
export enum TenantType {
  BANK = 'BANK',
  PAYMENT = 'PAYMENT',
  MERCHANT = 'MERCHANT'
}

export enum TenantPlan {
  STANDARD = 'STANDARD',
  PRO = 'PRO',
  ENTERPRISE = 'ENTERPRISE'
}

// tenant_pci_scope 小写例外（baseline §3.6）
export enum TenantPciScope {
  CDE = 'cde',
  NON_CDE = 'non_cde'
}

// baseline §3.7 案件等级
export enum CaseLevel {
  P0 = 'P0',
  P1 = 'P1',
  P2 = 'P2',
  P3 = 'P3'
}

// baseline §3.8 交易类型与渠道
export enum TxType {
  PURCHASE = 'PURCHASE',
  WITHDRAW = 'WITHDRAW',
  REFUND = 'REFUND',
  TRANSFER = 'TRANSFER',
  TOPUP = 'TOPUP',
  PAYMENT = 'PAYMENT'
}

export enum Channel {
  WEB = 'WEB',
  APP = 'APP',
  POS = 'POS',
  API = 'API',
  QR = 'QR'
}

// baseline §3.9 反洗钱上报
export enum AmlReportType {
  LARGE = 'LARGE',
  SUSPICIOUS = 'SUSPICIOUS'
}

export enum AmlReportStatus {
  PENDING = 'PENDING',
  SUBMITTED = 'SUBMITTED',
  ACCEPTED = 'ACCEPTED',
  REJECTED = 'REJECTED'
}

// baseline §3.10 申诉状态
export enum AppealStatus {
  PENDING = 'PENDING',
  APPROVED = 'APPROVED',
  REJECTED = 'REJECTED',
  WITHDRAWN = 'WITHDRAWN'
}

// baseline §3.11 同意状态 + 同意用途
export enum ConsentStatus {
  GRANTED = 'GRANTED',
  WITHDRAWN = 'WITHDRAWN',
  EXPIRED = 'EXPIRED'
}

export enum ConsentPurpose {
  TRANSACTION_SCORING = 'TRANSACTION_SCORING',
  FRAUD_DETECTION = 'FRAUD_DETECTION',
  AML_REPORT = 'AML_REPORT',
  MARKETING = 'MARKETING',
  RESEARCH = 'RESEARCH'
}

// baseline §3.12 漂移告警
export enum DriftSeverity {
  LOW = 'LOW',
  MEDIUM = 'MEDIUM',
  HIGH = 'HIGH',
  CRITICAL = 'CRITICAL'
}

export enum DriftMetric {
  PSI = 'PSI',
  KL = 'KL',
  KS = 'KS',
  WASSERSTEIN = 'WASSERSTEIN'
}

// 用户角色（7 类，对齐 D06 §2.1）
export enum UserRole {
  TENANT_ADMIN = 'TENANT_ADMIN',
  MERCHANT_ADMIN = 'MERCHANT_ADMIN',
  RISK_ANALYST = 'RISK_ANALYST',
  RISK_MANAGER = 'RISK_MANAGER',
  AUDITOR = 'AUDITOR',
  COMPLIANCE_OFFICER = 'COMPLIANCE_OFFICER',
  DEVOPS_OPS = 'DEVOPS_OPS'
}

// 任务通用状态（异步评分 / SHAP / GNN 团伙检测 / 报表导出）
export enum TaskStatus {
  PENDING = 'PENDING',
  RUNNING = 'RUNNING',
  SUCCEEDED = 'SUCCEEDED',
  FAILED = 'FAILED',
  TIMEOUT = 'TIMEOUT'
}

// SHAP 计算状态（D05 §4.8）
export enum ShapStatus {
  RUNNING = 'RUNNING',
  READY = 'READY',
  FAILED = 'FAILED',
  EXPIRED = 'EXPIRED'
}

// Webhook 投递状态（D05 §11.7）
export enum WebhookDeliveryStatus {
  SUCCESS = 'SUCCESS',
  FAILED = 'FAILED',
  RETRYING = 'RETRYING',
  DEAD_LETTERED = 'DEAD_LETTERED'
}

// Webhook 状态（D05 §11.1）
export enum WebhookStatus {
  PENDING_VERIFICATION = 'PENDING_VERIFICATION',
  ACTIVE = 'ACTIVE',
  VERIFICATION_FAILED = 'VERIFICATION_FAILED',
  DISABLED = 'DISABLED'
}

// 模型类型（D05 §6.2）
export enum ModelType {
  XGB = 'XGB',
  BERT = 'BERT',
  MULTIMODAL = 'MULTIMODAL',
  GNN = 'GNN'
}

// 反馈标签（D05 §4.5）
export enum FeedbackLabel {
  FRAUD = 'FRAUD',
  NOT_FRAUD = 'NOT_FRAUD',
  SUSPECTED = 'SUSPECTED'
}

// PIPL 数据导出/删除请求状态
export enum PiplExportStatus {
  PROCESSING = 'PROCESSING',
  READY = 'READY',
  FAILED = 'FAILED',
  EXPIRED = 'EXPIRED'
}

export enum PiplDeletionStatus {
  PENDING_REVIEW = 'PENDING_REVIEW',
  APPROVED = 'APPROVED',
  IN_PROGRESS = 'IN_PROGRESS',
  COMPLETED = 'COMPLETED',
  REJECTED = 'REJECTED',
  PARTIALLY_COMPLETED = 'PARTIALLY_COMPLETED'
}

// GNN 算法（D05 §7.3）
export enum GnnAlgorithm {
  LOUVAIN = 'LOUVAIN',
  LABEL_PROP = 'LABEL_PROP',
  WALKTRAP = 'WALKTRAP'
}
