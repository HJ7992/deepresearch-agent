"""LLM 结构化输出的 schema（Pydantic 模型）。

谁在用：nodes.py 把 schema 交给 structured.StructuredCaller，让它按这个形状拿结果。

为什么要 schema 而不是自己解析自由文本：类型错误在节点边界就直接暴露（变成一次
可读的校验异常），不会把脏数据写进状态、留到下游才炸。
"""

from pydantic import BaseModel, Field


class SubQuestions(BaseModel):
    """planner 的输出：把大问题拆成几个能独立回答的子问题。"""

    sub_questions: list[str] = Field(
        min_length=1, max_length=4, description="2-4 个聚焦的、可独立回答的子问题"
    )


class CriticVerdict(BaseModel):
    """critic 的输出：这一稿能不能交付；不能就写明一条具体批评。"""

    passed: bool = Field(description="报告是否好到可以直接交付")
    critique: str = Field(default="", description="不通过时的一条可执行批评")
