"""MCP Server：把调研能力暴露给任何 MCP 客户端（Claude Desktop / Cursor）。

工具：
- index_status：查看当前索引片段数（毫秒级）
- search_docs：只检索本地文档，返回片段与来源（毫秒级）
- research：跑完整多 Agent 流水线，返回报告 + 引用覆盖率 + 计量（几十秒）

运行：
  python -m deepresearch.mcp_server            # stdio（桌面客户端默认）
  python -m deepresearch.mcp_server --http     # HTTP 传输，默认 127.0.0.1:8001

接入方式（Claude Desktop / Cursor）：在客户端的 MCP 配置里加一个 stdio server，
command 指向本项目的 .venv/Scripts/python（或 bin/python），args 为
"-m", "deepresearch.mcp_server"。
"""

from __future__ import annotations

import argparse
import logging
import uuid

from fastmcp import FastMCP

from .retriever import get_store
from .runner import run

logger = logging.getLogger(__name__)

mcp = FastMCP("DeepResearch")


@mcp.tool
def index_status() -> dict:
    """查看当前文档索引里有多少可检索片段。"""
    return {"indexed_chunks": get_store().count()}


@mcp.tool
def search_docs(query: str, top_k: int = 4) -> list[dict]:
    """检索本地文档库，返回最相关的片段与来源文件名（不生成报告，速度快）。"""
    chunks = get_store().search(query, k=max(1, min(top_k, 12)))
    return [
        {"source": c.source, "score": round(c.score, 3), "text": c.text}
        for c in chunks
    ]


@mcp.tool(timeout=300)
def research(question: str) -> dict:
    """跑一次完整调研（规划→检索→撰写→核验→审查），返回报告与质量指标。

    耗时通常 30-90 秒，调用方需允许较长超时。
    """
    result = run(question, thread_id=f"mcp-{uuid.uuid4().hex[:8]}", review=False)
    return {
        "report": result.get("report", ""),
        "citation_coverage": result.get("citation_coverage"),
        "invalid_citations": result.get("invalid_citations", []),
        "verdict_passed": result.get("verdict_passed"),
        "metrics": result.get("metrics", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepResearch MCP Server")
    parser.add_argument("--http", action="store_true", help="使用 HTTP 传输（默认 stdio）")
    parser.add_argument("--port", type=int, default=8001, help="HTTP 端口（默认 8001）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.http:
        mcp.run(transport="http", transport_kwargs={"host": "127.0.0.1", "port": args.port})
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
