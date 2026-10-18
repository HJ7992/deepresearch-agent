# LangGraph 基础

LangGraph 是用于构建有状态、多步骤 Agent 的编排框架。核心是把流程建模成状态图：节点是函数，边是流转关系，整个图共享一份状态。

## 核心概念

- **StateGraph**：以 TypedDict 定义状态，节点返回状态增量（dict），框架负责合并。
- **Reducer**：字段可声明合并方式，例如 `operator.add` 实现追加式列表，多个并行节点写入时不会互相覆盖。
- **条件边**：根据状态决定下一步走向，实现分支与循环，例如「审查不通过则回到撰写」。
- **Checkpointer**：按 thread_id 持久化每一步状态，支持中断恢复（进程重启后继续跑）与人工审核（interrupt）。
- **Send API**：把一个任务动态扇出成多个并行子任务，适合「一个问题拆成多个子问题并行调研」的 map-reduce 场景；结果通过 reducer 汇总。

## 版本注意事项

LangGraph 1.0 起，`langgraph.prebuilt.create_react_agent` 已废弃，预制 Agent 改为 `langchain.agents.create_agent`，定制方式从 hooks 改为 middleware（before_model / after_model 等）。网上大量教程仍是旧 API，迁移时应以官方 migration guide 为准。

## 为什么用它

相比自己写 while 循环，状态图把「控制流」显式化：分支、循环、并行、断点都能画出来，也便于测试单个节点。代价是学习曲线和额外的状态设计成本，简单线性流程用普通函数反而更直接。
