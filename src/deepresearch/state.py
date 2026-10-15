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
    notes: Annotated[list[str], operator.add]  # researcher 产出（只增不减）
    critique: str                # critic 产出：批评意见
    verdict_passed: bool         # critic 判定：报告是否通过
    revisions: int               # critic 已审查次数（修订循环封顶依据）
    revised: bool                # writer 是否已根据批评修订过
    report: str                  # writer 产出：最终报告
