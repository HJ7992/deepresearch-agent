"""节点工厂：每个工厂接收注入的聊天模型，返回 LangGraph 需要的
(state) -> dict 节点函数。

设计要点（面试话术）：
- planner/critic 用结构化输出，解析错误在节点边界就暴露，不会污染下游状态；
- researcher 在 M1 里顺序遍历子问题，M3 换成 LangGraph Send 并行扇出时，
  节点契约不变。
"""

from __future__ import annotations

import logging

from .prompts import CRITIC_SYSTEM, PLANNER_SYSTEM, RESEARCHER_SYSTEM, WRITER_SYSTEM
from .schemas import CriticVerdict, SubQuestions
from .state import AgentState

logger = logging.getLogger(__name__)

# planner 最多拆出 4 个子问题，防止 token 开销失控
MAX_SUB_QUESTIONS = 4


def _text(message) -> str:
    """取 AIMessage 的文本；兼容部分厂商返回分块列表的情况。"""
    text = getattr(message, "text", None)
    return text if isinstance(text, str) and text else str(message.content)


def make_planner(llm):
    """规划节点：把问题拆成 2-4 个可独立回答的子问题。"""
    structured = llm.with_structured_output(SubQuestions)

    def planner(state: AgentState) -> dict:
        result = structured.invoke(
            [("system", PLANNER_SYSTEM), ("human", state["question"])]
        )
        subqs = result.sub_questions[:MAX_SUB_QUESTIONS]
        logger.info("planner: 拆出 %d 个子问题", len(subqs))
        return {"sub_questions": subqs}

    return planner


def make_researcher(llm):
    """调研节点：逐个子问题产出笔记（M3 换成 Send 并行）。"""

    def researcher(state: AgentState) -> dict:
        notes = []
        for sq in state["sub_questions"]:
            reply = llm.invoke([("system", RESEARCHER_SYSTEM), ("human", sq)])
            notes.append(f"## {sq}\n\n{_text(reply).strip()}")
        logger.info("researcher: 产出 %d 条笔记", len(notes))
        return {"notes": notes}

    return researcher


def make_writer(llm):
    """撰写节点：把笔记汇总成报告；有批评意见时先按要求修订。"""

    def writer(state: AgentState) -> dict:
        critique = state.get("critique")
        notes = "\n\n".join(state["notes"])
        user = (
            f"原始问题：{state['question']}\n\n"
            f"调研笔记：\n{notes}"
        )
        if critique:
            user += (
                f"\n\n审稿人否决了上一稿，请在本轮修订中解决这条批评：\n{critique}"
            )
        reply = llm.invoke([("system", WRITER_SYSTEM), ("human", user)])
        report = _text(reply).strip()
        out: dict = {"report": report}
        if critique:
            out["revised"] = True
        logger.info("writer: 报告 %d 字符", len(report))
        return out

    return writer


def make_critic(llm):
    """审查节点：结构化判定通过/不通过；不通过时给一条具体批评。
    revisions 计数在此自增，作为修订循环的封顶依据。"""
    structured = llm.with_structured_output(CriticVerdict)

    def critic(state: AgentState) -> dict:
        verdict = structured.invoke(
            [
                ("system", CRITIC_SYSTEM),
                (
                    "human",
                    (
                        f"原始问题：{state['question']}\n\n"
                        f"报告：\n{state['report']}"
                    ),
                ),
            ]
        )
        revisions = state.get("revisions", 0) + 1
        logger.info("critic: 通过=%s 第 %d 次审查", verdict.passed, revisions)
        return {
            "critique": verdict.critique,
            "verdict_passed": verdict.passed,
            "revisions": revisions,
        }

    return critic
