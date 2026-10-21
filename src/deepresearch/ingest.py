"""文档入库 CLI：把目录下的 .md / .txt 切块、嵌入、写进 Qdrant。

用法：python -m deepresearch.ingest data/docs

为什么每次先 reset：入库要能反复执行，索引必须和文件内容一致；先删集合重建，
就不会留下已经删掉的那篇文档的残余片段。
"""

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

    # 递归找文档；排序是为了让入库顺序确定（评测复现时很重要）
    files = sorted(
        p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt"} and p.is_file()
    )
    store = store or get_store()

    chunks: list[RetrievedChunk] = []
    for f in files:
        # chunk id 用「相对路径#序号」：同一文件重跑得到同一批 id，天然幂等
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
        # 目录写错是常见误用，给一行提示比抛堆栈友好
        print(f"[错误] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        f"[完成] {stats['files']} 个文件 → {stats['chunks']} 个块，"
        f"集合 {stats['collection']}（{stats['mode']} 模式）"
    )
    # 本地嵌入式模式要显式关闭，否则退出时 Qdrant 会打 __del__ 告警
    try:
        get_store().close()
    except Exception as exc:  # noqa: BLE001 — 关闭失败不影响入库结果
        logging.getLogger(__name__).debug("关闭向量库失败：%s", exc)


if __name__ == "__main__":
    main()
