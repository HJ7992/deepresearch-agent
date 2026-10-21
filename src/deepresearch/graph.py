"""把各个节点拼成一张 LangGraph 图——整个项目的骨架。

谁在用：runner.build_app() 用它构建真正可运行的图；tests/test_graph.py 只看它的拓扑。

流水线长这样：
    planner ──Send 扇出──► researcher × N（并行，各答一个子问题）
            ──► collect（去重 + 全局重编号）──► writer
            ──► verifier（程序化核验）──► human_gate（人工审核，可暂停）
            ──► critic ──不达标 / 被人工退回──► writer（修订轮数封顶）

三个要点：
- Send 是动态扇出：子问题有几个运行期才知道，静态边表达不了；
- 放行条件同时看 critic 结论、引用覆盖率、编造引用、人工审核结果；
- max_revisions 数的是「修订轮数」：writer 最多跑 1 + max_revisions 次，防止无限烧钱。
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .config import settings
from .nodes import (
    make_collect,
    make_critic,
    make_human_gate,
    make_planner,
    make_researcher,
    make_verifier,
    make_writer,
)
from .state import AgentState


def build_graph(
    model,
    retriever=None,
    checkpointer=None,
    max_revisions: int = 1,
    min_citation_coverage: float | None = None,
    enable_review: bool = False,
    enforce_citations: bool = True,
):
    """组装并编译图。

    参数含义：
    - model：聊天模型（只要能被节点 invoke）。测试里传剧本假模型；
    - retriever：有 search(query) 方法就行；传 None 时 researcher 会如实说「没有资料」；
    - checkpointer：状态存储，配合 thread_id 才能暂停/续跑；
    - max_revisions：critic 否决后允许的修订轮数；
    - min_citation_coverage：引用覆盖率门槛，None 表示读配置；
    - enable_review：是否插入人工审核（CI 里关掉，避免卡住）；
    - enforce_citations：False 仅用于消融实验，跳过覆盖率/编造引用的硬门槛。
    """
    # 门槛只在建图时算一次，路由函数里直接闭包引用
    threshold = (
        settings.citation_min_coverage
        if min_citation_coverage is None
        else min_citation_coverage
    )

    g = StateGraph(AgentState)

    # 每个节点工厂都返回一个 (state) -> dict 的函数，依赖在工厂里注入
    g.add_node("planner", make_planner(model))
    g.add_node("researcher", make_researcher(model, retriever))
    g.add_node("collect", make_collect())
    g.add_node("writer", make_writer(model))
    g.add_node("verifier", make_verifier(threshold))
    g.add_node("human_gate", make_human_gate(enable_review))
    g.add_node("critic", make_critic(model))

    def fan_out(state: AgentState):
        """把每个子问题变成一个独立的 Send 任务：几个子问题就几个并行 researcher。"""
        return [Send("researcher", {"sub_question": sq}) for sq in state["sub_questions"]]

    # ---- 主干边：一条直线走到底，唯一的回头路在 critic 后面 ----
    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", fan_out, ["researcher"])  # 动态扇出
    g.add_edge("researcher", "collect")   # 多个 researcher 都汇到 collect
    g.add_edge("collect", "writer")
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "human_gate")
    g.add_edge("human_gate", "critic")

    def route_after_critic(state: AgentState) -> str:
        """最后一道岔路：交付，还是打回 writer 重写。"""
        # 人工退回（human_approved 为 False）时，critic 说通过也不算过
        ok = (
            state.get("verdict_passed")
            and state.get("human_approved", True) is not False
        )
        if enforce_citations:
            # 硬门槛：覆盖率达标 + 没有编造的引用编号，两个都是「有据可查」的底线
            ok = (
                ok
                and state.get("citation_coverage", 1.0) >= threshold
                and not state.get("invalid_citations")
            )
        # 已经修满 max_revisions 轮就硬停，即使还不满意也把最新一稿交出去
        if ok or state.get("revisions", 0) > max_revisions:
            return END
        return "writer"

    g.add_conditional_edges("critic", route_after_critic, {"writer": "writer", END: END})
    return g.compile(checkpointer=checkpointer)


def main() -> str:
    """打印这张图的结构（Mermaid 文本）：python -m deepresearch.graph。

    不需要 API key，也不会调用模型：节点工厂只是把参数包成函数，画图时并不执行它们。
    """
    # model 传 None 就够：这里只关心节点和边怎么连，没有任何节点会被 invoke
    app = build_graph(None)
    mermaid = app.get_graph().draw_mermaid()
    print(mermaid)
    return mermaid


if __name__ == "__main__":
    main()
