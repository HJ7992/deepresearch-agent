"""向量检索测试：本地嵌入式 Qdrant 的入库、检索、幂等、重置。"""

from deepresearch.config import Settings
from deepresearch.ingest import ingest_dir
from deepresearch.retriever import RetrievedChunk, VectorStore


def _store(tmp_path, name="qdrant"):
    cfg = Settings(
        qdrant_local_path=str(tmp_path / name),
        qdrant_collection="t",
        qdrant_url=None,
    )
    return VectorStore(cfg)


def test_index_and_search(tmp_path):
    store = _store(tmp_path)
    try:
        n = store.index(
            [
                RetrievedChunk(id="rag.md#0", text="RAG 是检索增强生成，先检索再生成。", source="rag.md"),
                RetrievedChunk(id="ft.md#0", text="微调是继续训练模型参数，改变模型行为。", source="ft.md"),
            ]
        )
        assert n == 2 and store.count() == 2

        hits = store.search("什么是检索增强生成？", k=1)
        assert len(hits) == 1
        assert hits[0].source == "rag.md"
        assert hits[0].score > 0.1
    finally:
        store.close()


def test_index_is_idempotent(tmp_path):
    store = _store(tmp_path)
    try:
        chunk = RetrievedChunk(id="dup#0", text="同样的内容重复写入。", source="dup.md")
        store.index([chunk])
        store.index([chunk])
        assert store.count() == 1
    finally:
        store.close()


def test_reset_clears_collection(tmp_path):
    store = _store(tmp_path)
    try:
        store.index([RetrievedChunk(id="a#0", text="内容。", source="a.md")])
        store.reset()
        assert store.count() == 0
    finally:
        store.close()


def test_search_on_empty_corpus_returns_empty(tmp_path):
    store = _store(tmp_path)
    try:
        assert store.search("任何问题") == []
    finally:
        store.close()


def test_ingest_dir_end_to_end(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# RAG\n\nRAG 通过检索外部文档增强生成质量。", encoding="utf-8")
    (docs / "b.md").write_text("# 微调\n\n微调通过继续训练改变模型行为。", encoding="utf-8")

    store = _store(tmp_path)
    try:
        stats = ingest_dir(str(docs), store=store)
        assert stats["files"] == 2
        assert stats["chunks"] >= 2
        hits = store.search("检索增强", k=1)
        assert hits and hits[0].source == "a.md"
    finally:
        store.close()
