"""GNN 图查询服务单元测试。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from gnn.community.detector import CommunityDetector
from gnn.graph_service import GNNGraphService, Graph


class _FakeRedis:
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def service() -> GNNGraphService:
    return GNNGraphService(
        neo4j_driver=None,  # 不连接真实 Neo4j
        redis_client=_FakeRedis(),
        graphsage=None,
        community_detector=CommunityDetector(min_community_size=2),
    )


def test_query_related_returns_empty_when_no_driver(service: GNNGraphService) -> None:
    """无 Neo4j driver → 返回空图（不抛异常）。"""
    graph = asyncio.run(service.query_related("node-1", k_hops=2, tenant_id="t1"))
    assert isinstance(graph, Graph)
    assert graph.center_node_id == "node-1"
    assert graph.nodes == []
    assert graph.edges == []


def test_compute_embedding_returns_empty_when_no_model(service: GNNGraphService) -> None:
    """GraphSAGE 未加载 → 返回空 embedding。"""
    embedding = asyncio.run(service.compute_embedding("node-1", tenant_id="t1"))
    assert embedding == []


def test_detect_community_with_simple_graph() -> None:
    """团伙检测：构造简单图 → 检测社区。"""
    detector = CommunityDetector(min_community_size=2, fraud_rate_threshold=0.5)
    nodes = ["a", "b", "c", "d", "e", "f"]
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("d", "e"), ("e", "f")]
    fraud_labels = {"a": True, "b": True, "c": False, "d": False, "e": False, "f": False}
    communities = detector.detect(
        nodes=nodes, edges=edges, node_fraud_labels=fraud_labels
    )
    assert len(communities) >= 1
    # 至少有一个社区成员数 >= 2
    assert any(c.stats.member_count >= 2 for c in communities)


def test_community_stats_fraud_gang_detection() -> None:
    """fraud_rate > 0.3 → 标记 is_fraud_gang=True。"""
    detector = CommunityDetector(min_community_size=2, fraud_rate_threshold=0.3)
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "a")]
    # 4 个节点，3 个欺诈 → fraud_rate = 0.75 → 欺诈团伙
    fraud_labels = {"a": True, "b": True, "c": True, "d": False}
    communities = detector.detect(
        nodes=nodes, edges=edges, node_fraud_labels=fraud_labels
    )
    assert any(c.stats.is_fraud_gang for c in communities)
    assert any(c.stats.fraud_rate > 0.3 for c in communities)


def test_graph_dataclass() -> None:
    """Graph dataclass 默认值。"""
    g = Graph(center_node_id="x", nodes=[], edges=[], k_hops=2)
    assert g.latency_ms == 0.0
    assert g.queried_at > 0
