"""用「剧本假模型」测试真实流水线——完整 LangGraph 拓扑、零 API 调用。
同样的假模型模式让 CI 结果完全确定。"""

import sqlite3
import threading

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from deepresearch.config import Settings
from deepresearch.graph import build_graph
from deepresearch.llm import make_default_model
from deepresearch.retriever import RetrievedChunk


class FakeStructured:
    """按剧本返回结构化输出的假对象。"""

    def __init__(self, schema, queue, owner):
        self._schema, self._queue, self._owner = schema, queue, owner

    def invoke(self, messages):
        self._owner.structured_calls += 1
        return self._schema(**self._queue.pop(0))


class FakeLLM:
    """剧本假模型：聊天回复和结构化输出各排一个队列，按调用顺序弹出。

    并行 researcher 会并发调用 invoke，队列操作加锁保证线程安全；
    需要「按输入决定回复」时传 responder（例如让每个子问题得到不同答案）。
    """

    def __init__(self, replies=(), structured=(), responder=None):
        self.replies = list(replies)
        self.structured = list(structured)
        self.responder = responder
        self.chat_calls = 0
        self.structured_calls = 0
        self._lock = threading.Lock()

    def invoke(self, messages):
        with self._lock:
            self.chat_calls += 1
            if self.responder is not None:
                text = self.responder(messages)
            else:
                text = self.replies.pop(0)
        return AIMessage(content=text)

    def with_structured_output(self, schema, **kwargs):
        # 记录 method 参数，供兼容性回归测试断言
        self.last_method = kwargs.get("method")
        return FakeStructured(schema, self.structured, self)


class FakeRetriever:
    """检索桩：默认固定返回两条资料；也可按 query 返回不同资料。"""

    def __init__(self, chunks=None, by_query=None):
        self.chunks = chunks or [
            RetrievedChunk(id="rag.md#0", text="RAG 是检索增强生成。", source="rag.md"),
            RetrievedChunk(id="ft.md#0", text="微调会改变模型参数。", source="ft.md"),
        ]
        self.by_query = by_query or {}
        self.queries: list[str] = []

    def search(self, query, k=None):
        self.queries.append(query)
        for key, chunks in self.by_query.items():
            if key in query:
                return chunks
        return self.chunks


def _critic_fail_once_llm():
    """剧本：critic 第一轮否决、第二轮通过——正好走一次完整修订。"""
    return FakeLLM(
        replies=[
            "关于子问题1的笔记",   # researcher 第 1 个子问题
            "关于子问题2的笔记",   # researcher 第 2 个子问题
            "# 初稿 v1",           # writer 第 1 稿
            "# 修订稿 v2",         # writer 修订稿
        ],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},              # planner
            {"passed": False, "critique": "补充来源"},     # critic 第 1 轮
            {"passed": True, "critique": ""},             # critic 第 2 轮
        ],
    )


def test_full_loop_passes_after_one_revision():
    """critic 否决一次后修订通过：状态、调用次数全部符合预期。"""
    llm = _critic_fail_once_llm()
    app = build_graph(llm, retriever=FakeRetriever())
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["sub_questions"] == ["Q1", "Q2"]
    assert len(out["notes"]) == 2          # 追加式 reducer，两条笔记都在
    assert out["report"] == "# 修订稿 v2"
    assert out["verdict_passed"] is True
    assert out["revisions"] == 2           # critic 审查了两轮
    assert out["revised"] is True
    assert llm.chat_calls == 4             # 2 次调研 + 2 次撰写
    assert llm.structured_calls == 3       # 1 次规划 + 2 次审查
    # 默认端点上首选 function_calling（无需降级）
    assert llm.last_method == "function_calling"


def test_revision_loop_is_capped():
    """封顶验证：max_revisions=1 时 writer 最多跑两次（初稿 + 一轮修订），
    若有第三次调用会弹出空剧本而报错——等于自动验证了封顶。"""
    llm = FakeLLM(
        replies=["n1", "n2", "# v1", "# v2"],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": False, "critique": "不行"},
            {"passed": False, "critique": "还是不行"},
        ],
    )
    app = build_graph(llm, retriever=FakeRetriever(), max_revisions=1)
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["verdict_passed"] is False
    assert out["revisions"] == 2           # 审查两轮后硬停
    assert out["report"] == "# v2"         # 最新一稿仍然交付
    assert llm.chat_calls == 4             # 绝不会有第三次撰写


def test_no_revision_needed_when_critic_passes():
    """critic 一次通过：不进入修订，revised 字段不出现。"""
    llm = FakeLLM(
        replies=["n1", "n2", "# 好报告"],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(llm, retriever=FakeRetriever())
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["report"] == "# 好报告"
    assert out["revisions"] == 1
    assert "revised" not in out


def test_make_default_model_requires_api_key():
    """没配 key 时报错信息要能指路（而不是晦涩的堆栈）。"""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        make_default_model(Settings(openai_api_key=None))


class OnlyJsonModeLLM(FakeLLM):
    """模拟 DeepSeek 思考型模型：function_calling 报 400，只接受 json_mode。"""

    def with_structured_output(self, schema, **kwargs):
        if kwargs.get("method") == "function_calling":

            class _Rejected:
                @staticmethod
                def invoke(messages):
                    raise RuntimeError(
                        "Error code: 400 - Thinking mode does not support this tool_choice"
                    )

            return _Rejected()
        return super().with_structured_output(schema, **kwargs)


def test_falls_back_to_json_mode_when_tool_choice_unsupported():
    """复刻真实故障：端点拒绝 tool_choice 时自动降级到 json_mode，流程照跑。"""
    llm = OnlyJsonModeLLM(
        replies=["n1", "n2", "# 报告"],
        structured=[{"sub_questions": ["Q1", "Q2"]}, {"passed": True, "critique": ""}],
    )
    app = build_graph(llm, retriever=FakeRetriever())
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["report"] == "# 报告"
    assert out["verdict_passed"] is True
    assert llm.last_method == "json_mode"


def test_uncited_report_triggers_revision():
    """verifier 发现覆盖率不足时，即使 critic 通过也要打回重写。"""
    llm = FakeLLM(
        replies=[
            "n1", "n2",
            # 第 1 稿：一段没有任何引用的长结论
            "这是一个没有任何引用标记的长结论段落，用来触发覆盖率不足的打回。",
            # 修订稿：带引用
            "修订后的结论引用了资料 [1]，覆盖率达标。",
        ],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},   # critic 通过，但覆盖率 0
            {"passed": True, "critique": ""},   # 修订后再次通过
        ],
    )
    app = build_graph(llm, retriever=FakeRetriever())
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["revisions"] == 2            # 走了两轮
    assert out["citation_coverage"] == 1.0
    assert llm.chat_calls == 4              # 2 调研 + 2 撰写


