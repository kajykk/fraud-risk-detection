"""团伙检测（Louvain / Label Propagation，D03 §4.4）。

输入：图节点 + 边（NetworkX 或 PyG Data）
输出：社区列表 + 每个社区统计信息（成员数 / 总金额 / 风险分）

团伙识别策略（D03 §4.4）：
- 社区欺诈率 > 30% → 标记为欺诈团伙
- 新交易落入团伙社区 → 加权风险分
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CommunityStats:
    """社区统计信息。"""

    community_id: int
    member_count: int
    total_amount: float  # 社区成员交易总金额
    fraud_count: int  # 已标记欺诈成员数
    fraud_rate: float  # 欺诈率（fraud_count / member_count）
    risk_score: float  # 社区风险分（0-1）
    is_fraud_gang: bool  # 是否标记为欺诈团伙（fraud_rate > 0.3）


@dataclass
class Community:
    """社区（团伙）检测结果。"""

    community_id: int
    members: list[str]  # 节点 ID 列表
    stats: CommunityStats


class CommunityDetector:
    """团伙检测器（Louvain 主，Label Propagation 备）。"""

    def __init__(
        self,
        algorithm: str = "louvain",
        fraud_rate_threshold: float = 0.3,
        min_community_size: int = 3,
        resolution: float = 1.0,
    ) -> None:
        self.algorithm = algorithm
        self.fraud_rate_threshold = fraud_rate_threshold
        self.min_community_size = min_community_size
        self.resolution = resolution

    def detect(
        self,
        nodes: list[str],
        edges: list[tuple[str, str]],
        node_amounts: dict[str, float] | None = None,
        node_fraud_labels: dict[str, bool] | None = None,
    ) -> list[Community]:
        """执行团伙检测。

        Args:
            nodes: 节点 ID 列表
            edges: 边列表 [(src, dst), ...]
            node_amounts: 节点 → 累计交易金额（可选）
            node_fraud_labels: 节点 → 是否欺诈（可选）

        Returns:
            communities: List[Community]
        """
        import networkx as nx  # type: ignore

        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edges)

        if self.algorithm == "louvain":
            partition = self._louvain(graph)
        elif self.algorithm == "label_propagation":
            partition = self._label_propagation(graph)
        else:
            logger.warning("community.unknown_algorithm", algorithm=self.algorithm)
            partition = self._louvain(graph)

        # 按社区聚合
        communities_map: dict[int, list[str]] = {}
        for node, cid in partition.items():
            communities_map.setdefault(cid, []).append(node)

        results: list[Community] = []
        for cid, members in communities_map.items():
            if len(members) < self.min_community_size:
                continue
            stats = self._compute_stats(
                cid, members, node_amounts or {}, node_fraud_labels or {}
            )
            results.append(Community(community_id=cid, members=members, stats=stats))

        logger.info(
            "community.detected",
            algorithm=self.algorithm,
            n_communities=len(results),
            n_fraud_gangs=sum(1 for c in results if c.stats.is_fraud_gang),
        )
        return results

    def _louvain(self, graph: Any) -> dict[str, int]:
        """Louvain 社区发现（python-louvain / networkx）。"""
        try:
            import networkx as nx  # type: ignore

            # 优先使用 networkx 3.x 内置 louvain_communities
            if hasattr(nx, "louvain_communities"):
                communities = nx.louvain_communities(
                    graph, resolution=self.resolution, seed=42
                )
                partition: dict[str, int] = {}
                for cid, members in enumerate(communities):
                    for node in members:
                        partition[node] = cid
                return partition
        except Exception as exc:  # noqa: BLE001
            logger.warning("community.louvain.networkx_failed", error=str(exc))

        try:
            import community as community_louvain  # type: ignore

            best_partition = community_louvain.best_partition(  # type: ignore[attr-defined]
                graph, resolution=self.resolution, random_state=42
            )
            return {node: int(cid) for node, cid in best_partition.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("community.louvain.fallback_to_label_prop", error=str(exc))
            return self._label_propagation(graph)

    def _label_propagation(self, graph: Any) -> dict[str, int]:
        """Label Propagation 社区发现（networkx 内置）。"""
        import networkx as nx  # type: ignore

        communities = nx.algorithms.community.label_propagation_communities(graph)
        partition: dict[str, int] = {}
        for cid, members in enumerate(communities):
            for node in members:
                partition[node] = cid
        return partition

    def _compute_stats(
        self,
        cid: int,
        members: list[str],
        node_amounts: dict[str, float],
        node_fraud_labels: dict[str, bool],
    ) -> CommunityStats:
        total_amount = sum(node_amounts.get(m, 0.0) for m in members)
        fraud_count = sum(1 for m in members if node_fraud_labels.get(m, False))
        member_count = len(members)
        fraud_rate = fraud_count / member_count if member_count else 0.0
        is_fraud_gang = fraud_rate > self.fraud_rate_threshold
        # 风险分 = 欺诈率 × 0.7 + min(member_count / 50, 1.0) × 0.3
        risk_score = fraud_rate * 0.7 + min(member_count / 50.0, 1.0) * 0.3
        return CommunityStats(
            community_id=cid,
            member_count=member_count,
            total_amount=total_amount,
            fraud_count=fraud_count,
            fraud_rate=fraud_rate,
            risk_score=min(risk_score, 1.0),
            is_fraud_gang=is_fraud_gang,
        )


__all__ = ["Community", "CommunityDetector", "CommunityStats"]
