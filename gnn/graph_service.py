"""GNN 图查询服务（D03 §4.4 / §2.4 GNNGraphService）。

类签名（D03 §2.4 类图）：
    GNNGraphService:
        +query_related(node_id, k_hops) → Graph
        +compute_embedding(node_id) → Vector  # GraphSAGE 推理
        +detect_community(node_id) → Community

实现要点：
- Cypher 查询 Neo4j（D04 §2.2 图模型）+ PyG 推理
- 节点 embedding 缓存 Redis（TTL 1h）
- 查询 P99 < 2s（D03 §7.2）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .community.detector import Community, CommunityDetector
from .config import settings
from .models.graphsage import GraphSAGE

logger = structlog.get_logger(__name__)


@dataclass
class Graph:
    """k 跳关联子图（D03 §4.4 实时查询输出）。"""

    center_node_id: str
    nodes: list[dict[str, Any]]  # [{id, label, props}, ...]
    edges: list[dict[str, Any]]  # [{src, dst, type, props}, ...]
    k_hops: int
    queried_at: float = field(default_factory=time.time)
    latency_ms: float = 0.0


# Cypher：k 跳关联节点 + 边查询（D04 §2.2 节点 + 关系类型）
# 注意 1：不能直接 collect(DISTINCT rs)（rs 是每条路径的关系列表，会按列表去重，
# 导致边集合为空）；先 UNWIND 节点与关系，再分别按对象去重。
# 注意 2：Neo4j 变长路径边界（*1..K）不接受参数占位符，跳数只能以整数
# 白名单校验后插值（k_hop_query 内强制 1..5 校验，杜绝注入）。
# 注意 3：WITH path LIMIT 先截断路径数再 UNWIND，防止超级节点笛卡尔积爆炸。
_K_HOPS_MIN = 1
_K_HOPS_MAX = 5
_PATH_BUDGET = 500


def k_hop_query(k_hops: int) -> str:
    """构建 k 跳关联查询；k_hops 必须为 1..5 的整数（防注入白名单）。"""
    if not isinstance(k_hops, int) or isinstance(k_hops, bool) or not (
        _K_HOPS_MIN <= k_hops <= _K_HOPS_MAX
    ):
        raise ValueError(f"k_hops must be an integer in [{_K_HOPS_MIN}, {_K_HOPS_MAX}], got {k_hops!r}")
    return f"""
MATCH path = (n)-[*1..{k_hops}]-(m)
WHERE n.id = $node_id AND n.tenant_id = $tenant_id
WITH path LIMIT {_PATH_BUDGET}
UNWIND nodes(path) AS node
UNWIND relationships(path) AS rel
WITH collect(DISTINCT {{id: node.id, labels: labels(node), props: properties(node)}}) AS nodes,
     collect(DISTINCT rel) AS rels
