"""图状态：整条流水线在节点之间传递的那个字典。

谁在用：graph.py 用它声明 `StateGraph(AgentState)` 的类型，nodes.py 里每个节点
只读自己关心的字段、只返回自己负责写入的字段。

设计要点：
- 字段保持细粒度，不把所有东西塞进一个大 messages 列表。这样每个字段基本只有
  一个写入者，checkpoint、调试、消融实验都简单得多。
- findings 用 `operator.add` 做追加式合并：多个 researcher 并行写入时谁都覆盖不了谁
  （Send 扇出能并行工作的前提）。其余字段都是「后写覆盖」，所以同一步只让一个节点写。
- `total=False`：字段不必一开始就齐全，节点只返回自己产出的增量。
"""

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    # ---- 输入 ----
    question: str                # 用户的调研问题
    sub_question: str            # Send 扇出后，单个 researcher 手里那一个子问题

    # ---- planner ----
    sub_questions: list[str]     # 拆出来的 2-4 个子问题

    # ---- researcher（并行写，靠 operator.add 合并）----
    findings: Annotated[list[dict], operator.add]  # 每项：{sub_question, text, sources}

    # ---- collect ----
    notes: list[str]             # 去重、按子问题排序并全局重编号后的笔记
    sources: list[dict]          # {"n", "source", "text"}：writer/verifier 认可的编号表

    # ---- writer ----
    report: str                  # markdown 报告
    revised: bool                # 是否已经按批评修订过

    # ---- verifier（程序化核验，不用 LLM）----
    citation_coverage: float     # 结论段落里「有有效引用」的占比
    invalid_citations: list[int] # 报告里引用了、但编号表里不存在的编号（编造）
    unsourced: list[str]         # 没有引用支撑的结论摘要（最多 10 条）

    # ---- human_gate（人工审核，HITL）----
    human_approved: bool         # True=批准；False=退回并带上意见

    # ---- critic ----
    critique: str                # 审稿意见（不通过时是一条可执行的修改要求）
    verdict_passed: bool         # critic 是否认可这一稿
    revisions: int               # critic 已经审查过几次（修订循环的封顶依据）
