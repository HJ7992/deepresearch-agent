"""文本切块：先按空行分段，再把小段打包，超长段落用滑窗兜底切。

谁在用：ingest.py 入库前调用 chunk_text()；切出来的每块会变成一条检索资料。

为什么切块要认真做：它是 RAG 质量的第一道闸。
- 切太碎：每块丢上下文，检索回来的片段看不懂；
- 切太大：向量混了太多主题，检索不准，还白烧 token。

这里的三步策略：
1) 按空行分段（尊重作者本来的结构）；
2) 段落按顺序打包到不超过上限（整段装，不切断句子）；
3) 单段就超长时，按字符窗口切、窗口之间保留重叠，避免语义被切断在边界。
"""

import re

DEFAULT_MAX_CHARS = 600   # 单块上限（字符数）
DEFAULT_OVERLAP = 80      # 滑窗切分时相邻窗口的重叠字符数


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """超长段落按字符窗口切，相邻窗口保留 overlap 个字符的重叠。"""
    if len(text) <= max_chars:
        return [text]
    # step 至少要 1，否则 overlap >= max_chars 时会原地死循环
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

    # 1) 分段：连续空行（含带空格的空行）都算段落分隔
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    # 2) 超长段落先拆成能装下的片段
    pieces: list[str] = []
    for p in paragraphs:
        pieces.extend(_split_long(p, max_chars, overlap))

    # 3) 按顺序打包到上限，装不下就收一块重新开始
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 1 > max_chars:  # +1 是拼接时的换行
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks
