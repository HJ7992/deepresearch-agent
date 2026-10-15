"""用「剧本假模型」测试真实流水线——完整 LangGraph 拓扑、零 API 调用。
同样的假模型模式让 CI 结果完全确定。"""

import pytest
from langchain_core.messages import AIMessage

from deepresearch.config import Settings
from deepresearch.graph import build_graph
from deepresearch.llm import make_default_model


class FakeStructured:
    """按剧本返回结构化输出的假对象。"""

    def __init__(self, schema, queue, owner):
        self._schema, self._queue, self._owner = schema, queue, owner

    def invoke(self, messages):
        self._owner.structured_calls += 1
        return self._schema(**self._queue.pop(0))


class FakeLLM:
    """剧本假模型：聊天回复和结构化输出各排一个队列，按调用顺序弹出。"""

    def __init__(self, replies=(), structured=()):
        self.replies = list(replies)
        self.structured = list(structured)
        self.chat_calls = 0
        self.structured_calls = 0

    def invoke(self, messages):
        self.chat_calls += 1
        return AIMessage(content=self.replies.pop(0))

    def with_structured_output(self, schema):
        return FakeStructured(schema, self.structured, self)


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
    app = build_graph(llm)
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["sub_questions"] == ["Q1", "Q2"]
    assert len(out["notes"]) == 2          # 追加式 reducer，两条笔记都在
    assert out["report"] == "# 修订稿 v2"
    assert out["verdict_passed"] is True
    assert out["revisions"] == 2           # critic 审查了两轮
    assert out["revised"] is True
    assert llm.chat_calls == 4             # 2 次调研 + 2 次撰写
    assert llm.structured_calls == 3       # 1 次规划 + 2 次审查


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
    app = build_graph(llm, max_revisions=1)
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
    app = build_graph(llm)
    out = app.invoke({"question": "什么是 RAG？"})

    assert out["report"] == "# 好报告"
    assert out["revisions"] == 1
    assert "revised" not in out


def test_make_default_model_requires_api_key():
    """没配 key 时报错信息要能指路（而不是晦涩的堆栈）。"""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        make_default_model(Settings(openai_api_key=None))