RETURN nodes, rels
"""


class GNNGraphService:
    """图查询服务（Neo4j + GraphSAGE + Louvain 团伙检测）。

    严格遵循 D03 §2.4 类图与 §4.4 设计：
        query_related(node_id, k_hops) → Graph
        compute_embedding(node_id) → Vector
        detect_community(node_id) → Community
    """

    def __init__(
        self,
        neo4j_driver: Any | None = None,
        redis_client: Any | None = None,
        graphsage: GraphSAGE | None = None,
        community_detector: CommunityDetector | None = None,
    ) -> None:
        self._driver = neo4j_driver
        self._redis = redis_client
        self._graphsage = graphsage
        self._community = community_detector or CommunityDetector(
            algorithm=settings.community.algorithm,
            fraud_rate_threshold=settings.community.fraud_rate_threshold,
            min_community_size=settings.community.min_community_size,
            resolution=settings.community.resolution,
        )

    def attach_neo4j(self, driver: Any) -> None:
        self._driver = driver

    def attach_redis(self, redis_client: Any) -> None:
        self._redis = redis_client

    def attach_graphsage(self, model: GraphSAGE) -> None:
        self._graphsage = model

    async def query_related(
        self, node_id: str, k_hops: int = 2, tenant_id: str = ""
    ) -> Graph:
        """k 跳关联节点查询（Cypher，P99 < 2s）。

        Args:
            node_id: 中心节点 ID（Account / Merchant / Device / IP / Card）
            k_hops: 跳数（默认 2）
            tenant_id: 租户 ID（Neo4j 节点含 tenant_id 属性，D03 §4.7）
        """
        start = time.perf_counter()
        if self._driver is None:
            logger.warning("graph_service.driver_not_ready")
            return Graph(
                center_node_id=node_id,
                nodes=[],
                edges=[],
                k_hops=k_hops,
                latency_ms=0.0,
            )
        try:
            rows = await asyncio.get_running_loop().run_in_executor(
                None, self._query_k_hop_sync, node_id, k_hops, tenant_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("graph_service.query_failed", error=str(exc), node_id=node_id)
            rows = {"nodes": [], "rels": []}

        latency_ms = (time.perf_counter() - start) * 1000.0
        return Graph(
            center_node_id=node_id,
            nodes=rows.get("nodes", []),
            edges=rows.get("rels", []),
            k_hops=k_hops,
            latency_ms=latency_ms,
        )

    def _query_k_hop_sync(
        self, node_id: str, k_hops: int, tenant_id: str
    ) -> dict[str, Any]:
        """同步 Neo4j Cypher 查询（在 thread executor 中执行）。

        查询超时受 settings.query_timeout_seconds 约束（D03 §7.2 P99 < 2s）：
        超级节点/深跳数下 Cypher 可能长时间占用连接，超时后由 driver 终止。
        """
        if self._driver is None:
            raise RuntimeError("neo4j driver not attached")
        records = self._driver.execute_query(
            k_hop_query(k_hops),
            node_id=node_id,
            tenant_id=tenant_id,
            database_=settings.neo4j.database,
            timeout=settings.query_timeout_seconds,
        )
        if not records:
            return {"nodes": [], "rels": []}
        record = records[0]
        return {
            "nodes": list(record["nodes"] or []),
            "rels": self._format_rels(record["rels"] or []),
        }

    @staticmethod
    def _format_rels(rels: Any) -> list[dict[str, Any]]:
        """把 Neo4j relationship 对象序列化为 dict。"""
        formatted = []
        for r in rels:
            try:
                formatted.append(
                    {
                        "src": r.start_node["id"],
                        "dst": r.end_node["id"],
                        "type": r.type(),
                        "props": dict(r),
                    }
                )
            except Exception:
                logger.warning("relationship_serialize_failed", exc_info=True)
                continue
        return formatted

    async def compute_embedding(self, node_id: str, tenant_id: str = "") -> list[float]:
        """GraphSAGE 推理：返回节点 embedding。

        优先查 Redis 缓存（TTL 1h），未命中则执行 PyG 推理。
        """
        cache_key = f"gnn:embed:{tenant_id}:{node_id}"
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached

        if self._graphsage is None or not self._graphsage.is_loaded:
            logger.warning("graph_service.graphsage_not_loaded")
            return []

        # 拉取 k=1 跳子图 → 构造 PyG 输入 → 推理
        sub_graph = await self.query_related(node_id, k_hops=1, tenant_id=tenant_id)
        if not sub_graph.nodes:
            return []

        try:
            embedding = await asyncio.get_running_loop().run_in_executor(
                None, self._infer_embedding_sync, sub_graph, node_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("graph_service.embedding_failed", error=str(exc))
            return []

        await self._write_cache(cache_key, embedding)
        return embedding

    def _infer_embedding_sync(self, graph: Graph, node_id: str) -> list[float]:
        """同步 GraphSAGE 推理（在 thread executor 中执行）。"""
        import torch

        nodes = graph.nodes
        if not nodes:
            return []
        node_idx = {str(n.get("id")): i for i, n in enumerate(nodes)}
        target_idx = node_idx.get(node_id)
        if target_idx is None:
            return []

        # 构造特征矩阵（占位：从 props 抽取数值字段）
        feature_dim = self._graphsage.in_channels  # type: ignore[union-attr]
        feat_rows = []
        for n in nodes:
            props = n.get("props") or {}
            row = [float(v) for v in props.values() if isinstance(v, (int, float))]
            if len(row) >= feature_dim:
                row = row[:feature_dim]
            else:
                row = row + [0.0] * (feature_dim - len(row))
            feat_rows.append(row)
        x = torch.tensor(feat_rows, dtype=torch.float32)

        # 构造 edge_index
        src_list: list[int] = []
        dst_list: list[int] = []
        for e in graph.edges:
            src = node_idx.get(str(e.get("src")))
            dst = node_idx.get(str(e.get("dst")))
            if src is not None and dst is not None:
                src_list.append(src)
                dst_list.append(dst)
        edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)

        embeddings = self._graphsage.forward(x, edge_index)  # type: ignore[union-attr]
        target_emb = embeddings[target_idx].cpu().tolist()
        return [float(v) for v in target_emb]

    async def detect_community(
        self,
        node_id: str,
        k_hops: int = 3,
        tenant_id: str = "",
        node_amounts: dict[str, float] | None = None,
        node_fraud_labels: dict[str, bool] | None = None,
    ) -> Community | None:
        """团伙检测：返回 node_id 所属社区。"""
        sub_graph = await self.query_related(node_id, k_hops=k_hops, tenant_id=tenant_id)
        if not sub_graph.nodes:
            return None

        nodes = [str(n.get("id")) for n in sub_graph.nodes if n.get("id") is not None]
        edges = [
            (str(e.get("src")), str(e.get("dst")))
            for e in sub_graph.edges
            if e.get("src") and e.get("dst")
        ]
        # Louvain 为 CPU 密集同步计算，放入线程池避免阻塞事件循环
        communities = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: self._community.detect(
                nodes=nodes,
                edges=edges,
                node_amounts=node_amounts,
                node_fraud_labels=node_fraud_labels,
            ),
        )
        for community in communities:
            if node_id in community.members:
                return community
        return None

    async def _read_cache(self, key: str) -> list[float] | None:
        if self._redis is None:
            return None
        try:
            import json

            raw = await self._redis.get(key)
            if not raw:
                return None
            return [float(x) for x in json.loads(raw)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_service.cache.read_failed", error=str(exc))
            return None

    async def _write_cache(self, key: str, embedding: list[float]) -> None:
        if self._redis is None or not embedding:
            return
        try:
            import json

            await self._redis.set(
                key,
                json.dumps(embedding),
                ex=settings.redis.embedding_cache_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_service.cache.write_failed", error=str(exc))


__all__ = ["GNNGraphService", "Graph", "k_hop_query"]
