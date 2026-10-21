"""图拓扑测试：不跑模型，只检查节点和边装对了没有。

行为测试（修订循环、HITL 暂停/恢复、引用重编号）在 tests/test_fake_graph.py，
那边用剧本假模型跑真实图；这里只守结构：增删节点、连错边、条件边漏了 END，
会先在这么小的文件里炸掉，而不是等某个旧线测试莫名失败。

为什么可以传 model=None：build_graph 只是把节点工厂包成函数塞进图里，
读拓扑 / 画图时没有任何节点被调用，因此不需要真模型、也不需要 API key。
"""

import deepresearch.graph as graph_module
from deepresearch.graph import build_graph

# 业务节点（LangGraph 还会自动加 __start__ / __end__，断言时一并算上）
NODES = {"planner", "researcher", "collect", "writer", "verifier", "human_gate", "critic"}


def _graph(**kwargs):
    """拿编译好的图结构；只读拓扑，不会 invoke，不花钱。"""
    return build_graph(None, **kwargs).get_graph()


def test_nodes_are_registered():
    """七个业务节点齐全，没有多余节点。"""
    assert set(_graph().nodes) == NODES | {"__start__", "__end__"}


def test_plain_edges():
    """固定边：一条主干，多个并行 researcher 都汇到 collect。"""
    edges = {(e.source, e.target) for e in _graph().edges if not e.conditional}
    assert edges == {
        ("__start__", "planner"),
        ("researcher", "collect"),
        ("collect", "writer"),
        ("writer", "verifier"),
        ("verifier", "human_gate"),
        ("human_gate", "critic"),
    }


def test_conditional_edges():
    """条件边：planner 扇出给 researcher；critic 决定「回 writer 修」还是结束。"""
    conditional = {(e.source, e.target) for e in _graph().edges if e.conditional}
    assert conditional == {
        ("planner", "researcher"),
        ("critic", "writer"),
        ("critic", "__end__"),
    }


def test_draw_mermaid_works():
    """README 里的架构图就是这段输出，必须能生成（不依赖模型或网络）。"""
    mermaid = _graph().draw_mermaid()
    assert "graph TD;" in mermaid
    for name in NODES:
        assert name in mermaid


def test_main_prints_mermaid(capsys):
    """python -m deepresearch.graph：打印结构图即可，全程不碰模型。"""
    mermaid = graph_module.main()
    printed = capsys.readouterr().out
    assert mermaid in printed
    assert "planner" in printed
