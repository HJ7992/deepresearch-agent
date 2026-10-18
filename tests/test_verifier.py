"""verifier 节点测试：覆盖率计算、无效引用识别、无结论段落时的默认值。"""

from deepresearch.nodes import make_verifier

SOURCES = [{"n": 1, "source": "a.md", "text": "资料一"}, {"n": 2, "source": "b.md", "text": "资料二"}]

# 两个「结论段落」，长度都超过 MIN_CLAIM_CHARS
CITED = "RAG 的核心是检索增强 [1]，它不改变模型参数，适合更新快的知识。"
UNCITED = "微调通过继续训练改变模型行为，适合固定格式和风格的任务。"


def _run(report, sources=SOURCES, min_cov=0.6):
    return make_verifier(min_cov)({"report": report, "sources": sources})


def test_half_claims_cited():
    out = _run(f"{CITED}\n\n{UNCITED}")
    assert out["citation_coverage"] == 0.5
    assert len(out["unsourced"]) == 1
    assert out["invalid_citations"] == []


def test_all_claims_cited():
    out = _run(f"{CITED}\n\n{CITED} [2]")
    assert out["citation_coverage"] == 1.0
    assert out["invalid_citations"] == []


def test_invalid_citation_detected():
    out = _run("这段结论只引用了不存在的编号 [9]，长度足够被统计。")
    assert out["invalid_citations"] == [9]
    assert out["citation_coverage"] == 0.0


def test_headings_and_source_list_ignored():
    report = "# 标题\n\n## 小节\n\n[1] a.md\n[2] b.md"
    out = _run(report)
    # 没有可统计的结论段落时覆盖率按 1.0 处理（不误伤短报告）
    assert out["citation_coverage"] == 1.0
    assert out["unsourced"] == []
