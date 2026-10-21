"""向量检索层：对 Qdrant 的薄封装，支持「本地嵌入式」和「连服务端」两种形态。

谁在用：ingest.py 入库时用它写数据；runner/节点里的 researcher 用它检索；
api.py 的 /health 用它报索引块数。

两种形态怎么选：
- 没配 QDRANT_URL：QdrantClient(path=...) 把索引存在本地目录，零部署，
  但有文件锁、同一路径只能一个进程用——适合开发、演示、CI；
- 配了 QDRANT_URL：连 docker compose 里的 Qdrant 服务，多进程共享，生产形态。

为什么要单独一层：检索和生成解耦，换向量库只改这个文件。
"""

import atexit
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
    """一条检索结果：id 用来去重，source 是来源文件名，score 是相似度。"""

    id: str
    text: str
    source: str
    score: float = 0.0


def _point_id(chunk_id: str) -> int:
    """把字符串 chunk_id 稳定地映射成 Qdrant 需要的整数点 id。

    用哈希而不是自增：同样的 chunk 重复入库会覆盖同一点，索引就是幂等的。
    """
    return int.from_bytes(hashlib.md5(chunk_id.encode("utf-8")).digest()[:8], "little") >> 1


class VectorStore:
    """文档入库 + 检索。索引是幂等的：同一 chunk_id 重复写入会覆盖，不会产生副本。"""

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
        """集合不存在就建一个，维度按嵌入器实际输出的维度来定，避免维度不匹配。"""
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
        """删除集合并等下次写入时重建（重建索引前调用）。"""
        try:
            self.client.delete_collection(self.cfg.qdrant_collection)
        except Exception as exc:  # noqa: BLE001 — 集合不存在时属正常情况
            logger.debug("删除集合失败（通常是不存在）：%s", exc)

    def count(self) -> int:
        """当前集合里有多少条可检索片段；集合不存在按 0 处理。"""
        try:
            return self.client.count(self.cfg.qdrant_collection).count
        except Exception:  # noqa: BLE001 — 集合不存在时按 0 处理
            return 0

    # ---- 写入与检索 ----
    def index(self, chunks: list[RetrievedChunk]) -> int:
        """批量入库，返回写入条数。"""
        if not chunks:
            return 0
        self._ensure_collection()
        vectors = self.embedder.embed_documents([c.text for c in chunks])
        points = [
            PointStruct(
                id=_point_id(c.id),
                vector=vec,
                # payload 里存原文和来源：检索时一次拿全，不用再查一次
                payload={"chunk_id": c.id, "text": c.text, "source": c.source},
            )
            for c, vec in zip(chunks, vectors)
        ]
        self.client.upsert(collection_name=self.cfg.qdrant_collection, points=points)
        return len(points)

    def search(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        """返回最相关的 k 个片段；库是空的就返回空列表（researcher 会如实说没资料）。"""
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
        """释放客户端（本地模式下等于释放文件锁）。"""
        self.client.close()


# 本地模式下同一路径只能开一个客户端（文件锁），所以按路径缓存单例复用
_stores: dict[str, VectorStore] = {}


def get_store(cfg: Settings | None = None) -> VectorStore:
    """按「服务端地址 / 本地路径」取同一个 VectorStore 实例。"""
    cfg = cfg or settings
    key = cfg.qdrant_url or os.path.abspath(cfg.qdrant_local_path)
    if key not in _stores:
        _stores[key] = VectorStore(cfg)
    return _stores[key]


def _close_all_stores() -> None:
    """进程退出时释放本地向量库文件锁，避免 __del__ 告警。"""
    for store in list(_stores.values()):
        try:
            store.close()
        except Exception:  # noqa: BLE001, S110 — 退出阶段尽力而为，不打印
            pass


atexit.register(_close_all_stores)
