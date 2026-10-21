"""命令行入口：在终端里跑一次调研，报告存进 reports/。

用法：
  python -m deepresearch.main "你的调研问题"            # 直接跑（无人工审核）
  python -m deepresearch.main --review "你的调研问题"   # 开启 HITL，人工批准/退回
  python -m deepresearch.main --resume <thread_id>      # 进程重启后恢复暂停的调研

报告存 reports/*.md，计量信息存同名 *.json（token、耗时、成本估算、覆盖率）。
"""

import argparse
import datetime as dt
import json
import logging
import pathlib
import re

from .retriever import get_store
from .runner import get_state, resume, run


def _slugify(text: str, max_len: int = 40) -> str:
    """把问题转成安全的文件名片段（保留中文，去掉路径非法字符）。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "report"


def _ask_decision(result: dict) -> dict:
    """人工审核交互：批准或退回（退回可以附一条意见）。"""
    print("\n" + "=" * 64)
    print("【人工审核】引用覆盖率：", result.get("citation_coverage"))
    invalid = result.get("invalid_citations") or []
    if invalid:
        # 编造引用是硬伤，先提醒再让人决定
        print("【警告】报告引用了不存在的编号：", invalid)
    while True:
        answer = input("批准这份报告？[y=批准 / n=退回] ").strip().lower()
        if answer in {"y", "n"}:
            break
    comment = ""
    if answer == "n":
        comment = input("退回意见（可留空）：").strip()
    return {"approved": answer == "y", "comment": comment}


def _save(result: dict, question: str) -> None:
    """把报告和计量信息各存一份到 reports/。"""
    out_dir = pathlib.Path("reports")
    out_dir.mkdir(exist_ok=True)
    stem = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{_slugify(question or 'resume')}"
    (out_dir / f"{stem}.md").write_text(result.get("report", ""), encoding="utf-8")

    # json 与 md 同名：看一眼报告，再对照它的成本和质量指标
    payload = {
        "question": question,
        "metrics": result.get("metrics", {}),
        "citation_coverage": result.get("citation_coverage"),
        "invalid_citations": result.get("invalid_citations", []),
        "sources": len(result.get("sources", [])),
        "revisions": result.get("revisions", 0),
        "verdict_passed": result.get("verdict_passed"),
        "human_approved": result.get("human_approved"),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[已保存] {out_dir / f'{stem}.md'}")
    m = result.get("metrics", {})
    print(
        f"[计量] {m.get('llm_calls')} 次调用，{m.get('total_tokens')} tokens，"
        f"{m.get('llm_seconds')}s，引用覆盖率 {result.get('citation_coverage')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepResearch 多 Agent 调研助手")
    parser.add_argument("question", nargs="?", help="要调研的问题（--resume 时可不填）")
    parser.add_argument(
        "--thread-id", default=None, help="会话线程 ID（默认按时间生成）"
    )
    parser.add_argument(
        "--max-revisions", type=int, default=1, help="critic 否决后允许的修订轮数"
    )
    parser.add_argument("--review", action="store_true", help="开启人工审核（HITL）")
    parser.add_argument(
        "--resume", metavar="THREAD_ID", default=None,
        help="恢复暂停的调研（进程重启后续跑）",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # 恢复模式：先把已有的报告打出来，再让人工做决定
    if args.resume:
        snapshot = get_state(args.resume)
        if not snapshot.values:
            print(f"[错误] 找不到 thread_id={args.resume} 的会话")
            raise SystemExit(1)
        print(snapshot.values.get("report", ""))
        result = resume(args.resume, _ask_decision(snapshot.values), args.max_revisions)
        thread_id = args.resume
        question = snapshot.values.get("question", "")
    else:
        if not args.question:
            parser.error("需要提供调研问题（或用 --resume 恢复会话）")
        thread_id = args.thread_id or dt.datetime.now().strftime("run-%Y%m%d-%H%M%S")
        result = run(
            args.question,
            thread_id=thread_id,
            max_revisions=args.max_revisions,
            review=args.review,
        )
        question = args.question

    # 可能暂停多次（人工退回重写后又会回到审核门），所以用循环而不是 if
    while result.get("paused"):
        print(result.get("report", ""))
        result = resume(thread_id, _ask_decision(result), args.max_revisions)

    print(result.get("report", ""))
    _save(result, question)
    # 本地嵌入式向量库要显式关闭，否则退出时 Qdrant 会打 __del__ 告警
    try:
        get_store().close()
    except Exception as exc:  # noqa: BLE001 — 关闭失败不影响结果
        logging.getLogger(__name__).debug("关闭向量库失败：%s", exc)


if __name__ == "__main__":
    main()
