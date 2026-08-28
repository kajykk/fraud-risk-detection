"""GraphSAGE 模型定义（D03 §4.4）。

技术栈：torch_geometric.nn.SAGEConv 2.5
模型结构：
    SAGEConv(in, 256) → SAGEConv(256, 128) → embedding(128)
    forward(x, edge_index) → embedding

训练目标：节点表征学习，用于团伙检测 / 关联风险评分。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class GraphSAGE:
    """GraphSAGE 模型包装类（torch_geometric.nn.SAGEConv）。

    隐藏层维度由 config.GraphSAGEConfig.hidden_channels 决定（默认 [256, 128]）。
    """

    def __init__(
        self,
        in_channels: int = 64,
        hidden_channels: list[int] | None = None,
        out_channels: int = 128,
        dropout: float = 0.2,
    ) -> None:
        self.in_channels = in_channels
        self.hidden_channels = hidden_channels or [256, 128]
        self.out_channels = out_channels
        self.dropout = dropout
        self._model: Any = None  # 实际的 torch_geometric.nn.Module
        self._device: Any = None
        self._loaded = False  # 训练权重是否已加载

    def build(self) -> Any:
        """构建 PyG SAGEConv 模型。"""
        import torch
        from torch_geometric.nn import SAGEConv

        class _SAGEModule(torch.nn.Module):
            def __init__(
                self,
                in_channels: int,
                hidden_channels: list[int],
                out_channels: int,
                dropout: float,
            ) -> None:
                super().__init__()
                layers = []
                dims = [in_channels] + list(hidden_channels)
                for i in range(len(dims) - 1):
                    layers.append(SAGEConv(dims[i], dims[i + 1]))
                self.convs = torch.nn.ModuleList(layers)
                self.final = SAGEConv(dims[-1], out_channels)
                self.dropout = torch.nn.Dropout(dropout)
                self.relu = torch.nn.ReLU()

            def forward(self, x: Any, edge_index: Any) -> Any:
                for conv in self.convs:
                    x = self.relu(conv(x, edge_index))
                    x = self.dropout(x)
                x = self.final(x, edge_index)
                return x

        self._model = _SAGEModule(
            self.in_channels,
            self.hidden_channels,
            self.out_channels,
            self.dropout,
        )
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(self._device)
        # 服务包装类默认推理用途：构建后立即置 eval，避免 dropout 引入不确定性
        self._model.eval()
        self._loaded = False
        logger.info(
            "graphsage.built",
            in_channels=self.in_channels,
            hidden_channels=self.hidden_channels,
            out_channels=self.out_channels,
            device=str(self._device),
        )
        return self._model

    @property
    def is_loaded(self) -> bool:
        """是否已加载训练好的权重（未加载时 embedding 输出无业务意义）。"""
        return bool(self._loaded and self._model is not None)

    def load(self, path: str) -> Any:
        """加载训练好的权重。"""
        import torch

        if self._model is None:
            self.build()
        state = torch.load(path, map_location=self._device, weights_only=True)
        self._model.load_state_dict(state)  # type: ignore[union-attr]
        self._model.eval()  # type: ignore[union-attr]
        self._loaded = True
        logger.info("graphsage.loaded", path=path)
        return self._model

    def forward(self, x: Any, edge_index: Any) -> Any:
        """前向推理：返回节点 embedding。

        仅允许在已加载训练权重后调用（随机权重输出会污染下游团伙检测）。
        """
        if self._model is None or not self._loaded:
            raise RuntimeError("graphsage_weights_not_loaded")
        with __import__("torch").no_grad():
            return self._model(x.to(self._device), edge_index.to(self._device))


__all__ = ["GraphSAGE"]
