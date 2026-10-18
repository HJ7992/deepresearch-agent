"""文本切块：按段落打包，超长段落滑窗切分。

设计要点（面试话术）：切块是 RAG 质量的第一道闸——切太碎丢上下文，
切太大检索不精准、还浪费 token。这里走「空行分段 → 段落打包到上限 →
超长段落滑窗兜底」，中文按字符窗口切，窗口间保留重叠避免语义断裂。
"""

from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 600
DEFAULT_OVERLAP = 80


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """超长段落按字符窗口切，相邻窗口保留 overlap 个字符的重叠。"""
    if len(text) <= max_chars:
        return [text]
    step = max(1, max_chars - overlap)
    return [text[i : i + max_chars] for i in range(0, len(text), step)]


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """把一篇文档切成若干块：段落优先，过长再滑窗；空文档返回空列表。"""
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paragraphs:
        pieces.extend(_split_long(p, max_chars, overlap))

    # 把小块按顺序打包到不超过上限；打包是「整块装」，不切句子
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 1 > max_chars:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks
