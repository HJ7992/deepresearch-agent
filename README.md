# DeepResearch Agent

[![CI](https://github.com/HJ7992/deepresearch-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/HJ7992/deepresearch-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

基于 LangGraph 的多 Agent 深度调研助手：输入一个调研问题，系统自动完成
「拆解 → 检索 → 交叉验证 → 写报告 → 自我审查」，带引用核验、人工审核、
断点恢复、FastAPI 服务与 MCP 接入。

> 完整技术方案见 `../01-主项目技术方案.md`。

## 当前状态：M5（MCP 接入 + 交付收尾）

- [x] M0 仓库骨架、CI、docker-compose、离线可运行的 StateGraph（无 LLM 依赖）
- [x] M1 planner/researcher/writer/critic 接入真实模型（结构化输出、修订封顶、报告落盘）
- [x] M2 文档入库 + Qdrant 检索 + verifier 引用核验 + FastAPI 服务 + token/时延计量
- [x] M3 Send 并行扇出 + collect 去重重编号 + HITL 人工审核 + SQLite/Postgres 断点恢复
- [x] M4 20 题评测集 + 规则判定 + 两组消融 + 可复现评测脚本 + Langfuse 可选接入
- [x] M5 MCP Server（stdio/HTTP）+ 演示脚本 + 指标进 README

## 快速开始

```bash
# 需要 uv（https://docs.astral.sh/uv/）
uv venv --python 3.12
uv sync --extra dev

# 跑测试（全部离线，无需 API key：假模型 + 本地嵌入式向量库）
.venv/Scripts/python -m pytest -q        # Windows
# .venv/bin/python -m pytest -q          # macOS/Linux

# 文档入库（切块 + 嵌入 + 写入 Qdrant，默认本地嵌入式模式）
.venv/Scripts/python -m deepresearch.ingest data/docs

# 跑 hello-world 图
.venv/Scripts/python -m deepresearch.graph

# Lint
.venv/Scripts/python -m ruff check .
```

配置：复制 `.env.example` 为 `.env` 并填入模型 API key（任意 OpenAI 兼容端点，含国产模型）。

## 跑一次真实调研（M1 起）

```bash
# 先入库（M2 起报告会基于检索到的资料，并标注引用编号）
.venv/Scripts/python -m deepresearch.ingest data/docs

.venv/Scripts/python -m deepresearch.main "RAG 和微调应该怎么选？"
# 报告打印到终端，同时保存到 reports/ 目录；
# 同名 .json 记录 token、耗时、成本估算、引用覆盖率
```

## 作为服务运行（M2 起）

```bash
.venv/Scripts/python -m uvicorn deepresearch.api:app --port 8000
# 或：uvicorn deepresearch.api:app --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"question": "MCP 解决了什么问题？"}'
# -> {"run_id": "...", "status": "queued", ...}

curl http://127.0.0.1:8000/runs/<run_id>
# -> status / report / metrics / citation_coverage
```

Docker（需本机安装 Docker Desktop，本机尚未验证）：

```bash
docker compose up --build
# app(8000) + qdrant(6333)；服务端模式下自动使用 QDRANT_URL
```

## 网页界面（M5 起）

```bash
.venv/Scripts/python -m uvicorn deepresearch.api:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

单页原生 HTML/JS（无构建链，Markdown 渲染库本地内置）：

- 输入问题 → 提交 → 轮询进度 → 渲染 Markdown 报告与引用来源
- 展示引用覆盖率、tokens、耗时、审查轮次、编造引用（如有）
- 勾选「人工审核」后，报告生成即暂停，界面直接**批准 / 退回重写**
- 顶部显示索引就绪状态与片段数

## 人工审核与断点恢复（M3 起）

```bash
# 开启 HITL：跑到人工审核门会暂停，终端里批准或退回
.venv/Scripts/python -m deepresearch.main --review "RAG 和微调应该怎么选？"

# 进程退出/被杀之后，用同一个 thread_id 恢复（状态在 data/checkpoints.sqlite）
.venv/Scripts/python -m deepresearch.main --resume <thread_id>

# 想用 Postgres 存 checkpoint：装 extra 并配 DATABASE_URL
uv sync --extra postgres
# DATABASE_URL=postgresql://user:pass@localhost:5432/deepresearch
```

人工退回时，意见会写进 `critique` 并打回 writer 重写，然后再次等待审核；
即使人工批准，critic 判定不达标仍会触发修订——两道门槛相互独立。

## 作为 MCP Server 接入 Claude / Cursor（M5 起）

```bash
.venv/Scripts/python -m deepresearch.mcp_server          # stdio（桌面客户端默认）
.venv/Scripts/python -m deepresearch.mcp_server --http   # HTTP 传输，127.0.0.1:8001
```

客户端配置示例（Claude Desktop，路径换成你自己的）：

```json
{
  "mcpServers": {
    "deepresearch": {
      "command": "D:/zZZ/MyFiles/hermes-file/ai-agent-portfolio/deepresearch-agent/.venv/Scripts/python.exe",
      "args": ["-m", "deepresearch.mcp_server"]
    }
  }
}
```

暴露的工具：`index_status`（索引状态）、`search_docs`（毫秒级检索）、
`research`（几十秒的完整调研，返回报告与质量指标）。

## 常见问题

- **报错 `This response_format type is unavailable now` 或
  `Thinking mode does not support this tool_choice`**：当前端点对结构化输出的支持
  方式和默认的不同（DeepSeek 思考型模型常见）。项目内置自动降级链
  `function_calling → json_mode → prompted`，正常会自己落到可用模式；日志里能看到
  一条「自动降级」警告。想跳过失败尝试，可在 `.env` 设
  `DEEPRESEARCH_STRUCTURED_MODE=json_mode`。
- **没配 key 就运行**：会提示 `未配置模型 API key`，按 `.env.example` 建好 `.env` 即可。

## 评测结果（20 题评测集，规则判定）

| 模式 | 题数 | 任务成功率 | 关键词命中 | 引用覆盖率 | 编造引用率 | critic 通过率 | 平均 tokens | 平均耗时 |
|------|------|-----------|-----------|-----------|-----------|--------------|------------|----------|
| full（完整流水线） | 20 | 100% | 97% | 92% | 0% | 90% | 18,864 | 33.9s |
| no_retrieval（关检索，消融） | 6 | 0% | 74% | 0% | 50% | 0% | 11,642 | 29.4s |
| no_verify（关引用强制，消融） | 6 | 100% | 94% | 92% | 0% | 100% | 18,953 | 35.3s |

**怎么读这张表**：
- 完整流水线在 20 题上任务成功率 100%（规则判定：关键词命中 ≥0.5、覆盖率 ≥0.6、无编造引用）。
- **关检索 = 系统失效**：覆盖率归零、一半报告出现编造引用、critic 全部否决——检索是「可溯源」的前提。
- **关引用强制没有变差**：在本语料上，写作提示词 + critic 已足以约束引用质量，硬门槛
  的价值是**确定性兜底**（编造编号/低覆盖会被程序拦下并强制重写，单元测试覆盖了这些场景），
  而不是抬高平均分。这是如实结论，不是每个模块都必然带来指标提升。

> 复现：`.venv/Scripts/python eval/run_eval.py`（逐题落盘，消融加 `--mode`）。

## 架构（M5 实况）

```
planner ──Send 扇出──► researcher × N（并行检索）──► collect（去重+全局重编号）
      ──► writer（引用 [n]）──► verifier（程序化核验）──► human_gate（人工审核）
      ──► critic（LLM 审查）── 不达标/被退回 ──► writer（修订封顶）
配套：FastAPI（提交+轮询）· MCP Server（stdio/HTTP）· SQLite/Postgres checkpoint
      · token/时延计量 · 20 题评测 + 消融
```

