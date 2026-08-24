"""从 Neo4j 构建图数据（D03 §4.4 / §5.2）。

图数据建模（D03 §4.4）：
节点类型：Account / Merchant / Device / IP / Card
关系类型：USES / PAYS_TO / FROM_IP / BINDS_TO / SHARES_WITH

构建流程：
    1. 从 Neo4j 查询节点 + 边
    2. 构造 PyG Data 对象（x, edge_index, node_ids）
    3. 用于 GraphSAGE 训练 / 推理
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class GraphSnapshot:
    """PyG 图快照（节点 + 边）。"""

    node_ids: list[str]  # 节点原始 ID
    node_features: Any  # tensor (N, F)
    edge_index: Any  # tensor (2, E)
    edge_weight: Any  # tensor (E,)
    labels: Any | None = None  # 节点标签（欺诈/正常，用于训练）


# Cypher 查询模板（D03 §4.4 节点 + 关系）
NODE_QUERY = """
MATCH (n)
WHERE n.tenant_id = $tenant_id
  AND (n:Account OR n:Merchant OR n:Device OR n:IP OR n:Card)
RETURN ID(n) AS internal_id,
       labels(n)[0] AS label,
       n.id AS node_id,
       properties(n) AS props
"""

EDGE_QUERY = """
MATCH (a)-[r]->(b)
WHERE a.tenant_id = $tenant_id
  AND b.tenant_id = $tenant_id
RETURN ID(a) AS src, ID(b) AS dst,
       type(r) AS rel_type,
       properties(r) AS props
"""


class GraphBuilder:
    """从 Neo4j 构建图数据。"""

    def __init__(self, neo4j_driver: Any) -> None:
        self._driver = neo4j_driver

    def build(self, tenant_id: str) -> GraphSnapshot:
        """从 Neo4j 拉取节点 + 边 → 构造 PyG Data。"""
        nodes = self._fetch_nodes(tenant_id)
        edges = self._fetch_edges(tenant_id)
        return self._to_snapshot(nodes, edges)

    def _fetch_nodes(self, tenant_id: str) -> list[dict]:
        with self._driver.session(database=self._database()) as sess:
            result = sess.run(NODE_QUERY, tenant_id=tenant_id)
            return [dict(record) for record in result]

    def _fetch_edges(self, tenant_id: str) -> list[dict]:
        with self._driver.session(database=self._database()) as sess:
            result = sess.run(EDGE_QUERY, tenant_id=tenant_id)
            return [dict(record) for record in result]

    def _database(self) -> str:
        from ..config import settings

        return settings.neo4j.database

    def _to_snapshot(self, nodes: list[dict], edges: list[dict]) -> GraphSnapshot:
        import numpy as np  # type: ignore
        import torch  # type: ignore

        if not nodes:
            empty = torch.zeros((0, 64), dtype=torch.float32)
            return GraphSnapshot(
                node_ids=[],
                node_features=empty,
                edge_index=torch.zeros((2, 0), dtype=torch.long),
                edge_weight=torch.zeros((0,), dtype=torch.float32),
            )

        # internal_id → row index
        id_to_idx = {n["internal_id"]: i for i, n in enumerate(nodes)}
        node_ids = [str(n.get("node_id") or n["internal_id"]) for n in nodes]

        # 节点特征：从 properties 抽取数值字段，缺失补 0
        feature_dim = 64
        feat_rows = []
        for n in nodes:
            props = n.get("props") or {}
            row = []
            for k in sorted(props.keys()):
                v = props[k]
                if isinstance(v, (int, float)):
                    row.append(float(v))
            # pad/truncate 到 feature_dim
            if len(row) >= feature_dim:
                row = row[:feature_dim]
            else:
                row = row + [0.0] * (feature_dim - len(row))
            feat_rows.append(row)
        x = torch.tensor(np.asarray(feat_rows, dtype=np.float32))

        # 边索引
        src_list: list[int] = []
        dst_list: list[int] = []
        weights: list[float] = []
        for e in edges:
            src = id_to_idx.get(e["src"])
            dst = id_to_idx.get(e["dst"])
            if src is None or dst is None:
                continue
            src_list.append(src)
            dst_list.append(dst)
            props = e.get("props") or {}
            weight = float(props.get("count", 1.0))
            weights.append(weight)
        edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
        edge_weight = torch.tensor(weights, dtype=torch.float32)

        logger.info(
            "graph.built",
            n_nodes=len(node_ids),
            n_edges=len(src_list),
        )
        return GraphSnapshot(
            node_ids=node_ids,
            node_features=x,
            edge_index=edge_index,
            edge_weight=edge_weight,
        )


__all__ = ["EDGE_QUERY", "NODE_QUERY", "GraphBuilder", "GraphSnapshot"]
