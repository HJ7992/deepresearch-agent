"""节点工厂：每个工厂接收注入的依赖（模型/检索器），返回 LangGraph 需要的
(state) -> dict 节点函数。

M3 相比 M2 的变化：
- researcher 不再一次处理所有子问题，而是由 Send 扇出的单个任务只回答
  一个子问题，产出 findings（用 operator.add 并行合并）；
- 新增 collect 节点：按子问题顺序归并 findings，来源按 chunk id 去重，
  并把各任务自己的局部编号（都从 1 开始）重映射成全局编号；
- 新增 human_gate 节点：HITL 人工审核，用 interrupt() 暂停、Command(resume=...)
  恢复；退回时把意见写进 critique，回到 writer 修订。
"""

from __future__ import annotations

import logging
import re

from langgraph.types import interrupt

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

# 重编号时用的临时占位符，避免 [1]→[2] 又被 [2]→[3] 连锁替换
_PLACEHOLDER = "⟦{}⟧"


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
    """调研节点（Send 扇出后的单个任务）：只回答 state['sub_question']，
    检索到的资料按局部编号 1..k 引用，由 collect 统一重编号。"""

    def researcher(state: AgentState) -> dict:
        sq = state["sub_question"]
        chunks = retriever.search(sq) if retriever else []

        sources: list[dict] = []
        parts: list[str] = []
        for i, c in enumerate(chunks, start=1):
            sources.append(
                {"n": i, "id": c.id, "source": c.source, "text": c.text[:300]}
            )
            parts.append(f"[{i}] 来源：{c.source}\n{c.text}")

        if parts:
            human = f"子问题：{sq}\n\n资料片段：\n\n" + "\n\n".join(parts)
        else:
            human = f"子问题：{sq}\n\n（资料库中没有检索到相关内容）"

        reply = llm.invoke([("system", RESEARCHER_SYSTEM), ("human", human)])
        logger.info("researcher[%s]: %d 条资料", sq[:20], len(sources))
        return {
            "findings": [
                {
                    "sub_question": sq,
                    "text": _text(reply).strip(),
                    "sources": sources,
                }
            ]
        }

    return researcher


def make_collect():
    """归并节点：按子问题顺序合并并行结果，来源去重并全局重编号。

    难点：每个 researcher 的引用编号都是局部的（都从 [1] 开始），
    合并后必须把笔记里的编号改写成全局编号，否则 verifier 会把它们误判为
    重复或编造引用。用两段式占位符替换避免连锁替换。
    """

    def collect(state: AgentState) -> dict:
        order = {q: i for i, q in enumerate(state.get("sub_questions", []))}
        findings = sorted(
            state.get("findings", []), key=lambda f: order.get(f["sub_question"], 0)
        )

        sources: list[dict] = []
        seen: dict[str, int] = {}  # chunk id -> 全局编号
        notes: list[str] = []

        for f in findings:
            mapping: dict[int, int] = {}
            for s in f.get("sources", []):
                if s["id"] in seen:
                    mapping[s["n"]] = seen[s["id"]]
                else:
                    n = len(sources) + 1
                    seen[s["id"]] = n
                    sources.append({"n": n, "source": s["source"], "text": s["text"]})
                    mapping[s["n"]] = n

            text = f["text"]
            for old, new in mapping.items():
                text = text.replace(f"[{old}]", _PLACEHOLDER.format(new))
            for new in set(mapping.values()):
                text = text.replace(_PLACEHOLDER.format(new), f"[{new}]")
            notes.append(f"## {f['sub_question']}\n\n{text}")

        logger.info("collect: %d 条笔记，去重后 %d 条来源", len(notes), len(sources))
        return {"notes": notes, "sources": sources}

    return collect


def make_writer(llm):
    """撰写节点：把笔记汇总成带引用的报告；有批评意见时先按要求修订。"""

    def writer(state: AgentState) -> dict:
        critique = state.get("critique")
        notes = "\n\n".join(state.get("notes", []))
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
            if len(body) < MIN_CLAIM_CHARS:
                continue  # 列表项/来源清单不算独立结论
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


def make_human_gate(enabled: bool = False):
    """人工审核门：开启时 interrupt() 暂停执行，等待 Command(resume=decision)。

    decision = {"approved": true/false, "comment": "..."}；退回时把意见写入
    critique，路由会把流程打回 writer。关闭时直接放行（不影响 CI）。
    """

    def human_gate(state: AgentState) -> dict:
        if not enabled:
            return {}
        decision = interrupt(
            {
                "report": state.get("report", ""),
                "citation_coverage": state.get("citation_coverage"),
                "invalid_citations": state.get("invalid_citations", []),
            }
        )
        if isinstance(decision, dict) and decision.get("approved"):
            logger.info("human_gate: 人工通过")
            return {"human_approved": True}

        comment = decision.get("comment", "") if isinstance(decision, dict) else ""
        logger.info("human_gate: 人工退回（%s）", comment or "无意见")
        return {
            "human_approved": False,
            "critique": f"人工退回：{comment or '请按审核意见修改后重新提交'}",
        }

    return human_gate


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
