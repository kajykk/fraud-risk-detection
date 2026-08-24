"""训练 GraphSAGE（D03 §4.4 / §5.2）。

离线计算（每日 02:00）：
- GraphSAGE 训练节点嵌入
- 社区发现（Louvain）
- 嵌入写入 PostgreSQL + Redis 缓存

训练目标：节点表征学习（无监督 + 监督微调）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from ..models.graphsage import GraphSAGE

logger = structlog.get_logger(__name__)


@dataclass
class TrainResult:
    model_path: str
    n_nodes: int
    n_edges: int
    embedding_dim: int
    loss: float


def train(
    snapshot: Any,
    save_path: str,
    in_channels: int = 64,
    hidden_channels: list[int] | None = None,
    out_channels: int = 128,
    epochs: int = 50,
    learning_rate: float = 1e-3,
) -> TrainResult:
    """训练 GraphSAGE。

    Args:
        snapshot: GraphSnapshot（节点 + 边）
        save_path: 模型保存路径
        in_channels: 输入特征维度
        hidden_channels: 隐藏层维度列表（默认 [256, 128]）
        out_channels: 输出 embedding 维度
        epochs: 训练轮数
        learning_rate: 学习率
    """
    import torch  # type: ignore

    if hidden_channels is None:
        hidden_channels = [256, 128]

    model_wrapper = GraphSAGE(
        in_channels=in_channels,
        hidden_channels=hidden_channels,
        out_channels=out_channels,
    )
    model = model_wrapper.build()
    device = model_wrapper._device  # type: ignore[attr-defined]

    x = snapshot.node_features.to(device)
    edge_index = snapshot.edge_index.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    # 无监督训练：基于节点相似度的对比损失（简化实现）
    # 实际可使用 PyG 的 GraphSAGE 自监督损失（negative sampling）
    model.train()
    final_loss = 0.0
    for epoch in range(epochs):
        optimizer.zero_grad()
        embeddings = model(x, edge_index)
        # 简化损失：embedding 范数约束 + 邻居对齐
        norm_loss = torch.mean(torch.norm(embeddings, dim=-1))
        # 邻居对齐：邻居节点 embedding 应相似
        if edge_index.size(1) > 0:
            src = embeddings[edge_index[0]]
            dst = embeddings[edge_index[1]]
            align_loss = torch.mean(1.0 - torch.nn.functional.cosine_similarity(src, dst))
            loss = align_loss + 0.001 * norm_loss
        else:
            loss = 0.001 * norm_loss
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())
        if (epoch + 1) % 10 == 0:
            logger.info("graphsage.train.epoch", epoch=epoch + 1, total=epochs, loss=final_loss)

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), save_path)
    n_nodes = x.size(0)
    n_edges = edge_index.size(1)
    logger.info(
        "graphsage.train.done",
        save_path=save_path,
        n_nodes=n_nodes,
        n_edges=n_edges,
        out_channels=out_channels,
        loss=final_loss,
    )
    return TrainResult(
        model_path=save_path,
        n_nodes=n_nodes,
        n_edges=n_edges,
        embedding_dim=out_channels,
        loss=final_loss,
    )


__all__ = ["TrainResult", "train"]