def test_fabricated_citation_forces_revision():
    """引用了不存在的编号（编造来源）时，必须打回；达到轮数上限后 stops。"""
    llm = FakeLLM(
        replies=[
            "n1", "n2",
            "这段结论引用了不存在的编号 [9]，属于编造引用，长度足够被统计。",
            "修订稿仍然错误地引用 [9]，用来验证封顶后停止。",
        ],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(llm, retriever=FakeRetriever(), max_revisions=1)
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["invalid_citations"] == [9]
    assert out["revisions"] == 2            # 修订一轮后达到上限
    assert llm.chat_calls == 4


class PromptOnlyLLM:
    """两种原生模式都不支持，只能走 prompted 兜底（纯提示词 + 自己解析）。"""

    def with_structured_output(self, schema, **kwargs):
        raise RuntimeError("This response_format type is unavailable now")

    def invoke(self, messages):
        return AIMessage(content='```json\n{"sub_questions": ["Q1", "Q2"]}\n```')


def test_falls_back_to_prompted_mode():
    """最保守端点：原生模式全不支持时，用提示词 + JSON 解析兜底。"""
    from deepresearch.schemas import SubQuestions
    from deepresearch.structured import StructuredCaller

    caller = StructuredCaller(PromptOnlyLLM(), SubQuestions)
    out = caller.invoke([("human", "拆分问题")])
    assert out.sub_questions == ["Q1", "Q2"]


def test_non_compat_error_is_not_swallowed():
    """401 之类的非兼容性错误必须直接抛出，不能被降级逻辑吞掉。"""

    class AuthFailLLM(FakeLLM):
        def with_structured_output(self, schema, **kwargs):
            raise RuntimeError("Error code: 401 - invalid api key")

    app = build_graph(AuthFailLLM(), retriever=FakeRetriever())
    with pytest.raises(RuntimeError, match="401"):
        app.invoke({"question": "x"})


# ---------------------------------------------------------------------------
# 并行扇出、collect 重编号、HITL 暂停/恢复、跨实例 checkpoint 恢复
# ---------------------------------------------------------------------------

def _responder_by_subquestion(messages):
    """根据子问题返回不同答案，避免并行任务抢同一个回复队列。"""
    prompt = messages[-1][1]
    for sq in ("Q1", "Q2"):
        if sq in prompt:
            return f"结论：{sq} 的要点 [1]"
    return "结论 [1]"


def test_send_fan_out_merges_and_renumbers():
    """两个并行 researcher 的资料都从 [1] 编号，collect 必须重映射成 [1][2]。"""
    retriever = FakeRetriever(
        by_query={
            "Q1": [RetrievedChunk(id="a#0", text="资料A", source="a.md")],
            "Q2": [RetrievedChunk(id="b#0", text="资料B", source="b.md")],
        }
    )
    llm = FakeLLM(
        responder=_responder_by_subquestion,
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(llm, retriever=retriever)
    out = app.invoke({"question": "?"})

    # 笔记按子问题顺序合并，编号已全局化
    assert out["notes"][0].startswith("## Q1")
    assert "[1]" in out["notes"][0]
    assert out["notes"][1].startswith("## Q2")
    assert "[2]" in out["notes"][1]
    assert [s["source"] for s in out["sources"]] == ["a.md", "b.md"]


def test_collect_dedupes_shared_chunk():
    """两个子问题检索到同一块资料时，来源只保留一份，编号指向同一处。"""
    shared = [RetrievedChunk(id="same#0", text="同一块资料", source="same.md")]
    retriever = FakeRetriever(chunks=shared)
    llm = FakeLLM(
        responder=_responder_by_subquestion,
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(llm, retriever=retriever)
    out = app.invoke({"question": "?"})

    assert len(out["sources"]) == 1
    assert "[1]" in out["notes"][0] and "[1]" in out["notes"][1]


def test_hitl_approve_flow():
    """开启人工审核：图在 human_gate 暂停，批准后继续到 critic 并结束。"""
    llm = FakeLLM(
        replies=["n1", "n2", "# 报告 [1]"],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(
        llm, retriever=FakeRetriever(), checkpointer=InMemorySaver(), enable_review=True
    )
    cfg = {"configurable": {"thread_id": "h-approve"}}

    paused = app.invoke({"question": "?"}, cfg)
    assert "__interrupt__" in paused
    assert paused["report"].startswith("# 报告")

    done = app.invoke(Command(resume={"approved": True}), cfg)
    assert done["human_approved"] is True
    assert done["report"].startswith("# 报告")
    assert done["verdict_passed"] is True


def test_hitl_reject_triggers_revision():
    """人工退回：意见进入 critique，打回 writer 重写，然后再次等待审核。"""
    llm = FakeLLM(
        replies=["n1", "n2", "# 初稿 [1]", "# 修订稿 [1]"],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
            {"passed": True, "critique": ""},
        ],
    )
    app = build_graph(
        llm, retriever=FakeRetriever(), checkpointer=InMemorySaver(), enable_review=True
    )
    cfg = {"configurable": {"thread_id": "h-reject"}}

    first = app.invoke({"question": "?"}, cfg)
    assert "__interrupt__" in first

    second = app.invoke(
        Command(resume={"approved": False, "comment": "补充对比数据"}), cfg
    )
    assert "__interrupt__" in second          # 修订后再次等待人工
    assert second["human_approved"] is False
    assert second["report"] == "# 修订稿 [1]"

    third = app.invoke(Command(resume={"approved": True}), cfg)
    assert third["human_approved"] is True


def test_checkpoint_survives_restart(tmp_path):
    """模拟进程重启：新连接 + 新 app 用同一 thread_id 续跑，不重跑前端节点。"""
    db = str(tmp_path / "ckpt.sqlite")

    conn1 = sqlite3.connect(db, check_same_thread=False)
    saver1 = SqliteSaver(conn1)
    saver1.setup()
    llm1 = FakeLLM(
        replies=["n1", "n2", "# 报告 [1]"],
        structured=[
            {"sub_questions": ["Q1", "Q2"]},
            {"passed": True, "critique": ""},
        ],
    )
    app1 = build_graph(
        llm1, retriever=FakeRetriever(), checkpointer=saver1, enable_review=True
    )
    cfg = {"configurable": {"thread_id": "restart"}}

    first = app1.invoke({"question": "?"}, cfg)
    assert "__interrupt__" in first

    # 「重启」：新连接、新 app、新的假模型（只准备 critic 的那一次结构化调用）
    conn2 = sqlite3.connect(db, check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    saver2.setup()
    llm2 = FakeLLM(structured=[{"passed": True, "critique": ""}])
    app2 = build_graph(
        llm2, retriever=FakeRetriever(), checkpointer=saver2, enable_review=True
    )

    resumed = app2.invoke(Command(resume={"approved": True}), cfg)
    assert resumed["report"].startswith("# 报告")
    assert resumed["human_approved"] is True
    # 前端节点没有重跑：只发生了 1 次 LLM 调用（critic）
    assert llm2.chat_calls == 0
    assert llm2.structured_calls == 1
