"""TokenizationService（PCI-DSS ADR-005）。

- 卡号一律 Token，不存明文 PAN
- local 模式：Fernet 对称加密 + 映射表（MVP）
- aliyun-kms 模式：阿里云 KMS（生产）
- Format-Preserving Tokenization（V2）
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TokenizationService:
    """卡号 Tokenization 服务。"""

    def __init__(self) -> None:
        self.provider = settings.tokenization_provider
        # TODO: 初始化 Fernet / KMS client

    async def tokenize(self, pan: str) -> str:
        """将 PAN 转为 Token。

        MVP 实现：SHA256(pan + secret_key)[:24] 作为 token，前缀 tok_card_。
        生产应使用 Format-Preserving Tokenization（保持卡号长度与格式）。
        """
        if self.provider == "local":
            digest = hashlib.sha256(
                f"{pan}:{settings.tokenization_local_key}".encode()
            ).hexdigest()[:24]
            return f"tok_card_{digest}"
        # TODO: aliyun-kms 模式
        logger.warning("tokenization_provider_not_implemented", provider=self.provider)
        return f"tok_card_{hashlib.sha256(pan.encode()).hexdigest()[:24]}"

    async def detokenize(self, token: str) -> str:
        """Token 反查 PAN（仅在 CDE 区，严格审计）。

        TODO: 实现 token -> PAN 映射表查询（生产用独立加密存储）。
        """
        logger.warning("detokenize_not_implemented", token_prefix=token[:12])
        raise NotImplementedError("detokenize requires CDE-zone token mapping table")

    async def extract_bin_last4(self, pan: str) -> tuple[str, str]:
        """从 PAN 提取 BIN（前 6 位）和 Last4（后 4 位）。"""
        if len(pan) < 10:
            raise ValueError("invalid PAN length")
        return pan[:6], pan[-4:]


# 单例
tokenization_service = TokenizationService()


__all__ = ["TokenizationService", "tokenization_service"]
