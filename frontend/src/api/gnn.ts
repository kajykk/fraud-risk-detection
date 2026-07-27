/**
 * GNN 团伙检测 API（对齐 D05 §7，/api/v1/gnn/* 命名空间）
 */
import { get, post } from './request'

/** 图节点类型（D03 §4.4） */
export type GraphNodeType = 'Account' | 'Merchant' | 'Device' | 'IP' | 'Card'

/** 图节点 */
export interface GraphNode {
  id: string
  type: GraphNodeType
  depth?: number
  risk_score?: number
  shared_accounts?: number
  centrality?: number
}

/** 图边 */
export interface GraphEdge {
  from: string
  to: string
  type: 'USES' | 'PAYS_TO' | 'FROM_IP' | 'BINDS_TO' | 'SHARES_WITH' | 'SHARED_DEVICE'
  weight?: number
  first_seen_at?: string
}

/** k-hop 邻居查询响应（D05 §7.1） */
export interface RelatedGraph {
  seed_node: GraphNode
  k: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  total_nodes: number
  evaluated_at_ms: number
}

/** GraphSAGE 嵌入响应（D05 §7.2） */
export interface NodeEmbedding {
  node_id: string
  model_id: string
  embedding: number[]
  dimension: number
  computed_at: string
  latency_ms: number
}

/** 团伙检测任务（D05 §7.3-7.4） */
export interface CommunityDetectionTask {
  task_id: string
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'TIMEOUT'
  communities?: string[]
  progress?: number
  estimated_seconds?: number
  callback_event?: string
  created_at?: string
  completed_at?: string
}

/** 团伙详情（D05 §7.5） */
export interface CommunityDetail {
  community_id: string
  confidence: number
  size: number
  total_amount: number
  detected_at: string
  algorithm: 'LOUVAIN' | 'LABEL_PROP' | 'WALKTRAP'
  nodes: GraphNode[]
  edges: GraphEdge[]
  case_id?: string
  model_id: string
}

/** k-hop 邻居查询（D05 §7.1） */
export function getRelated(
  nodeId: string,
  params: { k?: number; edge_types?: string; time_window_hours?: number; limit?: number }
) {
  return get<RelatedGraph>(`/gnn/related/${nodeId}`, params as Record<string, unknown>)
}

/** GraphSAGE 嵌入（D05 §7.2） */
export function computeEmbedding(
  nodeId: string,
  payload: { model_id?: string; dimension?: number; context_hops?: number }
) {
  return post<NodeEmbedding>(`/gnn/embedding/${nodeId}`, payload)
}

/** 触发团伙检测异步任务（D05 §7.3） */
export function detectCommunity(payload: {
  seed_account_id: string
  depth?: number
  time_window_hours?: number
  min_confidence?: number
  edge_types?: string[]
  algorithm?: 'LOUVAIN' | 'LABEL_PROP' | 'WALKTRAP'
  callback_event?: string
}) {
  return post<CommunityDetectionTask>('/gnn/community-detection', payload)
}

/** 查询团伙检测任务状态（D05 §7.4） */
export function getCommunityTask(taskId: string) {
  return get<CommunityDetectionTask>(`/gnn/community-detection/${taskId}`)
}

/** 团伙详情（D05 §7.5） */
export function getCommunity(communityId: string) {
  return get<CommunityDetail>(`/gnn/community/${communityId}`)
}
