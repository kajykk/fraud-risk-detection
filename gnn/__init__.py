"""FRD GNN 模块（D03 §1.3 / §4.4）。

子模块：
- main: FastAPI GNN 服务入口（端口 8502）
- graph_service: 图查询服务（Neo4j + GraphSAGE）
- models: GraphSAGE 模型定义
- training: GraphSAGE 训练 + 图构建
- community: 团伙检测（Louvain / Label Propagation）
- tests: 单元测试
"""

__all__ = [
    "main",
    "config",
    "graph_service",
    "models",
    "training",
    "community",
]
