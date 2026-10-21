# 3 分钟演示录屏脚本

> 目的：对方点开仓库 30 秒能看懂，3 分钟能看完整个系统。
> 工具：OBS Studio 或 Windows 自带 Xbox Game Bar（Win+G）；终端字号调到 16–18。

## 录制前准备

```bash
.venv/Scripts/python -m deepresearch.ingest data/docs                  # 确保索引就绪
.venv/Scripts/python -m deepresearch.graph                             # 先跑一次，确认拓扑能打印
.venv/Scripts/python -m deepresearch.main "RAG 和微调应该怎么选？"       # 提前跑一遍，确认有报告
```

- 打开三个窗口：① 终端（项目目录）② 浏览器（GitHub 仓库页）③ 生成的报告文件
- 关闭无关通知；报告里保留「参考来源」章节作为引用证据

## 分镜

**0:00–0:15 一句话定位**
- 显示 README 顶部：多 Agent 调研助手，基于 LangGraph，带引用核验、人工审核、断点恢复
- 口述：「这是一个基于 LangGraph 的多 Agent 深度调研系统，重点解决两个问题：
  报告要有据可查，以及长任务要可控。」

**0:15–0:45 架构 30 秒**
- 切到 README 架构图（或终端里 `python -m deepresearch.graph` 的输出，粘到 mermaid.live），指着讲：
  planner 拆子问题 → Send 并行检索 → collect 去重重编号 → writer 写报告 →
  verifier 程序化核验 → critic 审查 → 人工审核门
- 顺带一句：「这张图不是手画的，是程序从真实图对象里打印出来的。」

**0:45–1:45 跑一次真实调研**
- 浏览器打开 http://127.0.0.1:8000（先 `uvicorn deepresearch.api:app --port 8000`）
- 输入问题 → 点「开始调研」→ 展示状态从「运行中」到「已完成」
- 展示：渲染后的报告、引用标记 `[1] [4]`、「参考来源」章节、指标 chips
  （引用覆盖率 / tokens / 耗时 / 审查轮次）
- 如果网页面板不方便，也可以退回终端演示：`ingest` + `main`，效果等价

**1:45–2:20 人工审核**
- 勾选「开启人工审核（HITL）」再提交一次
- 展示状态停在「等待人工审核」，输入退回意见「补充对比数据」→ 点「退回重写」
- 展示报告被重写后再次等待审核 → 点「批准」
- 口述：「退回意见进入 critique，writer 重写后重新审核；人工批准和 critic 通过是两道独立闸门。」

**2:20–2:50 API 与恢复**
- 启动 uvicorn（另开窗口）→ curl POST /research → 拿到 run_id → GET 轮询到 done
- 顺带说一句：「checkpoint 在 SQLite，进程重启用 --resume 续跑，已完成的节点不会重跑。」

**2:50–3:00 收尾**
- 切到 README 指标表：「20 题评测集，任务成功率 X%，平均覆盖率 Y%，单任务成本 Z。」
- 一句：「代码、评测脚本、演示语料都在仓库里，可以一键复现。」

## 录制后

- 视频传到 B 站/YouTube（不公开也行），链接放简历和 README
- 截图 3 张：终端运行、报告引用、API 返回 JSON，放 README 或简历附件
- 检查：视频里不能出现 API key、个人路径以外的敏感信息
