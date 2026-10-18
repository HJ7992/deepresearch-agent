"""嵌入层：本地哈希嵌入（默认，离线零成本）+ OpenAI 兼容嵌入 API（可选）。

设计要点（面试话术）：嵌入被抽象成 embed_documents / embed_query 两个方法，
检索层不关心具体实现——CI 和离线演示用哈希嵌入保证确定性、不花钱；
配置了 EMBEDDING_* 就换成真实语义嵌入（bge / text-embedding 类），无需改检索代码。

哈希嵌入的局限：只捕捉字面相似（字符 n-gram 的哈希桶），不理解语义。
它存在的意义是「没有网络、没有 key 也能跑通全链路」，生产请换真实嵌入模型。
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re

from .config import Settings, settings


class HashingEmbedder:
    """中文字/双字 + 英文词的哈希嵌入，512 维，L2 归一化。"""

    dim = 512

    def _tokens(self, text: str) -> list[str]:
        text = text.lower()
        chars = re.findall(r"[\u4e00-\u9fff]", text)  # 中文单字
        words = re.findall(r"[a-z0-9_]+", text)  # 英文词
        bigrams = [a + b for a, b in itertools.pairwise(chars)]  # 中文双字
        return chars + words + bigrams

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            h = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAICompatEmbedder:
    """调用任意 OpenAI 兼容 /embeddings 端点（如托管的 BGE 服务）。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url or None)
        self._model = model
        self.weighted = 1.0  # 与 HashingEmbedder 接口保持一致的占位属性

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embedder(cfg: Settings | None = None):
    """三项 EMBEDDING_* 都配了就用真实嵌入，否则（默认）本地哈希。"""
    cfg = cfg or settings
    if cfg.embedding_base_url and cfg.embedding_api_key and cfg.embedding_model:
        return OpenAICompatEmbedder(
            cfg.embedding_api_key, cfg.embedding_base_url, cfg.embedding_model
        )
    return HashingEmbedder()
