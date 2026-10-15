# DeepResearch Agent

基于 LangGraph 的多 Agent 深度调研助手：输入一个调研问题，系统自动完成
「拆解 → 检索 → 交叉验证 → 写报告 → 自我审查」，带长期记忆、人工审核、
全链路观测与自建 MCP Server。

> 完整技术方案见 `../01-主项目技术方案.md`。

## 当前状态：M1（真实 LLM 节点 + 封顶修订循环）

- [x] M0 仓库骨架、CI、docker-compose、离线可运行的 StateGraph（无 LLM 依赖）
- [x] M1 planner/researcher/writer/critic 接入真实模型（结构化输出、修订封顶、报告落盘）
- [ ] M2 RAG 检索（Qdrant）+ verifier 引用核对
- [ ] M3 mem0 记忆 + checkpoint/HITL + Send 并行
- [ ] M4 Langfuse 观测 + ragas 评测 + 消融实验
- [ ] M5 MCP Server + 演示录屏

## 快速开始

```bash
# 需要 uv（https://docs.astral.sh/uv/）
uv venv --python 3.12
uv sync --extra dev

# 跑测试（M0 全部离线，无需 API key）
.venv/Scripts/python -m pytest -q        # Windows
# .venv/bin/python -m pytest -q          # macOS/Linux

# 跑 hello-world 图
.venv/Scripts/python -m deepresearch.graph

# Lint
.venv/Scripts/python -m ruff check .
```

配置：复制 `.env.example` 为 `.env` 并填入模型 API key（任意 OpenAI 兼容端点，含国产模型）。

## 跑一次真实调研（M1 起）

```bash
.venv/Scripts/python -m deepresearch.main "什么是检索增强生成？"
# 报告打印到终端，同时保存到 reports/ 目录
```

## 架构（目标态）

```
planner ──► researcher(s, 并行) ──► verifier ──► writer ──► critic ──┐
   ▲                                                                │
   └──────────── 人工审核(HITL) ◄──── 不达标 ◄───────────────────────┘
配套：mem0 记忆层 · Langfuse 观测 · checkpoint 恢复 · MCP Server
```
