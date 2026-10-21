"""Streamlit 界面的视觉层：配色与字体变量、全局 CSS，以及几个拼 HTML 的纯函数。

为什么单独一层：streamlit_app.py 只负责「什么时候显示什么」，颜色、间距、卡片形状
全部收在这里。这些函数只接收数据、返回 HTML 字符串，不导入 streamlit，
所以可以直接单元测试（见 tests/test_streamlit_app.py）。

设计取向：调研产物天然是「报告 + 编号来源」，所以整体做成一张档案台——
纸白底、墨色字、靛蓝作主色，标题用衬线（文献气质），数字用等宽（数据感）。
唯一的强调色留给「等待人工审核」，因为它才是需要人动手的地方。
"""

import html

# ---- 调色板（改颜色只改这里）----
PAPER = "#FAFAF7"       # 页面底色：偏冷的纸白
CARD = "#FFFFFF"        # 卡片
INK = "#16202C"         # 主文字：墨
INK_SOFT = "#5A6673"    # 次要文字
RULE = "#E2E1DB"        # 分隔线
INDIGO = "#2C4A78"      # 主色：靛蓝墨
INDIGO_SOFT = "#EDF1F7"
BRASS = "#A2782B"       # 等待人工审核
GREEN = "#2C6A56"       # 通过 / 达标
RUST = "#9B3B2E"        # 编造引用 / 失败

# ---- 流水线阶段：顺序与 graph.py 里的节点一一对应 ----
# (节点名, 中文标签)
STAGES = (
    ("planner", "规划"),
    ("researcher", "检索"),
    ("collect", "归并"),
    ("writer", "撰写"),
    ("verifier", "核验"),
    ("human_gate", "审核"),
    ("critic", "审查"),
)
STAGE_NAMES = tuple(name for name, _ in STAGES)

# 引用覆盖率及格线，与 config 里的默认值一致，画刻度用
COVERAGE_FLOOR = 0.6

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {{
  --paper: {PAPER};
  --card: {CARD};
  --ink: {INK};
  --ink-soft: {INK_SOFT};
  --rule: {RULE};
  --indigo: {INDIGO};
  --indigo-soft: {INDIGO_SOFT};
  --brass: {BRASS};
  --green: {GREEN};
  --rust: {RUST};
  --serif: "Noto Serif SC", "Songti SC", SimSun, serif;
  --sans: "Inter", "Noto Sans SC", -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  --mono: "IBM Plex Mono", "JetBrains Mono", ui-monospace, Consolas, monospace;
}}

/* ---------- 页面骨架 ---------- */
html, body, [data-testid="stAppViewContainer"] {{
  background: var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15px;
}}
[data-testid="stHeader"] {{ background: transparent; }}
/* 隐藏 Streamlit 自带的菜单、Deploy 按钮和页脚，避免和产品顶栏打架 */
#MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none; }}
[data-testid="stSidebar"] {{
  background: #F3F2ED;
  border-right: 1px solid var(--rule);
}}
.block-container {{
  max-width: 1080px;
  padding-top: 1.6rem;
  padding-bottom: 4rem;
}}
h1, h2, h3, h4 {{ font-family: var(--serif); letter-spacing: 0; }}
a {{ color: var(--indigo); }}

/* ---------- 表单控件 ---------- */
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {{
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: 8px;
  color: var(--ink);
  font-family: var(--sans);
  font-size: 0.95rem;
  line-height: 1.6;
  padding: 0.7rem 0.75rem;
}}
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus {{
  border-color: var(--indigo);
  box-shadow: 0 0 0 3px rgba(44, 74, 120, 0.12);
}}
button:focus-visible, [role="button"]:focus-visible {{
  outline: 2px solid var(--indigo);
  outline-offset: 2px;
}}

/* 按钮。Streamlit 的 testid 是 stBaseButton-<kind>，kind 会拼成 secondary /
   secondaryFormSubmit / primary / primaryFormSubmit，所以用 ^= 前缀匹配；
   主级规则放后面，靠顺序压过次级（同级 specificity 时后者生效）。 */
