"""节点工厂：每个工厂接收依赖（模型 / 检索器），返回一个 (state) -> dict 的节点函数。

谁在用：graph.py 建图时调用这些工厂，把返回值交给 g.add_node()。

为什么用「工厂 + 闭包」而不是把模型写成全局变量：依赖从外面传进来，节点本身是
纯函数式的（进来一个 state，返回要更新的字段），测试时换成假模型就能离线跑。

几个值得留意的设计：
- researcher 不一次处理所有子问题：Send 扇出后每个任务只回答一个子问题，产出
  findings（用 operator.add 并行合并），这样检索和生成都能并行；
- collect 负责收尾：按子问题顺序归并 findings，来源按 chunk id 去重，并把各任务
  自己的局部编号（都从 1 开始）重映射成全局编号；
- human_gate 让人插进来：用 interrupt() 暂停、Command(resume=...) 恢复；退回时把
  意见写进 critique，路由自然打回 writer 修订。
"""

import logging
import re

from langgraph.types import interrupt

from .config import settings
from .prompts import CRITIC_SYSTEM, PLANNER_SYSTEM, RESEARCHER_SYSTEM, WRITER_SYSTEM
from .schemas import CriticVerdict, SubQuestions
from .state import AgentState
from .structured import StructuredCaller

logger = logging.getLogger(__name__)

# planner 最多拆出 4 个子问题：子问题越多，并行请求和 token 开销涨得越快
MAX_SUB_QUESTIONS = 4

# 报告里的引用标记，形如 [1]、[3]
CITATION_RE = re.compile(r"\[(\d+)\]")

# 去掉引用后仍不足这个长度的段落不算「结论」，不参与覆盖率统计
# （用来过滤标题、来源清单这类本来就不该带引用的行）
MIN_CLAIM_CHARS = 20

# 重编号时用的临时占位符，避免 [1]→[2] 之后又被 [2]→[3] 连锁替换
_PLACEHOLDER = "⟦{}⟧"


def _text(message) -> str:
    """取 AIMessage 的文本；兼容部分厂商返回分块列表的情况。"""
    text = getattr(message, "text", None)
    return text if isinstance(text, str) and text else str(message.content)


def make_planner(llm):
    """规划节点：把大问题拆成 2-4 个能独立回答的子问题。"""

    # 结构化调用器在建图时就绑好 schema，节点里只负责组装 messages
    structured = StructuredCaller(llm, SubQuestions)

    def planner(state: AgentState) -> dict:
        result = structured.invoke(
            [("system", PLANNER_SYSTEM), ("human", state["question"])]
        )
        # 模型偶尔会多拆几条，这里硬截断，别让并行扇出无限膨胀
        subqs = result.sub_questions[:MAX_SUB_QUESTIONS]
        logger.info("planner: 拆出 %d 个子问题", len(subqs))
        return {"sub_questions": subqs}

    return planner


