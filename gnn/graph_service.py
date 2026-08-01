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
from typing import Any, Dict, List, Optional

import structlog

from .community.detector import Community, CommunityDetector
from .config import settings
from .models.graphsage import GraphSAGE

logger = structlog.get_logger(__name__)


@dataclass
class Graph:
    """k 跳关联子图（D03 §4.4 实时查询输出）。"""

    center_node_id: str
    nodes: List[Dict[str, Any]]  # [{id, label, props}, ...]
    edges: List[Dict[str, Any]]  # [{src, dst, type, props}, ...]
    k_hops: int
    queried_at: float = field(default_factory=time.time)
    latency_ms: float = 0.0


# Cypher：k 跳关联节点 + 边查询（D04 §2.2 节点 + 关系类型）
K_HOP_QUERY = """
MATCH path = (n)-[*1..$k_hops]-(m)
WHERE n.id = $node_id AND n.tenant_id = $tenant_id
WITH nodes(path) AS ns, relationships(path) AS rs
UNWIND ns AS node
WITH collect(DISTINCT {id: node.id, labels: labels(node), props: properties(node)}) AS nodes,
     collect(DISTINCT rs) AS rels
RETURN nodes, rels
LIMIT 1000
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
        neo4j_driver: Optional[Any] = None,
        redis_client: Optional[Any] = None,
        graphsage: Optional[GraphSAGE] = None,
        community_detector: Optional[CommunityDetector] = None,
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
    ) -> Dict[str, Any]:
        """同步 Neo4j Cypher 查询（在 thread executor 中执行）。"""
        with self._driver.session(database=settings.neo4j.database) as sess:
            result = sess.run(
                K_HOP_QUERY,
                node_id=node_id,
                k_hops=k_hops,
                tenant_id=tenant_id,
            )
            record = result.single()
            if record is None:
                return {"nodes": [], "rels": []}
            return {
                "nodes": list(record["nodes"] or []),
                "rels": self._format_rels(record["rels"] or []),
            }

    @staticmethod
    def _format_rels(rels: Any) -> List[Dict[str, Any]]:
        """把 Neo4j relationship 对象序列化为 dict。"""
        formatted = []
        for r in rels:
            try:
                formatted.append(
                    {
                        "src": r.start_node["id"],  # type: ignore[index]
                        "dst": r.end_node["id"],  # type: ignore[index]
                        "type": r.type(),
                        "props": dict(r),
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return formatted

    async def compute_embedding(self, node_id: str, tenant_id: str = "") -> List[float]:
        """GraphSAGE 推理：返回节点 embedding。

        优先查 Redis 缓存（TTL 1h），未命中则执行 PyG 推理。
        """
        cache_key = f"gnn:embed:{tenant_id}:{node_id}"
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached

        if self._graphsage is None or self._graphsage._model is None:
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

    def _infer_embedding_sync(self, graph: Graph, node_id: str) -> List[float]:
        """同步 GraphSAGE 推理（在 thread executor 中执行）。"""
        import torch  # type: ignore

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
        return embeddings[target_idx].cpu().tolist()

    async def detect_community(
        self,
        node_id: str,
        k_hops: int = 3,
        tenant_id: str = "",
        node_amounts: Optional[Dict[str, float]] = None,
        node_fraud_labels: Optional[Dict[str, bool]] = None,
    ) -> Optional[Community]:
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
        communities = self._community.detect(
            nodes=nodes,
            edges=edges,
            node_amounts=node_amounts,
            node_fraud_labels=node_fraud_labels,
        )
        for community in communities:
            if node_id in community.members:
                return community
        return None

    async def _read_cache(self, key: str) -> Optional[List[float]]:
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

    async def _write_cache(self, key: str, embedding: List[float]) -> None:
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


__all__ = ["GNNGraphService", "Graph", "K_HOP_QUERY"]