button[data-testid^="stBaseButton-secondary"] {{
  background: var(--card);
  border: 1px solid var(--rule);
  border-radius: 8px;
  color: var(--ink);
  font-family: var(--sans);
  font-weight: 500;
  box-shadow: none;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}}
button[data-testid^="stBaseButton-secondary"]:hover {{
  background: var(--indigo-soft);
  border-color: var(--indigo);
  color: var(--indigo);
}}
button[data-testid^="stBaseButton-primary"] {{
  background: var(--indigo);
  border: 1px solid var(--indigo);
  border-radius: 8px;
  color: #fff;
  font-family: var(--sans);
  font-weight: 500;
}}
button[data-testid^="stBaseButton-primary"]:hover {{
  background: #243D64;
  border-color: #243D64;
  color: #fff;
}}
/* 兜底：老版本按钮带 kind 属性、不带 data-testid */
button[kind="primary"] {{
  background: var(--indigo);
  border-color: var(--indigo);
  color: #fff;
}}

/* 展开区与提示条 */
[data-testid="stExpander"] details {{
  border: 1px solid var(--rule);
  border-radius: 10px;
  background: var(--card);
}}
[data-testid="stAlert"] {{ border-radius: 10px; }}

/* ---------- 顶栏：品牌 + 索引状态 ---------- */
.dr-brandbar {{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 22px;
}}
.dr-brand {{ display: flex; align-items: center; gap: 12px; }}
.dr-mark {{
  width: 30px; height: 30px;
  border: 1.5px solid var(--indigo);
  border-radius: 4px;
  position: relative;
  flex: none;
}}
.dr-mark::after {{
  content: "";
  position: absolute;
  inset: 5px;
  background: repeating-linear-gradient(
    -45deg, var(--indigo) 0 1.5px, transparent 1.5px 5px
  );
  opacity: 0.85;
}}
.dr-title {{ font-family: var(--serif); font-size: 20px; font-weight: 600; line-height: 1.2; }}
.dr-sub {{
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-soft);
  text-transform: uppercase;
  margin-top: 3px;
}}
.dr-index {{
  font-family: var(--mono);
  font-size: 12px;
  color: var(--ink-soft);
  text-align: right;
  line-height: 1.5;
}}
.dr-index strong {{ color: var(--ink); font-weight: 500; }}
.dr-index .dr-dot {{
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: var(--green); margin-right: 6px; vertical-align: 1px;
}}
.dr-index .dr-dot.gray {{ background: #B4B8BC; }}
.dr-index .dr-dot.rust {{ background: var(--rust); }}

/* ---------- 阶段轨道（签名元素：直接映射图里的节点） ---------- */
.dr-rail {{
  display: flex;
  align-items: flex-start;
  gap: 0;
  overflow-x: auto;
  padding: 2px 0 14px;
  margin-bottom: 4px;
  scrollbar-width: thin;
}}
.dr-stage {{
  flex: 1 0 auto;
  min-width: 92px;
  position: relative;
  padding-top: 16px;
  text-align: left;
}}
.dr-stage::before {{  /* 连线 */
  content: "";
  position: absolute;
  top: 5px; left: 0; right: 0;
  height: 1px;
  background: var(--rule);
}}
.dr-stage::after {{  /* 节点 */
  content: "";
  position: absolute;
  top: 1px; left: 0;
  width: 9px; height: 9px;
  border-radius: 50%;
  border: 1.5px solid #C8C8C2;
  background: var(--paper);
}}
.dr-stage .dr-stage-label {{
  font-size: 13px;
  color: #9AA0A6;
  font-weight: 500;
}}
.dr-stage .dr-stage-node {{
  display: block;
  font-family: var(--mono);
  font-size: 10px;
  color: #B4B8BC;
  margin-top: 1px;
}}
.dr-stage.done::after {{ background: var(--green); border-color: var(--green); }}
.dr-stage.done::before {{ background: #C9D8CE; }}
.dr-stage.done .dr-stage-label {{ color: var(--ink); }}
.dr-stage.done .dr-stage-node {{ color: var(--ink-soft); }}
.dr-stage.active::after {{
  background: var(--indigo);
  border-color: var(--indigo);
  box-shadow: 0 0 0 4px rgba(44, 74, 120, 0.14);
}}
.dr-stage.active .dr-stage-label {{ color: var(--indigo); font-weight: 600; }}
.dr-stage.active .dr-stage-node {{ color: var(--indigo); }}
.dr-stage.awaiting::after {{
  background: var(--brass);
  border-color: var(--brass);
  box-shadow: 0 0 0 4px rgba(162, 120, 43, 0.16);
}}
.dr-stage.awaiting .dr-stage-label {{ color: var(--brass); font-weight: 600; }}
.dr-stage.awaiting .dr-stage-node {{ color: var(--brass); }}
.dr-rail-note {{
  font-family: var(--mono);
  font-size: 11px;
  color: var(--ink-soft);
  margin: -6px 0 18px;
}}

/* ---------- 指标带 ---------- */
.dr-band {{
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 18px;
}}
.dr-band > div {{ background: var(--card); padding: 14px 16px; }}
.dr-meter {{ flex: 2 1 300px; min-width: 260px; }}
.dr-meter-head {{
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px; color: var(--ink-soft);
}}
.dr-meter-head strong {{
  font-family: var(--mono); font-size: 20px; font-weight: 500; color: var(--ink);
}}
.dr-track {{
  position: relative;
  height: 7px;
  background: #EFEFEA;
  border-radius: 4px;
  margin: 10px 0 7px;
  overflow: visible;
}}
.dr-fill {{ height: 100%; border-radius: 4px; background: var(--green); }}
.dr-fill.low {{ background: var(--rust); }}
.dr-floor {{
  position: absolute; top: -3px; width: 1px; height: 13px;
  background: #B9B9B2;
}}
.dr-meter-foot {{ font-size: 11px; color: var(--ink-soft); font-family: var(--mono); }}
.dr-stat {{ flex: 1 1 96px; }}
.dr-stat span {{
  display: block;
  font-size: 11px;
  color: var(--ink-soft);
  margin-bottom: 4px;
}}
.dr-stat strong {{
  font-family: var(--mono); font-size: 17px; font-weight: 500; color: var(--ink);
}}
.dr-stat strong.rust {{ color: var(--rust); }}
.dr-stat strong.green {{ color: var(--green); }}

/* ---------- 警示条 ---------- */
.dr-warn {{
  border-left: 3px solid var(--rust);
  background: #FBF2F0;
  padding: 10px 14px;
  border-radius: 0 8px 8px 0;
  font-size: 13px;
  color: #7B2E24;
  margin-bottom: 16px;
}}
.dr-warn code {{
  font-family: var(--mono);
  background: #F3E2DE;
  padding: 1px 5px;
  border-radius: 4px;
}}

/* ---------- 审核卡（唯一的黄铜强调） ---------- */
.dr-review {{
  border: 1px solid #E3D6B8;
  border-left: 3px solid var(--brass);
  background: #FDFAF2;
  border-radius: 0 10px 10px 0;
  padding: 16px 18px;
  margin-bottom: 16px;
}}
.dr-review .dr-eyebrow {{
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--brass);
  margin-bottom: 6px;
}}
.dr-review p {{ margin: 0; font-size: 13.5px; color: #5A4A2C; line-height: 1.65; }}
.dr-review strong {{ color: #3F3218; }}

/* ---------- 报告 ---------- */
.st-key-reportcard {{
  border-top: 1px solid var(--rule);
  padding-top: 22px;
}}
/* 正文限制行宽（中文约 44 字一行）：段落/列表才需要，表格和代码块要给满宽 */
.st-key-reportcard p, .st-key-reportcard li, .st-key-reportcard blockquote {{
  max-width: 44em;
}}
.st-key-reportcard h1 {{
  font-family: var(--serif);
  font-size: 27px; line-height: 1.35; margin: 0 0 18px; font-weight: 600;
}}
.st-key-reportcard h2 {{
  font-family: var(--serif);
  font-size: 19px; margin: 30px 0 10px; font-weight: 600;
  padding-bottom: 6px; border-bottom: 1px solid var(--rule);
}}
.st-key-reportcard h3 {{
  font-family: var(--serif);
  font-size: 16px; margin: 22px 0 8px; font-weight: 600;
}}
.st-key-reportcard p {{ font-size: 15px; line-height: 1.85; color: #202B38; }}
.st-key-reportcard li {{ line-height: 1.8; margin-bottom: 4px; }}
.st-key-reportcard code {{
  font-family: var(--mono); font-size: 0.86em;
  background: #F1F1EC; padding: 1px 5px; border-radius: 4px;
}}
.st-key-reportcard blockquote {{
  border-left: 2px solid var(--rule);
  padding-left: 14px; color: var(--ink-soft); font-style: normal;
}}
.st-key-reportcard table {{ border-collapse: collapse; font-size: 14px; }}
.st-key-reportcard th, .st-key-reportcard td {{
  border: 1px solid var(--rule); padding: 7px 11px; text-align: left;
}}
.st-key-reportcard th {{ background: #F6F6F1; font-weight: 600; }}

/* ---------- 来源台账 ---------- */
.dr-ledger {{
  border-top: 1px solid var(--rule);
  margin-top: 30px;
  padding-top: 20px;
}}
.dr-ledger-head {{
  display: flex; justify-content: space-between; align-items: baseline;
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-soft);
  margin-bottom: 14px;
}}
.dr-src {{
  display: flex; gap: 14px;
  padding: 12px 0;
  border-top: 1px solid #EFEEE8;
}}
.dr-src:first-of-type {{ border-top: none; }}
.dr-src-n {{
  font-family: var(--mono); font-size: 13px; color: var(--indigo);
  min-width: 34px; padding-top: 1px;
}}
.dr-src-file {{ font-size: 13px; font-weight: 600; color: var(--ink); }}
.dr-src-text {{
  font-size: 13px; color: var(--ink-soft); line-height: 1.7; margin-top: 3px;
}}
.dr-empty {{
  font-size: 13px; color: var(--ink-soft);
  border: 1px dashed var(--rule); border-radius: 10px; padding: 18px;
}}

/* ---------- 空状态 ---------- */
.dr-intro {{ max-width: 60ch; margin-bottom: 6px; }}
.dr-intro h1 {{
  font-family: var(--serif);
  font-size: 26px; font-weight: 600; margin: 0 0 10px; line-height: 1.4;
}}
.dr-intro p {{ color: var(--ink-soft); font-size: 14px; line-height: 1.8; margin: 0 0 8px; }}
.dr-steps {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  border-radius: 10px; overflow: hidden; margin: 18px 0 10px;
}}
.dr-steps div {{ background: var(--card); padding: 14px 16px; }}
.dr-steps b {{
  display: block; font-family: var(--mono); font-size: 10.5px;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--indigo);
  margin-bottom: 6px;
}}
.dr-steps span {{ font-size: 13px; color: var(--ink-soft); line-height: 1.6; }}

/* ---------- 侧栏 ---------- */
[data-testid="stSidebar"] h2 {{ font-size: 15px; margin: 0 0 2px; }}
.dr-side-label {{
  font-family: var(--mono); font-size: 10.5px;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-soft);
  margin: 18px 0 6px;
}}
.dr-side-note {{ font-size: 12px; color: var(--ink-soft); line-height: 1.6; }}
.dr-session {{
  font-family: var(--mono); font-size: 11.5px; color: var(--ink-soft);
  line-height: 1.7; border-top: 1px solid var(--rule); padding-top: 10px;
}}

/* ---------- 窄屏 ---------- */
@media (max-width: 680px) {{
  .block-container {{ padding-top: 1rem; }}
  .dr-stage {{ min-width: 76px; }}
  .dr-stage .dr-stage-label {{ font-size: 12px; }}
  .st-key-reportcard h1 {{ font-size: 23px; }}
  .dr-title {{ font-size: 18px; }}
}}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>
"""


# ---------------------------------------------------------------------------
# 纯函数：把状态翻译成人能读的 HTML
# ---------------------------------------------------------------------------

def stage_index(name: str) -> int:
    """阶段在流水线里的下标；未知阶段返回 -1。"""
    return STAGE_NAMES.index(name) if name in STAGE_NAMES else -1


def infer_stage(values: dict, interrupted: bool = False) -> str:
    """根据 checkpoint 里已有的字段推断「现在走到哪一步」。

    判断依据是「哪个字段已经被写入」——每个字段只有一个写入节点（见 state.py），
    所以最后一个写进来的字段，决定下一个要跑的节点。
    """
    if interrupted:
        return "human_gate"
    if values.get("revisions"):
        return "critic"          # critic 已经审过至少一轮
    if values.get("report"):
        return "verifier"        # writer 写完 -> 下一步核验
    if values.get("notes"):
        return "writer"          # collect 归并完 -> 下一步撰写
    if values.get("findings"):
        return "collect"
    if values.get("sub_questions"):
        return "researcher"
    return "planner"


def stage_rail(current: str, researcher_count: int = 0,
               finished: bool = False, awaiting: bool = False) -> str:
    """画那条阶段轨道。

    current 是正在进行的阶段；它之前的都算完成。finished=True 时全部标完成。
    轨道标签直接用图里的节点名，看过 graph.py 的人一眼能对上。
    """
    idx = stage_index(current)
    cells = []
    for i, (node, label) in enumerate(STAGES):
        text = f"{label} ×{researcher_count}" if node == "researcher" and researcher_count else label
        if finished or i < idx:
            kind = "done"
        elif i == idx:
            kind = "awaiting" if awaiting else "active"
        else:
            kind = ""
        cells.append(
            f'<div class="dr-stage {kind}">'
            f'<span class="dr-stage-label">{html.escape(text)}</span>'
            f'<span class="dr-stage-node">{node}</span>'
            f"</div>"
        )
    return f'<div class="dr-rail">{"".join(cells)}</div>'


def _num(value) -> str:
    """整数加千分位；None 显示为短横线。"""
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def metric_band(result: dict) -> str:
    """指标带：左边覆盖率仪表（带及格刻度），右边几个等宽数字。"""
    metrics = result.get("metrics") or {}
    coverage = result.get("citation_coverage")
    invalid = result.get("invalid_citations") or []

    if coverage is None:
        coverage_html = (
            '<div class="dr-meter">'
            '<div class="dr-meter-head"><span>引用覆盖率</span><strong>—</strong></div>'
            '<div class="dr-track"></div>'
            '<div class="dr-meter-foot">报告生成后统计</div>'
            "</div>"
        )
    else:
        pct = max(0.0, min(1.0, float(coverage))) * 100
        low = "low" if coverage < COVERAGE_FLOOR else ""
        coverage_html = (
            '<div class="dr-meter">'
            f'<div class="dr-meter-head"><span>引用覆盖率</span><strong>{pct:.0f}%</strong></div>'
            f'<div class="dr-track"><div class="dr-fill {low}" style="width:{pct:.0f}%"></div>'
            f'<i class="dr-floor" style="left:{COVERAGE_FLOOR * 100:.0f}%"></i></div>'
            f'<div class="dr-meter-foot">及格线 {COVERAGE_FLOOR:.0%}'
            f'{" · 低于及格线会打回重写" if coverage < COVERAGE_FLOOR else " · 已达标"}</div>'
            "</div>"
        )

    # 指标卡：值只放数字/时长，颜色由标签决定（编造引用标红）
    stats = [
        ("tokens", _num(metrics.get("total_tokens"))),
        (
            "耗时",
            f'{metrics["llm_seconds"]}s'
            if metrics.get("llm_seconds") is not None
            else "—",
        ),
        ("审查轮次", _num(result.get("revisions"))),
        ("来源", _num(len(result.get("sources") or []))),
    ]
    if invalid:
        stats.append(("编造引用", f"{len(invalid)} 处"))

    stats_rows = []
    for label, value in stats:
        css = "rust" if label == "编造引用" else ""
        stats_rows.append(
            f'<div class="dr-stat"><span>{label}</span>'
            f'<strong class="{css}">{value}</strong></div>'
        )
    stats_html = "".join(stats_rows)
    return f'<div class="dr-band">{coverage_html}{stats_html}</div>'


def invalid_citation_warning(result: dict) -> str:
    """报告里引用了不存在的编号时的警示条（空字符串表示没问题）。"""
    invalid = result.get("invalid_citations") or []
    if not invalid:
        return ""
    nums = "、".join(f"<code>[{n}]</code>" for n in invalid)
    return (
        '<div class="dr-warn">报告引用了资料库里不存在的编号：'
        f"{nums}。这些句子没有依据，建议退回重写。</div>"
    )


def source_ledger(sources: list[dict] | None) -> str:
    """来源台账：把 sources 渲染成「编号 + 文件名 + 片段」的清单。"""
    sources = sources or []
    if not sources:
        return (
            '<div class="dr-ledger"><div class="dr-ledger-head"><span>来源台账</span>'
            '<span>0 条</span></div><div class="dr-empty">本次没有检索到资料，'
            "报告里的结论无法溯源。先运行 <code>python -m deepresearch.ingest data/docs</code>"
            " 把文档入库，再重新调研。</div></div>"
        )
    rows = []
    for item in sources:
        n = item.get("n")
        text = (item.get("text") or "").strip().replace("\n", " ")
        if len(text) > 220:
            text = text[:220] + "…"
        rows.append(
            '<div class="dr-src">'
            f'<div class="dr-src-n">[{n}]</div>'
            '<div><div class="dr-src-file">'
            f'{html.escape(str(item.get("source", "?")))}</div>'
            f'<div class="dr-src-text">{html.escape(text)}</div></div>'
            "</div>"
        )
    return (
        '<div class="dr-ledger"><div class="dr-ledger-head">'
        f"<span>来源台账 · 报告里的 [n] 对应这里</span><span>{len(sources)} 条</span>"
        f'</div>{"".join(rows)}</div>'
    )


def review_notice(result: dict) -> str:
    """等待人工审核时的那张卡（黄铜色，全站只在需要人动手时才出现）。"""
    coverage = result.get("citation_coverage")
    coverage_text = f"引用覆盖率 {coverage:.0%}" if coverage is not None else "覆盖率待统计"
    return (
        '<div class="dr-review">'
        '<div class="dr-eyebrow">awaiting review</div>'
        "<p><strong>报告已生成，等你决定。</strong><br>"
        f"{coverage_text}。批准后进入 critic 终审并交付；退回后会按你的意见重写，"
        "再回到这里复核。</p>"
        "</div>"
    )


def brand_bar(chunks: int | None, degraded: bool = False) -> str:
    """顶栏：左品牌，右索引状态。chunks 为 None 表示读不到索引。"""
    if chunks is None:
        dot, text = "rust", "索引不可用"
    elif chunks == 0:
        dot, text = "gray", "索引为空"
    else:
        dot, text = "", f"索引就绪 · <strong>{chunks:,}</strong> 片段"
    return (
        '<div class="dr-brandbar">'
        '<div class="dr-brand"><div class="dr-mark"></div>'
        '<div><div class="dr-title">DeepResearch</div>'
        '<div class="dr-sub">multi-agent research desk</div></div></div>'
        f'<div class="dr-index"><span class="dr-dot {dot}"></span>{text}</div>'
        "</div>"
    )


def intro() -> str:
    """空状态：还没跑过调研时，告诉人这是什么、会发生什么。"""
    return (
        '<div class="dr-intro"><h1>把一个问题，跑成一份有出处的报告。</h1>'
        "<p>系统会拆解问题、并行检索本地文档、写成报告，然后用程序核验每条引用，"
        "最后交给 critic 审稿。左侧输入问题即可开始；想先看稿再交付，打开人工审核。</p>"
        "</div>"
        '<div class="dr-steps">'
        "<div><b>01 · 拆解</b><span>planner 把问题拆成 2–4 个能独立回答的子问题</span></div>"
        "<div><b>02 · 检索</b><span>researcher 并行检索，资料按 [n] 编号</span></div>"
        "<div><b>03 · 撰写</b><span>writer 只允许引用编号表里的来源</span></div>"
        "<div><b>04 · 核验</b><span>verifier 算覆盖率、揪编造引用，不达标就重写</span></div>"
        "</div>"
    )