def make_researcher(llm, retriever):
    """调研节点（Send 扇出后的单个任务）：只回答 state["sub_question"]。

    检索到的资料按局部编号 1..k 引用，全局编号留给 collect 统一分配。
    retriever 为 None（消融实验）时不检索，直接告诉模型没有资料。
    """

    def researcher(state: AgentState) -> dict:
        sq = state["sub_question"]
        chunks = retriever.search(sq) if retriever else []

        # 把检索结果整理成「编号 + 来源 + 正文」的提示片段
        sources: list[dict] = []
        parts: list[str] = []
        for i, c in enumerate(chunks, start=1):
            sources.append(
                # text 截断到 300 字符：片段太长会挤占上下文，反正原文就在库里
                {"n": i, "id": c.id, "source": c.source, "text": c.text[:300]}
            )
            parts.append(f"[{i}] 来源：{c.source}\n{c.text}")

        if parts:
            human = f"子问题：{sq}\n\n资料片段：\n\n" + "\n\n".join(parts)
        else:
            # 空手也要说实话，这是「不许编造」的第一步
            human = f"子问题：{sq}\n\n（资料库中没有检索到相关内容）"

        reply = llm.invoke([("system", RESEARCHER_SYSTEM), ("human", human)])
        logger.info("researcher[%s]: %d 条资料", sq[:20], len(sources))
        # 返回单元素列表：多个并行任务的 findings 由 operator.add 拼起来
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

    这里的难点：每个 researcher 的引用编号都是局部的（各自从 [1] 开始），
    合并后必须把笔记里的编号改写成全局编号，否则 writer 会引错来源、
    verifier 会把重复编号当成同一处资料。
    """

    def collect(state: AgentState) -> dict:
        # findings 是并行追加的，顺序不确定；先按子问题在 planner 里的顺序排好
        order = {q: i for i, q in enumerate(state.get("sub_questions", []))}
        findings = sorted(
            state.get("findings", []), key=lambda f: order.get(f["sub_question"], 0)
        )

        sources: list[dict] = []
        seen: dict[str, int] = {}  # chunk id -> 全局编号，用来给重复资料复用编号
        notes: list[str] = []

        for f in findings:
            # 本任务内的「旧编号 -> 全局编号」映射
            mapping: dict[int, int] = {}
            for s in f.get("sources", []):
                if s["id"] in seen:
                    # 同一块资料已被别的任务引入，复用已有编号
                    mapping[s["n"]] = seen[s["id"]]
                else:
                    n = len(sources) + 1
                    seen[s["id"]] = n
                    sources.append({"n": n, "source": s["source"], "text": s["text"]})
                    mapping[s["n"]] = n

            # 两段式替换：先把所有旧编号换成占位符，再统一换成新编号。
            # 直接逐个 replace 会连锁污染（把刚写好的 [2] 又改成 [3]）。
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
        # 明确告诉模型「只能引用这些编号」，这是它能守规矩的前提
        src_desc = (
            "\n".join(f"[{s['n']}] {s['source']}" for s in sources) or "（无可用来源）"
        )
        user = (
            f"原始问题：{state['question']}\n\n"
            f"可引用的来源编号：\n{src_desc}\n\n"
            f"调研笔记：\n{notes}"
        )
        if critique:
            # 第二轮及以后：把审稿人的意见一起塞进去
            user += f"\n\n审稿人否决了上一稿，请在本轮修订中解决这条批评：\n{critique}"

        reply = llm.invoke([("system", WRITER_SYSTEM), ("human", user)])
        report = _text(reply).strip()
        out: dict = {"report": report}
        if critique:
            # revised=True 只表示「这一稿是针对批评改过的」，供状态和测试观察
            out["revised"] = True
        logger.info("writer: 报告 %d 字符", len(report))
        return out

    return writer


def make_verifier(min_coverage: float | None = None):
    """核验节点（纯程序，不调用 LLM）：

    1) 统计「有有效引用的结论段落」占比，得到引用覆盖率；
    2) 找出报告里引用了、但编号表里不存在的编号（编造引用）。

    为什么不用 LLM 判断：同样的报告，程序判定结果永远一样——可复现、能进 CI。
    """
    threshold = settings.citation_min_coverage if min_coverage is None else min_coverage

    def verifier(state: AgentState) -> dict:
        report = state.get("report", "")
        # 本次允许出现的编号集合，来自 collect 整理好的 sources
        valid = {int(s["n"]) for s in state.get("sources", [])}

        # 按空行切段落，把标题和过短的行筛掉，剩下的才算「结论」
        claims: list[str] = []
        for para in report.split("\n\n"):
            p = para.strip()
            if not p or p.startswith("#"):
                continue  # 标题不算结论
            body = CITATION_RE.sub("", p).strip()
            if len(body) < MIN_CLAIM_CHARS:
                continue  # 列表项 / 来源清单不算独立结论
            claims.append(p)

        cited, unsourced, invalid = 0, [], set()
        for p in claims:
            refs = {int(x) for x in CITATION_RE.findall(p)}
            bad = refs - valid     # 编造的编号
            invalid |= bad
            if refs - bad:         # 至少有一个引用是有效的，这段就算「有据可查」
                cited += 1
            else:
                unsourced.append(p[:60])

        # 没有任何可统计段落时按 1.0 处理，避免误伤很短的报告
        coverage = cited / len(claims) if claims else 1.0
        logger.info(
            "verifier: 覆盖率 %.0f%%（%d/%d 段，阈值 %.0f%%），无效引用：%s",
            coverage * 100, cited, len(claims), threshold * 100, sorted(invalid) or "无",
        )
        return {
            "citation_coverage": round(coverage, 3),
            "invalid_citations": sorted(invalid),
            "unsourced": unsourced[:10],  # 只留前 10 条，够定位问题就行
        }

    return verifier


def make_human_gate(enabled: bool = False):
    """人工审核门：开启时 interrupt() 暂停执行，等 Command(resume=decision) 恢复。

    decision = {"approved": true/false, "comment": "..."}；退回时把意见写进
    critique，路由就会打回 writer 重写。关闭时直接放行（CI 里不会卡住）。
    """

    def human_gate(state: AgentState) -> dict:
        if not enabled:
            return {}  # 什么都不改，等同于透明节点

        # interrupt 把这几项抛给调用方（CLI 打印、API 返回给前端），然后整个图暂停；
        # 恢复时这里会重新执行，interrupt() 的返回值就是调用方给的 decision。
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
            # 意见直接写进 critique，writer 下一轮就会读到
            "critique": f"人工退回：{comment or '请按审核意见修改后重新提交'}",
        }

    return human_gate


def make_critic(llm):
    """审查节点：结构化判定这一稿能不能交付；不能就给一条具体批评。

    revisions 在这里自增，route_after_critic 用它做修订轮数的封顶。
    """
    structured = StructuredCaller(llm, CriticVerdict)

    def critic(state: AgentState) -> dict:
        coverage = state.get("citation_coverage", 1.0)
        invalid = state.get("invalid_citations", [])
        # 把程序化核验结果一并交给模型：让它「结合数据」判断，而不是只看文笔
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
