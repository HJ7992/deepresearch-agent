"""Streamlit 界面：首页发起调研、看历史；详情页看进度、审阅报告、批准/退回。

启动：streamlit run src/deepresearch/streamlit_app.py

两个视图（用 session_state["view"] 切换，None 表示首页）：
- 首页：提问卡 + 示例问题 + 最近的调研。发起新调研后自动进入详情页；
- 详情页：左上角返回图标回到首页，下面是阶段轨道、指标、报告、来源台账。

布局原则（踩过的坑）：主流程必须在主区，不能只放在可折叠的侧栏里——否则侧栏
一折叠，页面上就没有任何可点的东西了。所以这里干脆不用侧栏。

为什么用「后台线程 + fragment 轮询」而不是直接调用：
- runner.run() 是同步阻塞几十秒的调用，直接在脚本里跑会把界面卡住；
- 所以把它丢进线程，主线程用 st.fragment(run_every=...) 每 1.5 秒读一次 checkpoint
  （runner.get_state），据此刷新阶段轨道、指标和报告；
- 进度不是假动画：阶段是看 checkpoint 里「哪个字段已经写进来了」推断的（见 state.py）。
"""

import threading
import time
import uuid
from datetime import datetime
from html import escape

import streamlit as st

# 注意：streamlit run 是把本文件当「顶层脚本」执行的（没有包上下文），
# 所以这里必须用绝对导入；写成 from . import runner 会直接 ImportError。
from deepresearch import runner
from deepresearch import ui_theme as theme
from deepresearch.config import settings
from deepresearch.retriever import get_store

REFRESH = "1.5s"  # 轮询 checkpoint 的间隔

# 示例问题贴着 data/docs 的语料，点了就能跑出有引用的结果
EXAMPLE_QUESTIONS = (
    "RAG 和微调应该怎么选？",
    "MCP 解决了什么问题？",
    "怎么评估一个 Agent 系统好不好？",
    "LangGraph 里状态和图是怎么组织的？",
)

# 首页历史列表里显示的状态文案
STATUS_TEXT = {
    "running": "运行中",
    "paused": "待审核",
    "done": "已完成",
    "failed": "失败",
}


# ---------------------------------------------------------------------------
# 读取数据：索引状态、checkpoint 快照
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def _index_count() -> int | None:
    """索引里有多少块可检索文档；读不到返回 None（不影响页面渲染）。"""
    try:
        return get_store().count()
    except Exception:  # noqa: BLE001 — 向量库异常不该让整个页面挂掉
        return None


@st.cache_resource(show_spinner=False)
def _probe_app():
    """只用来读 checkpoint 的图（从不 invoke）。整个进程复用一份，避免反复编译图。"""
    return runner.build_app(review=True)


def _snapshot(thread_id: str) -> tuple[dict, bool]:
    """读某个 thread 的最新状态。

    返回 (values, interrupted)：interrupted=True 表示图正停在人工审核门上
    （LangGraph 把中断信息放在 task.interrupts 里）。
    """
    if not thread_id or not settings.openai_api_key:
        return {}, False
    try:
        snapshot = _probe_app().get_state({"configurable": {"thread_id": thread_id}})
    except Exception:  # noqa: BLE001 — 状态读不到就当作还没有内容
        return {}, False
    interrupted = any(getattr(task, "interrupts", None) for task in (snapshot.tasks or ()))
    return dict(snapshot.values or {}), interrupted


# ---------------------------------------------------------------------------
# 启动任务：都在后台线程里跑，只往 box 这个 dict 里写结果
# ---------------------------------------------------------------------------

def _start_run(question: str, review: bool) -> None:
    """提交一次调研：立刻进入详情页，界面接着轮询进度。"""
    thread_id = f"ui-{uuid.uuid4().hex[:8]}"
    box: dict = {"status": "running", "started": time.time()}
    st.session_state.runs.insert(
        0,
        {
            "thread_id": thread_id,
            "question": question,
            "created": datetime.now().strftime("%m-%d %H:%M"),
            "box": box,
        },
    )
    st.session_state.view = thread_id  # 提交后直接看这次调研的进度

    def work() -> None:
        # 线程里只操作普通 dict，不碰任何 st.* 调用
        try:
            result = runner.run(question, thread_id=thread_id, review=review)
            box.update(result=result, status="paused" if result.get("paused") else "done")
        except Exception as exc:  # noqa: BLE001 — 后台任务出错要在界面上说清楚
            box.update(status="failed", error=str(exc))

    threading.Thread(target=work, daemon=True).start()


