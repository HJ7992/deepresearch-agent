"""节点工厂：每个工厂接收注入的聊天模型（researcher 还接收检索器），
返回 LangGraph 需要的 (state) -> dict 节点函数。

设计要点（面试话术）：
- planner/critic 用 StructuredCaller 结构化输出（带自动降级，见 structured.py）；
- researcher 先检索、再带编号资料作答——从 M2 起报告里的结论都应可溯源；
- verifier 是程序化核验（正则 + 编号校验 + 覆盖率），确定性、可测试，
  不依赖「让 LLM 自己检查自己」；
- researcher 在 M2 里顺序遍历子问题，M3 换成 Send 并行扇出时节点契约不变。
"""

from __future__ import annotations

import logging
import re

from .config import settings
from .prompts import CRITIC_SYSTEM, PLANNER_SYSTEM, RESEARCHER_SYSTEM, WRITER_SYSTEM
from .schemas import CriticVerdict, SubQuestions
from .state import AgentState
from .structured import StructuredCaller

logger = logging.getLogger(__name__)

# planner 最多拆出 4 个子问题，防止 token 开销失控
MAX_SUB_QUESTIONS = 4

# 报告里的引用标记，形如 [1]、[3]
CITATION_RE = re.compile(r"\[(\d+)\]")

# 少于这个长度的段落不算「结论」，不参与覆盖率统计（过滤标题、列表符号等）
MIN_CLAIM_CHARS = 20


def _text(message) -> str:
    """取 AIMessage 的文本；兼容部分厂商返回分块列表的情况。"""
    text = getattr(message, "text", None)
    return text if isinstance(text, str) and text else str(message.content)


def make_planner(llm):
    """规划节点：把问题拆成 2-4 个可独立回答的子问题。"""
    structured = StructuredCaller(llm, SubQuestions)

    def planner(state: AgentState) -> dict:
        result = structured.invoke(
            [("system", PLANNER_SYSTEM), ("human", state["question"])]
        )
        subqs = result.sub_questions[:MAX_SUB_QUESTIONS]
        logger.info("planner: 拆出 %d 个子问题", len(subqs))
        return {"sub_questions": subqs}

    return planner


def make_researcher(llm, retriever):
    """调研节点：逐个子问题检索资料，带编号作答；没有资料时如实说明。"""

    def researcher(state: AgentState) -> dict:
        notes: list[str] = []
        sources: list[dict] = []
        seen: dict[str, int] = {}  # chunk id -> 编号（跨子问题去重）

        for sq in state["sub_questions"]:
            chunks = retriever.search(sq) if retriever else []
            if chunks:
                parts = []
                for c in chunks:
                    if c.id not in seen:
                        seen[c.id] = len(sources) + 1
                        sources.append(
                            {"n": seen[c.id], "source": c.source, "text": c.text[:300]}
                        )
                    parts.append(f"[{seen[c.id]}] 来源：{c.source}\n{c.text}")
                human = f"子问题：{sq}\n\n资料片段：\n\n" + "\n\n".join(parts)
            else:
                human = f"子问题：{sq}\n\n（资料库中没有检索到相关内容）"
            reply = llm.invoke([("system", RESEARCHER_SYSTEM), ("human", human)])
            notes.append(f"## {sq}\n\n{_text(reply).strip()}")

        logger.info("researcher: %d 条笔记，%d 条来源", len(notes), len(sources))
        return {"notes": notes, "sources": sources}

    return researcher


def make_writer(llm):
    """撰写节点：把笔记汇总成带引用的报告；有批评意见时先按要求修订。"""

    def writer(state: AgentState) -> dict:
        critique = state.get("critique")
        notes = "\n\n".join(state["notes"])
        sources = state.get("sources", [])
        src_desc = (
            "\n".join(f"[{s['n']}] {s['source']}" for s in sources) or "（无可用来源）"
        )
        user = (
            f"原始问题：{state['question']}\n\n"
            f"可引用的来源编号：\n{src_desc}\n\n"
            f"调研笔记：\n{notes}"
        )
        if critique:
            user += f"\n\n审稿人否决了上一稿，请在本轮修订中解决这条批评：\n{critique}"
        reply = llm.invoke([("system", WRITER_SYSTEM), ("human", user)])
        report = _text(reply).strip()
        out: dict = {"report": report}
        if critique:
            out["revised"] = True
        logger.info("writer: 报告 %d 字符", len(report))
        return out

    return writer


def make_verifier(min_coverage: float | None = None):
    """核验节点（程序化，不用 LLM）：
    1) 统计结论段落中有有效引用的比例；
    2) 找出报告里引用了、但资料库里不存在的编号（编造引用）。

    阈值在这里只做计算，是否打回由 graph.route_after_critic 统一判断。
    """
    threshold = settings.citation_min_coverage if min_coverage is None else min_coverage

    def verifier(state: AgentState) -> dict:
        report = state.get("report", "")
        valid = {int(s["n"]) for s in state.get("sources", [])}

        claims: list[str] = []
        for para in report.split("\n\n"):
            p = para.strip()
            if not p or p.startswith("#"):
                continue  # 标题不算结论
            body = CITATION_RE.sub("", p).strip()
            # 去掉引用与列表符号后太短，说明是列表项/来源清单，不算独立结论
            if len(body) < MIN_CLAIM_CHARS:
                continue
            claims.append(p)

        cited, unsourced, invalid = 0, [], set()
        for p in claims:
            refs = {int(x) for x in CITATION_RE.findall(p)}
            bad = refs - valid
            invalid |= bad
            if refs - bad:
                cited += 1
            else:
                unsourced.append(p[:60])

        coverage = cited / len(claims) if claims else 1.0
        logger.info(
            "verifier: 覆盖率 %.0f%%（%d/%d 段，阈值 %.0f%%），无效引用：%s",
            coverage * 100, cited, len(claims), threshold * 100, sorted(invalid) or "无",
        )
        return {
            "citation_coverage": round(coverage, 3),
            "invalid_citations": sorted(invalid),
            "unsourced": unsourced[:10],
        }

    return verifier


def make_critic(llm):
    """审查节点：结构化判定通过/不通过；不通过时给一条具体批评。
    revisions 计数在此自增，作为修订循环的封顶依据。"""
    structured = StructuredCaller(llm, CriticVerdict)

    def critic(state: AgentState) -> dict:
        coverage = state.get("citation_coverage", 1.0)
        invalid = state.get("invalid_citations", [])
        verdict = structured.invoke(
            [
                ("system", CRITIC_SYSTEM),
                (
                    "human",
                    (
                        f"原始问题：{state['question']}\n\n"
                        f"程序化核验：引用覆盖率 {coverage:.0%}，"
                        f"不存在的引用编号：{invalid or '无'}\n\n"
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
