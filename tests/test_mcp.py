"""MCP Server 测试：用 fastmcp 的内存 Client 调用工具，不启动网络、不花钱。"""

import asyncio

from fastmcp import Client

from deepresearch import mcp_server
from deepresearch.retriever import RetrievedChunk


class FakeStore:
    """检索桩：只验证工具契约，不打开真实向量库。"""

    def count(self) -> int:
        return 3

    def search(self, query, k=None):
        return [
            RetrievedChunk(id="a#0", text="RAG 是检索增强生成。", source="a.md", score=0.93)
        ]


def _run(coro):
    return asyncio.run(coro)


def test_tools_are_exposed(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_store", lambda: FakeStore())

    async def go():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()

    tools = _run(go())
    names = {t.name for t in tools}
    assert {"index_status", "search_docs", "research"} <= names


def test_search_docs_returns_sources(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_store", lambda: FakeStore())

    async def go():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("search_docs", {"query": "RAG"})

    result = _run(go())
    text = str(result)
    assert "a.md" in text
    assert "RAG" in text


def test_index_status_reports_count(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_store", lambda: FakeStore())

    async def go():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("index_status", {})

    result = _run(go())
    assert "3" in str(result)
