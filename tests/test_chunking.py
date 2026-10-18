"""切块测试：空文档、短文档、段落打包、超长段落滑窗。"""

from deepresearch.chunking import chunk_text


def test_empty_text_returns_nothing():
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_one_chunk():
    chunks = chunk_text("这是一段很短的说明文字。")
    assert len(chunks) == 1
    assert chunks[0] == "这是一段很短的说明文字。"


def test_paragraphs_are_packed_under_limit():
    text = "\n\n".join("段落" + str(i) + "：" + "内容" * 30 for i in range(10))
    chunks = chunk_text(text, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # 每个原段落都出现在某个块里（不丢内容）
    joined = "\n".join(chunks)
    for i in range(10):
        assert f"段落{i}" in joined


def test_long_paragraph_is_windowed_with_overlap():
    text = "字" * 1500
    chunks = chunk_text(text, max_chars=600, overlap=80)
    assert len(chunks) == 3
    assert all(len(c) <= 600 for c in chunks)
    # 相邻窗口有 80 字符重叠
    assert chunks[0][-80:] == chunks[1][:80]
