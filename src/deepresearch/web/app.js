// DeepResearch 单页前端：提交调研 → 轮询状态 → 渲染报告 → 人工审核。
// 全部用原生 JS，没有构建链；Markdown 由本地 vendor 目录里的 marked + DOMPurify 处理。

// 简写：document.getElementById
const $ = (id) => document.getElementById(id);

// 后端的任务状态 -> 界面上给人看的中文
const STATE_LABEL = {
  queued: "排队中",
  running: "运行中…",
  awaiting_review: "等待人工审核",
  done: "已完成",
  failed: "失败",
};

let runId = null;      // 当前任务的 id（后端返回）
let pollTimer = null;  // 轮询定时器，切任务时先清掉旧的

// 顶部索引状态：让人一眼看出「检索库是不是空的」
async function refreshHealth() {
  try {
    const res = await fetch("/health");
    const data = await res.json();
    if (data.status === "ok") {
      $("health").textContent = `索引就绪 · ${data.indexed_chunks} 个片段`;
      if (data.indexed_chunks === 0) {
        // 空索引是最常见的「跑出来没有引用」的原因，直接给命令
        $("health").textContent += "（请先运行 python -m deepresearch.ingest data/docs）";
      }
    } else {
      $("health").textContent = "索引不可用";
    }
  } catch {
    $("health").textContent = "服务未连接";
  }
}

// 更新状态徽标和右侧的小字（创建时间 / 错误信息）
function setStatus(status, extra = "") {
  const badge = $("status-badge");
  badge.textContent = STATE_LABEL[status] || status;
  badge.className = "badge " + (
    status === "running" ? "running" :
    status === "awaiting_review" ? "awaiting" :
    status === "done" ? "done" :
    status === "failed" ? "failed" : ""
  );
  $("meta").textContent = extra;
}

// 指标 chips：覆盖率 / 编造引用 / tokens / 耗时 / 审查轮次 / 来源数
function renderMetrics(run) {
  const m = run.metrics || {};
  const chips = [];
  if (run.citation_coverage != null) {
    chips.push(`引用覆盖率 <strong>${Math.round(run.citation_coverage * 100)}%</strong>`);
  }
  if (run.invalid_citations && run.invalid_citations.length) {
    chips.push(`编造引用 <strong>${run.invalid_citations.join(", ")}</strong>`);
  }
  if (m.total_tokens) chips.push(`tokens <strong>${m.total_tokens}</strong>`);
  if (m.llm_seconds != null) chips.push(`耗时 <strong>${m.llm_seconds}s</strong>`);
  if (run.revisions != null) chips.push(`审查轮次 <strong>${run.revisions}</strong>`);
  if (run.sources) chips.push(`来源数 <strong>${run.sources}</strong>`);
  $("metrics").innerHTML = chips
    .map((c) => `<span class="chip">${c}</span>`)
    .join("");
}

// 渲染 Markdown 报告。marked 负责转 HTML，DOMPurify 负责挡掉注入的脚本
// （报告内容来自模型，不能当可信 HTML 直接塞进页面）。
function renderReport(markdown) {
  if (!markdown) return;
  const html = marked.parse(markdown);
  $("report").innerHTML = DOMPurify.sanitize(html);
}

// 提交一次调研：清空上一轮界面，拿到 run_id 后开始轮询
async function submitResearch() {
  const question = $("question").value.trim();
  if (question.length < 2) {
    // 后端要求至少 2 个字符，这里先拦一下，省一次请求
    $("question").focus();
    return;
  }
  stopPolling();
  $("submit").disabled = true;
  $("review-box").hidden = true;
  $("report").innerHTML = "";
  $("metrics").innerHTML = "";
  $("run-panel").hidden = false;
  setStatus("queued");

  try {
    const res = await fetch("/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, review: $("review").checked }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "提交失败");
    runId = data.run_id;
    poll();
  } catch (err) {
    setStatus("failed", String(err.message || err));
    $("submit").disabled = false;
  }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

// 单次轮询更省事：每次 tick 结束时决定「再排一次」还是「停下」
function poll() {
  stopPolling();
  pollTimer = setTimeout(tick, 1200);
}

// 查一次任务状态，按状态决定继续轮询还是停手
async function tick() {
  if (!runId) return;
  try {
    const res = await fetch(`/runs/${runId}`);
    const run = await res.json();
    if (!res.ok) throw new Error(run.detail || "查询失败");

    const created = run.created_at ? `创建于 ${run.created_at}` : "";
    setStatus(run.status, created);
    renderMetrics(run);
    renderReport(run.report);

    if (run.status === "awaiting_review") {
      // 停下等人操作：轮询继续下去只会白跑请求
      $("review-box").hidden = false;
      $("submit").disabled = false;
      return;
    }

    if (run.status === "done" || run.status === "failed") {
      $("submit").disabled = false;
      if (run.status === "failed" && run.error) {
        $("meta").textContent = run.error;
      }
      return;
    }
    poll();  // 还在跑，继续等
  } catch (err) {
    // 网络抖动不该让界面卡死：提示一下，然后继续轮询
    $("meta").textContent = String(err.message || err);
    poll();
  }
}

// 提交人工审核结论；退回时可带一条意见（会变成 writer 的修改要求）
async function submitReview(approved) {
  if (!runId) return;
  $("approve").disabled = true;
  $("reject").disabled = true;
  try {
    const res = await fetch(`/runs/${runId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        comment: $("review-comment").value.trim(),
      }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || "审核提交失败");
    }
    $("review-box").hidden = true;
    $("review-comment").value = "";
    poll();  // 审核完图会继续跑（或再次暂停），重新开始轮询
  } catch (err) {
    $("meta").textContent = String(err.message || err);
  } finally {
    $("approve").disabled = false;
    $("reject").disabled = false;
  }
}

// ---- 事件绑定 ----
$("submit").addEventListener("click", submitResearch);
$("question").addEventListener("keydown", (e) => {
  // Ctrl/Cmd + Enter 提交，和大多数聊天框的手感一致
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitResearch();
});
$("approve").addEventListener("click", () => submitReview(true));
$("reject").addEventListener("click", () => submitReview(false));

// 页面加载完先报一次索引状态
refreshHealth();
