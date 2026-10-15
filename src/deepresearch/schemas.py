"""LLM 结构化输出的 Pydantic 模型。

面试话术：结构化输出（with_structured_output）优于手工解析自由文本——
类型错误在节点边界就暴露，不会污染下游状态。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubQuestions(BaseModel):
    """planner 输出：问题拆解后的子问题列表。"""

    sub_questions: list[str] = Field(
        min_length=1, max_length=4, description="2-4 个聚焦的、可独立回答的子问题"
    )


class CriticVerdict(BaseModel):
    """critic 输出：通过与否 + 不通过时的一条具体批评。"""

    passed: bool = Field(description="报告是否好到可以直接交付")
    critique: str = Field(default="", description="不通过时的一条可执行批评")
