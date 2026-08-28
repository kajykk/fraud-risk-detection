"""训练 GraphSAGE（D03 §4.4 / §5.2）。

离线计算（每日 02:00）：
- GraphSAGE 训练节点嵌入
- 社区发现（Louvain）
- 嵌入写入 PostgreSQL + Redis 缓存

训练目标：无监督链接预测（正样本=真实边，负样本=随机节点对，
BCEWithLogits on 内积得分）。历史实现的"embedding 范数惩罚 +
邻居 cosine 对齐"存在退化解：最小化范数把所有表征推向零向量，
cosine 在零向量处梯度无意义，模型输出无判别力。

工程化：
- 边集 9:1 划分训练/验证，按验证损失保留最优权重（防过拟合）；
- 固定随机种子保证可复现；
- 图退化（边数不足）直接失败，不产出随机权重模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from ..models.graphsage import GraphSAGE

logger = structlog.get_logger(__name__)

# 验证边比例与最低可训练边数（低于阈值视为图退化）
_VAL_RATIO = 0.1
_MIN_EDGES = 20


@dataclass
class TrainResult:
    model_path: str
    n_nodes: int
    n_edges: int
    embedding_dim: int
    loss: float
    val_loss: float
    n_train_edges: int
    n_val_edges: int


def _negative_sample(
    edge_index: Any,
    num_nodes: int,
    num_samples: int,
    generator: Any,
    device: Any,
) -> Any:
    """采样负样本节点对：拒绝采到真实边（含反向），上限重试防死循环。"""
    import torch

    edge_set = {
        (int(edge_index[0, i]), int(edge_index[1, i]))
        for i in range(edge_index.size(1))
    }
    src = torch.randint(0, num_nodes, (num_samples,), generator=generator, device="cpu")
    dst = torch.randint(0, num_nodes, (num_samples,), generator=generator, device="cpu")
    keep_src, keep_dst = [], []
    for s, d in zip(src.tolist(), dst.tolist(), strict=False):
        if s == d or (s, d) in edge_set or (d, s) in edge_set:
            continue
        keep_src.append(s)
        keep_dst.append(d)
    src_t = torch.tensor(keep_src, dtype=torch.long, device=device)
    dst_t = torch.tensor(keep_dst, dtype=torch.long, device=device)
    return src_t, dst_t


def train(
    snapshot: Any,
    save_path: str,
    in_channels: int = 64,
    hidden_channels: list[int] | None = None,
    out_channels: int = 128,
    epochs: int = 50,
    learning_rate: float = 1e-3,
    seed: int = 42,
) -> TrainResult:
    """训练 GraphSAGE（链接预测目标）。

    Args:
        snapshot: GraphSnapshot（node_features + edge_index）
        save_path: 模型保存路径
        in_channels: 输入特征维度
        hidden_channels: 隐藏层维度列表（默认 [256, 128]）
        out_channels: 输出 embedding 维度
        epochs: 训练轮数
        learning_rate: 学习率
        seed: 随机种子（可复现）
    """
    import torch

    if hidden_channels is None:
        hidden_channels = [256, 128]

    x_all = snapshot.node_features
    edge_index_all = snapshot.edge_index
    num_nodes = x_all.size(0)
    num_edges = edge_index_all.size(1)
    if num_edges < _MIN_EDGES:
        raise RuntimeError(
            f"graph degenerate: {num_edges} edges < {_MIN_EDGES}; "
            "refusing to train (random-weight artifacts pollute serving)"
        )

    generator = torch.Generator().manual_seed(seed)

    # 边集划分：验证边留作泛型评估（消息传递仍用全图，转导式设置）
    perm = torch.randperm(num_edges, generator=generator)
    n_val = max(1, int(num_edges * _VAL_RATIO))
    val_idx, train_idx = perm[:n_val], perm[n_val:]
    train_edge_index = edge_index_all[:, train_idx]

    model_wrapper = GraphSAGE(
        in_channels=in_channels,
        hidden_channels=hidden_channels,
        out_channels=out_channels,
    )
    model = model_wrapper.build()
    device = model_wrapper._device

    x = x_all.to(device)
    full_edge_index = edge_index_all.to(device)
    train_edges = train_edge_index.to(device)
    val_edges = edge_index_all[:, val_idx].to(device)

    optimizer = torch.optim.Adam(
        model.parameters(), lr=learning_rate, weight_decay=5e-4
    )
    criterion = torch.nn.BCEWithLogitsLoss()

    def _score_loss(edges: Any) -> tuple[Any, Any]:
        emb = model(x, full_edge_index)
        pos_score = (emb[edges[0]] * emb[edges[1]]).sum(dim=-1)
        neg_src, neg_dst = _negative_sample(
            edges, num_nodes, edges.size(1), generator, device
        )
        neg_score = (emb[neg_src] * emb[neg_dst]).sum(dim=-1)
        logits = torch.cat([pos_score, neg_score], dim=0)
        targets = torch.cat(
            [torch.ones(pos_score.size(0)), torch.zeros(neg_score.size(0))],
            dim=0,
        ).to(device)
        return criterion(logits, targets), float(logits.detach().float().sigmoid().mean())

    model.train()
    final_train_loss = 0.0
    best_val_loss = float("inf")
    best_state: dict[str, Any] | None = None

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        loss, _ = _score_loss(train_edges)
        loss.backward()
        optimizer.step()
        final_train_loss = float(loss.item())

        # 验证：固定验证边 + eval 模式（关闭 dropout）
        model.eval()
        with torch.no_grad():
            val_loss, _ = _score_loss(val_edges)
        val_loss_val = float(val_loss.item())
        if val_loss_val < best_val_loss:
            best_val_loss = val_loss_val
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 10 == 0:
            logger.info(
                "graphsage.train.epoch",
                epoch=epoch + 1,
                total=epochs,
                loss=final_train_loss,
                val_loss=val_loss_val,
            )

    if best_state is not None:
        model.load_state_dict(best_state)
        model.eval()

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), save_path)
    logger.info(
        "graphsage.train.done",
        save_path=save_path,
        n_nodes=num_nodes,
        n_edges=num_edges,
        n_train_edges=int(train_idx.numel()),
        n_val_edges=int(val_idx.numel()),
        out_channels=out_channels,
        loss=final_train_loss,
        best_val_loss=best_val_loss,
    )
    return TrainResult(
        model_path=save_path,
        n_nodes=num_nodes,
        n_edges=num_edges,
        embedding_dim=out_channels,
        loss=final_train_loss,
        val_loss=best_val_loss,
        n_train_edges=int(train_idx.numel()),
        n_val_edges=int(val_idx.numel()),
    )


__all__ = ["TrainResult", "train"]
