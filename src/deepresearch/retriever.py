"""向量检索层：Qdrant 封装（本地嵌入式 / 服务端两种形态）。

- 未配置 QDRANT_URL：QdrantClient(path=...) 本地嵌入式，零部署依赖，适合开发与演示；
- 配置 QDRANT_URL：连 docker compose 里的 Qdrant 服务，生产形态。

面试话术：检索与生成分离，换向量库只需要改这一层；集合首次写入时按嵌入维度
自动创建，避免维度不匹配。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from .config import Settings, settings
from .embeddings import get_embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    """检索结果：id 用于去重，source 是文件名，score 是相似度。"""

    id: str
    text: str
    source: str
    score: float = 0.0


def _point_id(chunk_id: str) -> int:
    """Qdrant 点 id 用哈希取整数（稳定、可重入，重复写入不会产生副本）。"""
    return int.from_bytes(hashlib.md5(chunk_id.encode("utf-8")).digest()[:8], "little") >> 1


class VectorStore:
    """文档入库 + 检索。索引是幂等的：同一 chunk_id 重复写入会覆盖。"""

    def __init__(self, cfg: Settings | None = None):
        self.cfg = cfg or settings
        self.embedder = get_embedder(self.cfg)
        if self.cfg.qdrant_url:
            self.client = QdrantClient(url=self.cfg.qdrant_url)
            self._mode = f"服务端 {self.cfg.qdrant_url}"
        else:
            self.client = QdrantClient(path=self.cfg.qdrant_local_path)
            self._mode = f"本地 {os.path.abspath(self.cfg.qdrant_local_path)}"

    # ---- 集合管理 ----
    def _ensure_collection(self) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if self.cfg.qdrant_collection in existing:
            return
        dim = len(self.embedder.embed_query("维度探针"))
        self.client.create_collection(
            collection_name=self.cfg.qdrant_collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("已创建集合 %s（维度 %d，模式：%s）",
                    self.cfg.qdrant_collection, dim, self._mode)

    def reset(self) -> None:
        """删除集合并重建（重建索引前调用）。"""
        try:
            self.client.delete_collection(self.cfg.qdrant_collection)
        except Exception as exc:  # noqa: BLE001 — 集合不存在时属正常情况
            logger.debug("删除集合失败（通常是不存在）：%s", exc)

    def count(self) -> int:
        try:
            return self.client.count(self.cfg.qdrant_collection).count
        except Exception:  # noqa: BLE001 — 集合不存在时按 0 处理
            return 0

    # ---- 写入与检索 ----
    def index(self, chunks: list[RetrievedChunk]) -> int:
        if not chunks:
            return 0
        self._ensure_collection()
        vectors = self.embedder.embed_documents([c.text for c in chunks])
        points = [
            PointStruct(
                id=_point_id(c.id),
                vector=vec,
                payload={"chunk_id": c.id, "text": c.text, "source": c.source},
            )
            for c, vec in zip(chunks, vectors)
        ]
        self.client.upsert(collection_name=self.cfg.qdrant_collection, points=points)
        return len(points)

    def search(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        """返回最相关的 k 个片段；集合为空时返回空列表（researcher 会如实说无资料）。"""
        if self.count() == 0:
            return []
        vector = self.embedder.embed_query(query)
        resp = self.client.query_points(
            collection_name=self.cfg.qdrant_collection,
            query=vector,
            limit=k or self.cfg.top_k,
            with_payload=True,
        )
        return [
            RetrievedChunk(
                id=p.payload.get("chunk_id", str(p.id)),
                text=p.payload.get("text", ""),
                source=p.payload.get("source", "?"),
                score=float(p.score),
            )
            for p in resp.points
        ]

    def close(self) -> None:
        self.client.close()


# 本地模式下同一路径只能开一个客户端（文件锁），因此按路径缓存单例
_stores: dict[str, VectorStore] = {}


def get_store(cfg: Settings | None = None) -> VectorStore:
    cfg = cfg or settings
    key = cfg.qdrant_url or os.path.abspath(cfg.qdrant_local_path)
    if key not in _stores:
        _stores[key] = VectorStore(cfg)
    return _stores[key]
