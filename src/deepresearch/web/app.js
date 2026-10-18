// DeepResearch 单页前端：提交调研 → 轮询状态 → 渲染报告 → 人工审核
// 全部用原生 JS，无构建链；Markdown 由本地 vendor 的 marked + DOMPurify 处理。

const $ = (id) => document.getElementById(id);

const STATE_LABEL = {
  queued: "排队中",
  running: "运行中…",
  awaiting_review: "等待人工审核",
  done: "已完成",
  failed: "失败",
};

let runId = null;
let pollTimer = null;
let lastStatus = null;

async function refreshHealth() {
  try {
    const res = await fetch("/health");
    const data = await res.json();
    if (data.status === "ok") {
      $("health").textContent = `索引就绪 · ${data.indexed_chunks} 个片段`;
      if (data.indexed_chunks === 0) {
        $("health").textContent += "（请先运行 python -m deepresearch.ingest data/docs）";
      }
    } else {
      $("health").textContent = "索引不可用";
    }
  } catch {
    $("health").textContent = "服务未连接";
  }
}

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

function renderReport(markdown) {
  if (!markdown) return;
  const html = marked.parse(markdown);
  $("report").innerHTML = DOMPurify.sanitize(html);
}

async function submitResearch() {
  const question = $("question").value.trim();
  if (question.length < 2) {
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

function poll() {
  stopPolling();
  pollTimer = setTimeout(tick, 1200);
}

async function tick() {
  if (!runId) return;
  try {
    const res = await fetch(`/runs/${runId}`);
    const run = await res.json();
    if (!res.ok) throw new Error(run.detail || "查询失败");

    lastStatus = run.status;
    const created = run.created_at ? `创建于 ${run.created_at}` : "";
    setStatus(run.status, created);
    renderMetrics(run);
    renderReport(run.report);

    if (run.status === "awaiting_review") {
      $("review-box").hidden = false;
      $("submit").disabled = false;
      return; // 等用户操作，不继续轮询
    }

    if (run.status === "done" || run.status === "failed") {
      $("submit").disabled = false;
      if (run.status === "failed" && run.error) {
        $("meta").textContent = run.error;
      }
      return;
    }
    poll();
  } catch (err) {
    $("meta").textContent = String(err.message || err);
    poll();
  }
}

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
    poll();
  } catch (err) {
    $("meta").textContent = String(err.message || err);
  } finally {
    $("approve").disabled = false;
    $("reject").disabled = false;
  }
}

$("submit").addEventListener("click", submitResearch);
$("question").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitResearch();
});
$("approve").addEventListener("click", () => submitReview(true));
$("reject").addEventListener("click", () => submitReview(false));

refreshHealth();
