"""Streamlit 界面的测试。

分两层：
- ui_theme 里那些「数据进、HTML 出」的纯函数，直接断言字符串内容；
- 整个页面用 Streamlit 自带的 AppTest 跑一遍，确认没有异常（不需要 API key、
  不会真的发起调研）。
"""

import pathlib

from streamlit.testing.v1 import AppTest

from deepresearch import ui_theme as theme

APP_PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "deepresearch" / "streamlit_app.py"


# ---------------------------------------------------------------------------
# infer_stage：看 checkpoint 里已有的字段，推断现在走到哪
# ---------------------------------------------------------------------------

def test_infer_stage_walks_the_pipeline():
    assert theme.infer_stage({}) == "planner"
    assert theme.infer_stage({"sub_questions": ["Q1"]}) == "researcher"
    assert theme.infer_stage({"findings": [{}]}) == "collect"
    assert theme.infer_stage({"notes": ["n"]}) == "writer"
    assert theme.infer_stage({"report": "# 报告"}) == "verifier"
    assert theme.infer_stage({"revisions": 1}) == "critic"


def test_interrupt_pins_stage_to_human_gate():
    """停在人工审核时，无论字段走到哪，轨道都指在 human_gate。"""
    assert theme.infer_stage({"report": "# 报告", "revisions": 1}, interrupted=True) == "human_gate"


# ---------------------------------------------------------------------------
# stage_rail
# ---------------------------------------------------------------------------

def test_rail_marks_progress():
    rail = theme.stage_rail("writer", researcher_count=2)
    # 七个阶段都在，节点名也打出来（方便和 graph.py 对照）
    for node, _ in theme.STAGES:
        assert node in rail
    assert "检索 ×2" in rail
    # writer 之前（planner/researcher/collect）算完成，writer 自己算进行中
    assert rail.count('dr-stage done') == 3
    assert rail.count("dr-stage active") == 1


def test_rail_awaiting_and_finished():
    awaiting = theme.stage_rail("human_gate", awaiting=True)
    assert "dr-stage awaiting" in awaiting

    finished = theme.stage_rail("critic", finished=True)
    assert "active" not in finished
    assert finished.count("dr-stage done") == len(theme.STAGES)


# ---------------------------------------------------------------------------
# metric_band / 警示条
# ---------------------------------------------------------------------------

def test_metric_band_shows_coverage_and_floor():
    band = theme.metric_band(
        {
            "citation_coverage": 0.92,
            "revisions": 2,
            "sources": [{"n": 1}, {"n": 2}],
            "metrics": {"total_tokens": 12345, "llm_seconds": 33.9},
        }
    )
    assert "92%" in band
    assert "及格线 60%" in band
    assert "12,345" in band
    assert "33.9s" in band


def test_metric_band_flags_low_coverage():
    band = theme.metric_band({"citation_coverage": 0.3, "metrics": {}})
    assert "dr-fill low" in band
    assert "低于及格线" in band


def test_metric_band_without_report_yet():
    band = theme.metric_band({})
    assert "报告生成后统计" in band


def test_invalid_citation_warning():
    assert theme.invalid_citation_warning({"invalid_citations": []}) == ""
    warning = theme.invalid_citation_warning({"invalid_citations": [9]})
    assert "[9]" in warning


# ---------------------------------------------------------------------------
# source_ledger
# ---------------------------------------------------------------------------

def test_ledger_lists_sources_and_escapes_html():
    ledger = theme.source_ledger(
        [{"n": 1, "source": "rag.md", "text": "<script>alert(1)</script> 片段"}]
    )
    assert "[1]" in ledger
    assert "rag.md" in ledger
    # 片段文本必须被转义，不能把标签原样塞进页面
    assert "<script>" not in ledger
    assert "&lt;script&gt;" in ledger


def test_ledger_empty_state_points_at_ingest():
    ledger = theme.source_ledger([])
    assert "没有检索到资料" in ledger
    assert "deepresearch.ingest" in ledger


# ---------------------------------------------------------------------------
# brand_bar / review_notice
# ---------------------------------------------------------------------------

def test_brand_bar_states():
    assert "索引为空" in theme.brand_bar(0)
    assert "索引不可用" in theme.brand_bar(None)
    assert "1,024" in theme.brand_bar(1024)


def test_review_notice_mentions_both_actions():
    notice = theme.review_notice({"citation_coverage": 0.8})
    assert "80%" in notice
    assert "批准" in notice and "退回" in notice


# ---------------------------------------------------------------------------
# 整页冒烟：AppTest 真的把脚本跑一遍（不提交、不调用模型）
# ---------------------------------------------------------------------------

def test_app_renders_without_error():
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert not app.exception
    # 首页就应该有提问框和「开始调研」按钮
    assert app.text_area(key="question") is not None
    assert "开始调研" in [b.label for b in app.button]


def test_ask_form_lives_in_main_area():
    """回归：提问入口必须在主区。曾经只放在侧栏，侧栏一折叠页面就完全没法操作。"""
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    labels = [b.label for b in app.button]
    assert "开始调研" in labels
    assert "开始调研" not in [b.label for b in app.sidebar.button]
    # 示例问题也在主区，点了就能填进提问框
    assert any(label.startswith("RAG 和微调") for label in labels)


def test_home_lists_history():
    """首页要能看到历史调研，点一条就能回到那次结果。"""
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    app.session_state["runs"] = [
        {
            "thread_id": "t-history",
            "question": "上次问过的问题",
            "created": "10-21 10:00",
            "box": {"status": "done"},
        }
    ]
    app.run()
    assert not app.exception
    labels = [b.label for b in app.button]
    assert any("上次问过的问题" in label for label in labels)
    assert any("已完成" in label for label in labels)


def test_detail_view_has_home_button():
    """详情页左上角要有返回首页的入口。"""
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    app.session_state["runs"] = [
        {
            "thread_id": "t-detail",
            "question": "详情页问题",
            "created": "10-21 10:00",
            "box": {"status": "done"},
        }
    ]
    app.session_state["view"] = "t-detail"
    app.run()
    assert not app.exception
    labels = [b.label for b in app.button]
    assert app.button(key="go-home") is not None
    # 首页的「开始调研」此时不该出现（发起入口在首页）
    assert "开始调研" not in labels


def test_app_has_no_history_before_first_run():
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()
    assert app.session_state["runs"] == []
    assert app.session_state["view"] is None
