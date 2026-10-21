"""评测脚本：跑固定评测集，产出可复现的指标与消融对比。

用法：
  python eval/run_eval.py                        # 全量 20 题
  python eval/run_eval.py --limit 3              # 冒烟（只跑前 3 题）
  python eval/run_eval.py --mode no_retrieval    # 消融：关掉检索
  python eval/run_eval.py --mode no_verify --limit 6

判定规则（全部可复现、不依赖模型自评）：
- 关键词命中率：期望关键词出现在报告中的比例（子串匹配，中文可用）
- 引用覆盖率：verifier 计算的、有有效引用的结论段落占比
- 任务成功：关键词命中 ≥ 阈值 且 覆盖率 ≥ 阈值 且 无编造引用
- 质量判定：流水线内 critic 的 verdict（LLM 评审，单独记录）

每跑完一题就追加写一行 JSONL，进程中断也不会丢已完成的结果。
"""

import argparse
import datetime as dt
import json
import pathlib
import statistics
import time

from deepresearch.runner import run

EVAL_DIR = pathlib.Path(__file__).parent
REPORT_DIR = EVAL_DIR.parent / "reports"

KEYWORD_MIN = 0.5      # 关键词命中率门槛
COVERAGE_MIN = 0.6     # 引用覆盖率门槛


def load_questions() -> list[dict]:
    return json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))


def keyword_hit(report: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    text = report.lower()
    hit = sum(1 for k in keywords if k.lower() in text)
    return hit / len(keywords)


def evaluate_one(item: dict, mode: str) -> dict:
    started = time.perf_counter()
    result = run(item["question"], thread_id=f"eval-{item['id']}-{mode}", review=False, mode=mode)
    elapsed = time.perf_counter() - started

    report = result.get("report", "")
    hit_rate = keyword_hit(report, item.get("keywords", []))
    coverage = result.get("citation_coverage") or 0.0
    invalid = result.get("invalid_citations") or []
    metrics = result.get("metrics", {})

    success = hit_rate >= KEYWORD_MIN and coverage >= COVERAGE_MIN and not invalid
    return {
        "id": item["id"],
        "category": item["category"],
        "mode": mode,
        "question": item["question"],
        "keyword_hit": round(hit_rate, 3),
        "citation_coverage": round(float(coverage), 3),
        "invalid_citations": invalid,
        "verdict_passed": bool(result.get("verdict_passed")),
        "revisions": int(result.get("revisions", 0)),
        "success": success,
        "sources": len(result.get("sources", [])),
        "prompt_tokens": metrics.get("prompt_tokens", 0),
        "completion_tokens": metrics.get("completion_tokens", 0),
        "total_tokens": metrics.get("total_tokens", 0),
        "llm_calls": metrics.get("llm_calls", 0),
        "seconds": round(elapsed, 1),
    }


def summarize(rows: list[dict], mode: str) -> dict:
    if not rows:
        return {"mode": mode, "count": 0}
    def mean(key):
        return round(statistics.mean(r[key] for r in rows), 3)
    return {
        "mode": mode,
        "count": len(rows),
        "success_rate": round(sum(1 for r in rows if r["success"]) / len(rows), 3),
        "mean_keyword_hit": mean("keyword_hit"),
        "mean_coverage": mean("citation_coverage"),
        "invalid_citation_rate": round(
            sum(1 for r in rows if r["invalid_citations"]) / len(rows), 3
        ),
        "critic_pass_rate": round(sum(1 for r in rows if r["verdict_passed"]) / len(rows), 3),
        "mean_tokens": int(statistics.mean(r["total_tokens"] for r in rows)),
        "mean_seconds": round(statistics.mean(r["seconds"] for r in rows), 1),
    }


def to_markdown(summaries: list[dict]) -> str:
    header = (
        "| 模式 | 题数 | 任务成功率 | 关键词命中 | 引用覆盖率 | 编造引用率 | critic 通过率 | 平均 tokens | 平均耗时(s) |\n"
        "|------|------|-----------|-----------|-----------|-----------|--------------|------------|------------|\n"
    )
    lines = []
    for s in summaries:
        lines.append(
            f"| {s['mode']} | {s['count']} | {s['success_rate']:.0%} | "
            f"{s['mean_keyword_hit']:.0%} | {s['mean_coverage']:.0%} | "
            f"{s['invalid_citation_rate']:.0%} | {s['critic_pass_rate']:.0%} | "
            f"{s['mean_tokens']} | {s['mean_seconds']} |"
        )
    return header + "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepResearch 评测脚本")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（冒烟）")
    parser.add_argument(
        "--mode", default="full", choices=["full", "no_retrieval", "no_verify"],
        help="full=完整流水线；no_retrieval=关检索；no_verify=关引用强制",
    )
    args = parser.parse_args()

    questions = load_questions()
    if args.limit:
        questions = questions[: args.limit]

    REPORT_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    progress = REPORT_DIR / f"eval-{args.mode}-{stamp}.jsonl"
    rows: list[dict] = []

    print(f"[评测] 模式={args.mode} 题数={len(questions)} 输出={progress}", flush=True)
    for i, item in enumerate(questions, start=1):
        row = evaluate_one(item, args.mode)
        rows.append(row)
        with progress.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"[{i}/{len(questions)}] {item['id']} 命中={row['keyword_hit']:.0%} "
            f"覆盖率={row['citation_coverage']:.0%} 成功={row['success']} "
            f"tokens={row['total_tokens']} {row['seconds']}s",
            flush=True,
        )

    summary = summarize(rows, args.mode)
    out_json = REPORT_DIR / f"eval-summary-{args.mode}-{stamp}.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md = REPORT_DIR / f"eval-summary-{args.mode}-{stamp}.md"
    out_md.write_text(to_markdown([summary]), encoding="utf-8")

    print("\n" + to_markdown([summary]))
    print(f"\n[完成] 汇总：{out_json}")
    print(f"[完成] 明细：{progress}")


if __name__ == "__main__":
    main()
