"""图状态定义。

设计要点（面试话术）：状态保持细粒度，不要把所有东西塞进一个 messages
大列表——每个字段只有一个写入节点，checkpoint、消融实验和调试都简单得多。
notes 用 operator.add 追加式 reducer，多个 researcher 并行写入时互不覆盖
（为 M3 的 Send 扇出打底）。
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    question: str                # 输入：调研问题
    sub_questions: list[str]     # planner 产出：子问题列表
    sub_question: str            # Send 扇出时单个 researcher 拿到的子问题
    findings: Annotated[list[dict], operator.add]  # researcher 产出（并行合并）
    notes: list[str]             # collect 产出：去重、全局重编号后的笔记
    sources: list[dict]          # collect 产出：{"n", "source", "text"} 全局编号资料
    critique: str                # critic 产出：批评意见
    verdict_passed: bool         # critic 判定：报告是否通过
    human_approved: bool         # 人工审核结论（HITL 退回时为 False）
    revisions: int               # critic 已审查次数（修订循环封顶依据）
    revised: bool                # writer 是否已根据批评修订过
    report: str                  # writer 产出：最终报告
    citation_coverage: float     # verifier：有有效引用的结论段落占比
    invalid_citations: list[int]  # verifier：报告里不存在的引用编号（编造）
    unsourced: list[str]         # verifier：无引用结论的摘要（最多 10 条）
