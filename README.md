# DeepResearch Agent

[![CI](https://github.com/HJ7992/deepresearch-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/HJ7992/deepresearch-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

基于 LangGraph 的多 Agent 深度调研助手：输入一个调研问题，系统自动完成
「拆解 → 检索 → 并行调研 → 写报告 → 引用核验 → 自我审查 → 人工审核」，
并带断点恢复、FastAPI 服务、MCP 接入和可复现评测。

> 完整技术方案见 `../01-主项目技术方案.md`。

## 它想解决什么

Demo 级的「自动写报告」已经很常见，真正拿去用会卡在三件事上，这个项目主要就是把
这三件事做实：

1. **报告要有出处**：每条事实都标 `[n]`，`verifier` 用程序检查覆盖率、揪出编造的
   引用编号，不达标就打回重写——不是靠模型自己说「我很严谨」。
2. **长任务要可控**：几十秒的流程能中途暂停等人审核（HITL），进程挂了能用同一个
   `thread_id` 从断点续跑，已完成的节点不会重跑、不会重复烧钱。
3. **换模型不能崩**：结构化输出有 `function_calling → json_mode → prompted` 的自动
   降级链，DeepSeek 等国产端点也能直接跑，不用改代码。

## 能力清单

- **流程**：`planner` 拆子问题 → `Send` 并行扇出多个 `researcher` → `collect` 去重
  并全局重编号 → `writer` 写报告 → `verifier` 程序化核验 → `human_gate` 人工审核
  → `critic` 终审，不达标打回重写（轮数封顶）
- **检索**：文档切块 → 嵌入 → Qdrant（默认本地嵌入式，可切服务端）→ 相似度检索
- **质量**：引用覆盖率、编造引用检测、修订轮数上限、人工退回
- **持久化**：SQLite（默认）或 Postgres 存 checkpoint，支持暂停 / 恢复 / 跨进程续跑
- **接口**：CLI、HTTP 服务 + 单页网页、MCP Server（stdio / HTTP）
- **计量**：每次调研的 token、耗时、成本估算随报告落盘；可选 Langfuse 追踪
- **评测**：20 题固定评测集 + 规则判定 + 两组消融，脚本可复现

## 快速开始

```bash
# 需要 uv（https://docs.astral.sh/uv/）
uv venv --python 3.12
uv sync --extra dev

# 跑测试（全部离线，无需 API key：剧本假模型 + 本地嵌入式向量库）
.venv/Scripts/python -m pytest -q        # Windows；44 个用例
# .venv/bin/python -m pytest -q          # macOS/Linux

# 文档入库（切块 + 嵌入 + 写入 Qdrant，默认本地嵌入式模式）
.venv/Scripts/python -m deepresearch.ingest data/docs

# 看流水线的结构图（打印 Mermaid 文本，不需要 API key、不调用模型）
.venv/Scripts/python -m deepresearch.graph

# Lint
.venv/Scripts/python -m ruff check .
```

`python -m deepresearch.graph` 输出的是 Mermaid 图定义，想看图可以粘到
[mermaid.live](https://mermaid.live)。它读的就是真实图对象 `build_graph(...)` 的拓扑，
不是另外维护的一层桩代码——图变了，图就是这个。

配置：复制 `.env.example` 为 `.env` 并填入模型 API key（任意 OpenAI 兼容端点，含国产模型）。

## 跑一次真实调研

```bash
# 先入库：报告会基于检索到的资料，并标注引用编号
.venv/Scripts/python -m deepresearch.ingest data/docs

.venv/Scripts/python -m deepresearch.main "RAG 和微调应该怎么选？"
# 报告打印到终端，同时保存到 reports/；
# 同名 .json 记录 token、耗时、成本估算、引用覆盖率
```

## 作为服务运行

```bash
.venv/Scripts/python -m uvicorn deepresearch.api:app --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"question": "MCP 解决了什么问题？"}'
# -> {"run_id": "...", "status": "queued", ...}

curl http://127.0.0.1:8000/runs/<run_id>
# -> status / report / metrics / citation_coverage
```

接口用「提交 + 轮询」而不是同步阻塞：一次调研几十秒到几分钟，同步会占满连接、
超时不可控，也没法中途查进度。

Docker（需本机安装 Docker Desktop，本机尚未验证）：

```bash
docker compose up --build
# app(8000) + qdrant(6333)，服务端模式下自动使用 QDRANT_URL
```

## 网页界面

```bash
.venv/Scripts/python -m uvicorn deepresearch.api:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

单页原生 HTML/JS（无构建链，Markdown 渲染库本地内置）：

- 输入问题 → 提交 → 轮询进度 → 渲染 Markdown 报告与引用来源
- 展示引用覆盖率、tokens、耗时、审查轮次、编造引用（如有）
- 勾选「人工审核」后，报告生成即暂停，界面直接**批准 / 退回重写**
- 顶部显示索引就绪状态与片段数

## 人工审核与断点恢复

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
即使人工批准，critic 判定不达标仍会触发修订——两道闸门相互独立。

## 作为 MCP Server 接入 Claude / Cursor

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
`research`（几十秒的完整调研，返回报告与质量指标）。分开是因为客户端有超时约束：
只想查资料就不该触发一次完整调研。

## 架构

```
planner ──Send 扇出──► researcher × N（并行检索）──► collect（去重 + 全局重编号）
      ──► writer（引用 [n]）──► verifier（程序化核验）──► human_gate（人工审核）
      ──► critic（LLM 审查）── 不达标/被退回 ──► writer（修订封顶）
```

几个关键设计：

- **动态扇出**：子问题数量运行期才知道，所以用 `Send` 而不是静态边；
- **并行写入靠 reducer**：`findings` 用 `operator.add` 合并，多个 researcher 互不覆盖；
- **编号必须重映射**：每个 researcher 都从 `[1]` 开始，`collect` 用两段式占位符替换
  把局部编号改成全局编号，否则 writer 会引错来源；
- **两道路由闸门**：critic（质量观感）+ verifier（覆盖率 / 编造引用）+ 人工审核结论，
  全部满足才交付，否则打回 writer，且修订轮数封顶。

代码地图（按阅读顺序）：

| 文件 | 职责 |
|------|------|
| `config.py` | 环境变量 → 配置对象 |
| `state.py` | 图状态字段与 reducer 定义 |
| `graph.py` | 节点、边、条件边组装；`python -m deepresearch.graph` 打印拓扑 |
| `nodes.py` | 七个节点的实现（规划/调研/归并/撰写/核验/人工门/审查） |
| `structured.py` | 结构化输出的三级降级 |
| `chunking.py` / `embeddings.py` / `retriever.py` / `ingest.py` | 切块、向量化、Qdrant 存取、入库 CLI |
| `checkpointer.py` / `runner.py` | 状态持久化、对外入口（run / resume / get_state） |
| `api.py` / `web/` / `mcp_server.py` | HTTP 服务与网页、MCP 工具 |
| `usage.py` / `observability.py` | token 与耗时计量、可选 Langfuse 上报 |

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

## 常见问题

- **报错 `This response_format type is unavailable now` 或
  `Thinking mode does not support this tool_choice`**：当前端点对结构化输出的支持
  方式和默认的不同（DeepSeek 思考型模型常见）。项目内置自动降级链
  `function_calling → json_mode → prompted`，正常会自己落到可用模式；日志里能看到
  一条「自动降级」警告。想跳过失败尝试，可在 `.env` 设
  `DEEPRESEARCH_STRUCTURED_MODE=json_mode`。
- **没配 key 就运行**：会提示 `未配置模型 API key`，按 `.env.example` 建好 `.env` 即可。
- **报告里没有引用 / 覆盖率很低**：先看网页顶部的索引片段数和 `/health`；多半是还没
  运行 `ingest`，或者 `data/docs` 里的文档和问题不相关。

## 文档

- `docs/学习指南.md`：怎么把这份代码真正学成自己的（阅读顺序 + 动手练习）
- `docs/验收题.md`：按主题分组的口述验收题（附答案要点）
- `docs/demo-guide.md`：3 分钟演示录屏分镜
- `docs/改进计划.md`：还能继续做的改法（按收益/成本排过序）
- `docs/blog-langgraph-deepresearch.md`：面向外部读者的设计笔记