def _start_resume(thread_id: str, approved: bool, comment: str) -> None:
    """提交人工审核结论：批准继续终审，退回则打回 writer 重写。"""
    run = _find_run(thread_id)
    if run is None:
        return
    box = run["box"]
    box.pop("result", None)  # 丢掉上一轮结果，免得界面还显示旧报告
    box.update(status="running", started=time.time(), error=None)
    decision = {"approved": approved, "comment": comment}

    def work() -> None:
        try:
            result = runner.resume(thread_id, decision)
            box.update(result=result, status="paused" if result.get("paused") else "done")
        except Exception as exc:  # noqa: BLE001
            box.update(status="failed", error=str(exc))

    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------------------
# 会话：找一条记录、切换视图
# ---------------------------------------------------------------------------

def _find_run(thread_id: str | None) -> dict | None:
    if not thread_id:
        return None
    return next((r for r in st.session_state.runs if r["thread_id"] == thread_id), None)


def _open_run(thread_id: str) -> None:
    st.session_state.view = thread_id


def _go_home() -> None:
    st.session_state.view = None


def _init_state() -> None:
    st.session_state.setdefault("question", "")
    st.session_state.setdefault("review", False)
    st.session_state.setdefault("runs", [])
    st.session_state.setdefault("view", None)  # None = 首页

    # ?thread= 只在打开页面时生效一次：之后用户点「返回首页」，不该被它拉回详情页
    if not st.session_state.get("_qp_done"):
        thread = st.query_params.get("thread")
        if thread:
            if _find_run(thread) is None:
                # 历史列表里显示真实问题（从 checkpoint 里读），读不到才退回会话 id
                values, _ = _snapshot(thread)
                st.session_state.runs.append(
                    {
                        "thread_id": thread,
                        "question": values.get("question") or f"会话 {thread}",
                        "created": "",
                        "box": {"status": "done"},
                    }
                )
            st.session_state.view = thread
        st.session_state["_qp_done"] = True


# ---------------------------------------------------------------------------
# 首页：提问入口 + 历史
# ---------------------------------------------------------------------------

def _ask_form(form_key: str) -> None:
    """提问表单：唯一的发起入口。"""
    api_ready = bool(settings.openai_api_key)
    with st.form(form_key, clear_on_submit=False, border=False):
        question = st.text_area(
            "调研问题",
            key="question",
            height=104,
            placeholder="例如：RAG 和微调应该怎么选？",
            label_visibility="collapsed",
        )
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            review = st.toggle("生成后先人工审核", key="review")
        with right:
            submitted = st.form_submit_button(
                "开始调研",
                type="primary",
                use_container_width=True,
                disabled=not api_ready,
            )

    if submitted:
        text = (question or "").strip()
        if len(text) < 2:
            st.error("问题太短了，写清楚一点再提交。")
        else:
            _start_run(text, review)
            st.rerun()


def _fill_question(question: str) -> None:
    """示例问题按钮的回调：在 widget 实例化之前改它的值，避免 Streamlit 报错。"""
    st.session_state.question = question


def _examples() -> None:
    """示例问题，点一下填进上面的输入框。"""
    st.markdown('<div class="dr-side-label">或者试试这些</div>', unsafe_allow_html=True)
    for start in (0, 2):
        cols = st.columns(2)
        for offset, col in enumerate(cols):
            index = start + offset
            if index >= len(EXAMPLE_QUESTIONS):
                break
            example = EXAMPLE_QUESTIONS[index]
            col.button(
                example,
                key=f"example-{index}",
                use_container_width=True,
                on_click=_fill_question,
                args=(example,),
            )


def _history() -> None:
    """首页的历史列表：点一条就回到那次调研。"""
    runs = st.session_state.runs
    if not runs:
        return
    st.markdown('<div class="dr-side-label">最近的调研</div>', unsafe_allow_html=True)
    with st.container(key="history"):
        for run in runs[:8]:
            status = STATUS_TEXT.get(run["box"].get("status"), "")
            when = run.get("created") or ""
            label = f"{run['question']}\u3000·\u3000{status}"
            if when:
                label = f"{label}\u3000{when}"
            st.button(
                label,
                key=f"hist-{run['thread_id']}",
                use_container_width=True,
                on_click=_open_run,
                args=(run["thread_id"],),
            )


# ---------------------------------------------------------------------------
# 详情页：轨道、指标、审核卡、报告、来源台账
# ---------------------------------------------------------------------------

def _elapsed(box: dict) -> int:
    return max(0, int(time.time() - float(box.get("started") or time.time())))


def _note(status: str, box: dict, result: dict, awaiting: bool) -> str:
    """阶段轨道下面那行小字：这次跑到哪、为什么停下。"""
    if status == "failed":
        return "运行失败"
    if awaiting:
        return "停在人工审核 · 批准或退回后流程继续"
    if status == "done":
        verdict = "critic 通过" if result.get("verdict_passed") else "critic 未通过（已到修订上限）"
        sources = len(result.get("sources") or [])
        return f"已完成 · {verdict} · {sources} 条来源可查"
    return f"运行中 · 已用时 {_elapsed(box)}s · 每 {REFRESH} 刷新一次进度"


