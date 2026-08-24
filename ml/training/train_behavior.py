"""训练 1D-CNN 行为时序模态。

对应 D03 §4.3：
    behavior → 1D-CNN + IsolationForest → score_behavior

模型结构：Conv1d × 3 + GlobalAvgPool + Linear(sigmoid)（与推理侧 modalities/behavior.py 对齐）。
输出：model_versions 表 status=REGISTERED，model_type=BEHAVIOR。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BehaviorTrainResult:
    model_path: str
    n_samples: int
    metrics: dict[str, float]


def _build_model(in_channels: int, seq_len: int):
    import torch.nn as nn  # type: ignore

    class Behavior1DCNN(nn.Module):
        def __init__(self, in_channels: int, seq_len: int) -> None:
            super().__init__()
            self.conv1 = nn.Conv1d(in_channels, 32, kernel_size=3, padding=1)
            self.conv2 = nn.Conv1d(32, 64, kernel_size=3, padding=1)
            self.conv3 = nn.Conv1d(64, 128, kernel_size=3, padding=1)
            self.relu = nn.ReLU()
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.fc = nn.Linear(128, 1)

        def forward(self, x):
            import torch  # type: ignore

            x = self.relu(self.conv1(x))
            x = self.relu(self.conv2(x))
            x = self.relu(self.conv3(x))
            x = self.pool(x).squeeze(-1)
            return torch.sigmoid(self.fc(x))

    return Behavior1DCNN(in_channels, seq_len)


def _pad_or_truncate(series: list[list[float]], seq_len: int, n_features: int):
    import numpy as np  # type: ignore

    if len(series) >= seq_len:
        series = series[:seq_len]
    cols: list[list[float]] = (
        [list(col) for col in zip(*series, strict=False)]
        if series
        else [[0.0] * seq_len for _ in range(n_features)]
    )
    while len(cols) < n_features:
        cols.append([0.0] * seq_len)
    for i, col in enumerate(cols):
        if len(col) < seq_len:
            cols[i] = list(col) + [0.0] * (seq_len - len(col))
        else:
            cols[i] = list(col)[:seq_len]
    return np.asarray(cols, dtype=np.float32)


def train(
    series_list: list[list[list[float]]],
    labels: list[int],
    save_path: str,
    epochs: int = 10,
    batch_size: int = 64,
    learning_rate: float = 1e-3,
    seq_len: int = 50,
    n_features: int = 8,
) -> BehaviorTrainResult:
    """训练 1D-CNN 行为模型。"""
    import numpy as np  # type: ignore
    import torch  # type: ignore
    from torch.utils.data import DataLoader, TensorDataset  # type: ignore

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    arrays = [_pad_or_truncate(s, seq_len, n_features) for s in series_list]
    X = torch.from_numpy(np.stack(arrays, axis=0)).float()  # (N, n_features, seq_len)
    y = torch.tensor(labels, dtype=torch.float32).unsqueeze(1)
    dataset = TensorDataset(X, y)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    model = _build_model(n_features, seq_len).to(device)
    criterion = torch.nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        logger.info("behavior.train.epoch", epoch=epoch + 1, total=epochs, loss=total_loss)

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), save_path)

    # 评估
    model.eval()
    probas: list[float] = []
    with torch.no_grad():
        for batch_x, _ in DataLoader(dataset, batch_size=batch_size):
            outputs = model(batch_x.to(device)).cpu().numpy().flatten()
            probas.extend(outputs.tolist())

    from .evaluate import compute_auc, compute_f1, compute_recall_at_fpr

    metrics = {
        "auc": compute_auc(labels, probas),
        "f1": compute_f1(labels, [1 if p >= 0.5 else 0 for p in probas]),
        "recall_at_1pct_fpr": compute_recall_at_fpr(labels, probas, fpr_threshold=0.01),
    }
    logger.info(
        "behavior.train.done",
        save_path=save_path,
        n_samples=len(labels),
        metrics=metrics,
    )
    return BehaviorTrainResult(model_path=save_path, n_samples=len(labels), metrics=metrics)


__all__ = ["train", "BehaviorTrainResult"]
