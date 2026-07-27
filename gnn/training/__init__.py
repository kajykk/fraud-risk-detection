"""GNN 训练子模块。"""

from .build_graph import GraphBuilder
from .train_graphsage import train

__all__ = ["GraphBuilder", "train"]
