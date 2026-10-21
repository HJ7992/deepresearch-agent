"""嵌入层：默认用本地哈希嵌入（离线、零成本），配好环境变量就换成真实嵌入 API。

谁在用：retriever.VectorStore 在初始化和检索时调用它。

为什么做成两个方法的接口（embed_documents / embed_query）：检索层只关心
「把文本变成向量」，不关心背后是哈希还是 BGE。所以 CI 和离线演示用哈希嵌入，
保证结果确定、不花一分钱；生产上配好 EMBEDDING_* 三项就自动换成真实语义嵌入，
上层代码一行都不用改。

哈希嵌入的局限（务必知道）：它只捕捉字面相似（字符 n-gram 落到哈希桶），
不理解语义，同义改写基本召不回来。它存在的唯一意义是「没网络、没 key 也能
把全链路跑通」。
"""

import hashlib
import itertools
import math
import re

from .config import Settings, settings


class HashingEmbedder:
    """中文字 / 中文双字 / 英文词的哈希嵌入，512 维，L2 归一化。"""

    dim = 512

    def _tokens(self, text: str) -> list[str]:
        """把文本切成用于哈希的最小单位。"""
        text = text.lower()
        chars = re.findall(r"[\u4e00-\u9fff]", text)  # 中文单字
        words = re.findall(r"[a-z0-9_]+", text)       # 英文/数字词
        bigrams = [a + b for a, b in itertools.pairwise(chars)]  # 中文双字（补一点顺序信息）
        return chars + words + bigrams

    def _embed_one(self, text: str) -> list[float]:
        """每个 token 哈希到某一维，并用哈希的一位决定加还是减（减少碰撞偏置）。"""
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            h = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 == 0 else -1.0
            vec[idx] += sign
        # L2 归一化：之后用余弦相似度才不会被文本长度带偏
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入（入库用）。"""
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """嵌入一条查询（检索用）。"""
        return self._embed_one(text)


class OpenAICompatEmbedder:
    """调用任意 OpenAI 兼容 /embeddings 端点（例如托管的 BGE 服务）。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        # 延迟到用时才 import：不配真实嵌入就不需要拉起这个客户端
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
    """三项 EMBEDDING_* 都配了就用真实嵌入，否则（默认）用本地哈希嵌入。"""
    cfg = cfg or settings
    if cfg.embedding_base_url and cfg.embedding_api_key and cfg.embedding_model:
        return OpenAICompatEmbedder(
            cfg.embedding_api_key, cfg.embedding_base_url, cfg.embedding_model
        )
    return HashingEmbedder()
