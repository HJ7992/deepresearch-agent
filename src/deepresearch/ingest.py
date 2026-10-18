"""文档入库 CLI：python -m deepresearch.ingest data/docs

把目录下所有 .md / .txt 切块、嵌入、写入 Qdrant（默认本地嵌入式模式）。
可重复执行：会先删集合重建，保证索引与文件一致。
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from .chunking import chunk_text
from .config import settings
from .retriever import RetrievedChunk, get_store


def ingest_dir(path: str, store=None) -> dict:
    """读取目录下所有文档并重建索引。返回 {files, chunks, collection, mode}。"""
    root = pathlib.Path(path)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在：{path}")

    files = sorted(
        p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt"} and p.is_file()
    )
    store = store or get_store()

    chunks: list[RetrievedChunk] = []
    for f in files:
        rel = str(f.relative_to(root)).replace("\\", "/")
        text = f.read_text(encoding="utf-8")
        for i, piece in enumerate(chunk_text(text)):
            chunks.append(RetrievedChunk(id=f"{rel}#{i}", text=piece, source=rel))

    store.reset()
    store.index(chunks)
    return {
        "files": len(files),
        "chunks": len(chunks),
        "collection": settings.qdrant_collection,
        "mode": "server" if settings.qdrant_url else "local",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="文档入库（切块 + 嵌入 + 写入 Qdrant）")
    parser.add_argument("path", nargs="?", default="data/docs", help="文档目录（默认 data/docs）")
    args = parser.parse_args()

    try:
        stats = ingest_dir(args.path)
    except FileNotFoundError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        f"[完成] {stats['files']} 个文件 → {stats['chunks']} 个块，"
        f"集合 {stats['collection']}（{stats['mode']} 模式）"
    )
    # 本地嵌入式模式在进程退出时释放文件锁，显式关闭可避免 __del__ 告警
    try:
        get_store().close()
    except Exception as exc:  # noqa: BLE001 — 关闭失败不影响入库结果
        logging.getLogger(__name__).debug("关闭向量库失败：%s", exc)


if __name__ == "__main__":
    main()
