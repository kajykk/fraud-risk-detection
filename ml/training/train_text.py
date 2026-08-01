"""微调 BERT 文本模态。

对应 D03 §4.3：
    text → BERT (金融微调) → score_text

基础模型：bert-base-chinese（PIPL 合规 + 中文场景优化）。
输出：model_versions 表 status=REGISTERED，model_type=TEXT。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TextTrainResult:
    model_path: str
    n_samples: int
    metrics: dict[str, float]


def train(
    texts: list[str],
    labels: list[int],
    save_path: str,
    base_model: str = "bert-base-chinese",
    epochs: int = 3,
    batch_size: int = 32,
    learning_rate: float = 2e-5,
    max_length: int = 128,
) -> TextTrainResult:
    """微调 BERT 二分类模型。"""
    import torch  # type: ignore
    from torch.utils.data import DataLoader, Dataset  # type: ignore
    from transformers import (  # type: ignore
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, num_labels=2
    ).to(device)

    class TextDataset(Dataset):
        def __init__(self, texts, labels, tokenizer, max_length):
            self.texts = texts
            self.labels = labels
            self.tokenizer = tokenizer
            self.max_length = max_length

        def __len__(self):
            return len(self.texts)

        def __getitem__(self, idx):
            enc = self.tokenizer(
                self.texts[idx],
                truncation=True,
                padding="max_length",
                max_length=self.max_length,
                return_tensors="pt",
            )
            return {
                "input_ids": enc["input_ids"].squeeze(0),
                "attention_mask": enc["attention_mask"].squeeze(0),
                "labels": torch.tensor(self.labels[idx], dtype=torch.long),
            }

    dataset = TextDataset(texts, labels, tokenizer, max_length)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    total_steps = len(loader) * epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=0, num_training_steps=total_steps
    )

    model.train()
    for epoch in range(epochs):
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
        logger.info("text.train.epoch", epoch=epoch + 1, total=epochs)

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)

    # 评估
    model.eval()
    probas: list[float] = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=batch_size):
            inputs = {
                "input_ids": batch["input_ids"].to(device),
                "attention_mask": batch["attention_mask"].to(device),
            }
            logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[:, 1]
            probas.extend(probs.cpu().numpy().tolist())

    from .evaluate import compute_auc, compute_f1, compute_recall_at_fpr

    metrics = {
        "auc": compute_auc(labels, probas),
        "f1": compute_f1(labels, [1 if p >= 0.5 else 0 for p in probas]),
        "recall_at_1pct_fpr": compute_recall_at_fpr(labels, probas, fpr_threshold=0.01),
    }
    logger.info("text.train.done", save_path=save_path, n_samples=len(texts), metrics=metrics)
    return TextTrainResult(model_path=save_path, n_samples=len(texts), metrics=metrics)


__all__ = ["train", "TextTrainResult"]