def _process_details(result: dict) -> None:
    """过程详情：拆出了哪些子问题、每个子问题找到多少资料。默认折叠。"""
    questions = result.get("sub_questions") or []
    findings = result.get("findings") or []
    if not questions and not findings:
        return
    with st.expander("过程详情 · 子问题与检索命中"):
        for question in questions:
            related = [f for f in findings if f.get("sub_question") == question]
            chunks = sum(len(f.get("sources") or []) for f in related)
            chars = sum(len(f.get("text") or "") for f in related)
            st.markdown(f"- **{question}** — 命中 {chunks} 块资料，笔记 {chars} 字")


def _render(thread_id: str, box: dict) -> None:
    """把一次调研画出来。"""
    values, interrupted = _snapshot(thread_id)
    # checkpoint 里有的字段（report/sources...）优先用最终结果再覆盖一层（带 metrics）
    result = {**values, **(box.get("result") or {})}
    status = box.get("status", "running")
    awaiting = interrupted or status == "paused"
    finished = status == "done"

    st.html(
        theme.stage_rail(
            theme.infer_stage(result, interrupted=awaiting),
            researcher_count=len(result.get("sub_questions") or []),
            finished=finished and not awaiting,
            awaiting=awaiting,
        )
    )
    st.markdown(
        f'<div class="dr-rail-note">{_note(status, box, result, awaiting)}</div>',
        unsafe_allow_html=True,
    )

    if status == "failed":
        st.error(f"这次没跑通：{box.get('error') or '未知错误'}")
        return

    report = result.get("report")
    if report:
        st.html(theme.metric_band(result))
        warning = theme.invalid_citation_warning(result)
        if warning:
            st.html(warning)

    if awaiting:
        st.html(theme.review_notice(result))
        comment = st.text_area(
            "退回意见（批准时可以留空）",
            key=f"comment-{thread_id}",
            height=76,
            placeholder="例如：补充 RAG 和微调的对比数据",
        )
        approve_col, reject_col = st.columns(2)
        if approve_col.button(
            "批准并交付", type="primary", use_container_width=True, key=f"ok-{thread_id}"
        ):
            _start_resume(thread_id, True, comment)
            st.rerun()
        if reject_col.button(
            "退回重写", use_container_width=True, key=f"rej-{thread_id}"
        ):
            _start_resume(thread_id, False, comment)
            st.rerun()

    if report:
        with st.container(key="reportcard"):
            st.markdown(report)
        st.html(theme.source_ledger(result.get("sources")))
        _process_details(result)
    elif status == "running":
        st.markdown(
            '<div class="dr-empty">正在拆问题、检索资料。报告写好后会出现在这里，'
            "上面的轨道会实时更新。</div>",
            unsafe_allow_html=True,
        )


@st.fragment(run_every=REFRESH)
def _live(thread_id: str, box: dict) -> None:
    """运行中的区域会自动刷新；一旦跑完就切回静态渲染，停止轮询。"""
    if box.get("status") != "running":
        st.rerun()
    _render(thread_id, box)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

def _home() -> None:
    st.html(theme.brand_bar(_index_count()))
    st.html(theme.intro())
    with st.container(key="askcard"):
        _ask_form("ask")
    _examples()
    _history()
    st.markdown(
        f'<div class="dr-footer">model · {escape(settings.model_name)}'
        f"　|　checkpoint · {escape(settings.checkpoint_db)}</div>",
        unsafe_allow_html=True,
    )


def _detail(run: dict) -> None:
    # 返回首页的图标放在左上角，紧挨品牌栏
    nav_col, brand_col = st.columns([1, 16], vertical_alignment="center")
    with nav_col, st.container(key="homebtn"):
        st.button(
            "",
            icon=":material/arrow_back:",
            type="tertiary",
            help="返回首页",
            key="go-home",
            on_click=_go_home,
        )
    with brand_col:
        st.html(theme.brand_bar(_index_count()))

    st.markdown(
        f'<div class="dr-current-q">正在看 · <strong>{escape(run["question"])}</strong></div>',
        unsafe_allow_html=True,
    )

    if run["box"].get("status") == "running":
        _live(run["thread_id"], run["box"])   # 运行中：自动刷新
    else:
        _render(run["thread_id"], run["box"])  # 跑完了：静态展示


def main() -> None:
    st.set_page_config(
        page_title="DeepResearch · 调研工作台",
        page_icon=":material/library_books:",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(theme.CSS, unsafe_allow_html=True)

    _init_state()

    if not settings.openai_api_key:
        st.warning(
            "还没配置模型 API key：把 .env.example 复制成 .env，"
            "填入 OPENAI_API_KEY 后重启本页。",
            icon=None,
        )

    run = _find_run(st.session_state.view)
    if run is None:
        _home()
    else:
        _detail(run)


if __name__ == "__main__":
    main()
