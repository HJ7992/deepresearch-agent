# DeepResearch Agent

基于 LangGraph 的多 Agent 深度调研助手：输入一个调研问题，系统自动完成
「拆解 → 检索 → 交叉验证 → 写报告 → 自我审查」，带长期记忆、人工审核、
全链路观测与自建 MCP Server。

> 完整技术方案见 `../01-主项目技术方案.md`。

## 当前状态：M2（检索增强 + 引用核验 + 服务化）

- [x] M0 仓库骨架、CI、docker-compose、离线可运行的 StateGraph（无 LLM 依赖）
- [x] M1 planner/researcher/writer/critic 接入真实模型（结构化输出、修订封顶、报告落盘）
- [x] M2 文档入库 + Qdrant 检索 + verifier 引用核验 + FastAPI 服务 + token/时延计量
- [ ] M3 mem0 记忆 + checkpoint/HITL + Send 并行
- [ ] M4 Langfuse 观测 + ragas 评测 + 消融实验
- [ ] M5 MCP Server + 演示录屏

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

## 常见问题

- **报错 `This response_format type is unavailable now` 或
  `Thinking mode does not support this tool_choice`**：当前端点对结构化输出的支持
  方式和默认的不同（DeepSeek 思考型模型常见）。项目内置自动降级链
  `function_calling → json_mode → prompted`，正常会自己落到可用模式；日志里能看到
  一条「自动降级」警告。想跳过失败尝试，可在 `.env` 设
  `DEEPRESEARCH_STRUCTURED_MODE=json_mode`。
- **没配 key 就运行**：会提示 `未配置模型 API key`，按 `.env.example` 建好 `.env` 即可。

## 架构（M2 实况）

```
planner ──► researcher（Qdrant 检索，带编号资料）──► writer（引用 [n]）
                                                          │
                                                          ▼
                              verifier（程序化：覆盖率 + 无效编号）
                                                          │
                                                          ▼
                     critic（LLM 审查，结合核验数据）── 不达标 ──► writer（封顶重写）
配套：FastAPI 服务 · token/时延计量 · 本地嵌入式/服务端双模式 Qdrant
```

