"""命令行入口：python -m deepresearch.main "你的调研问题"

跑完整流水线，报告存 reports/*.md，计量信息（token/耗时/成本/引用覆盖率）
存同名 *.json。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
import re

from .retriever import get_store
from .runner import run


def _slugify(text: str, max_len: int = 40) -> str:
    """把问题转成安全的文件名片段（保留中文，去掉路径非法字符）。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "report"


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepResearch 多 Agent 调研助手")
    parser.add_argument("question", help="要调研的问题")
    parser.add_argument("--thread-id", default=None, help="会话线程 ID（默认按时间生成）")
    parser.add_argument(
        "--max-revisions", type=int, default=1,
        help="critic 否决后允许的修订轮数（默认 1）",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    result = run(
        args.question,
        thread_id=args.thread_id or dt.datetime.now().strftime("run-%Y%m%d-%H%M%S"),
        max_revisions=args.max_revisions,
    )

    out_dir = pathlib.Path("reports")
    out_dir.mkdir(exist_ok=True)
    stem = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{_slugify(args.question)}"
    (out_dir / f"{stem}.md").write_text(result["report"], encoding="utf-8")
    payload = {
        "question": args.question,
        "metrics": result.get("metrics", {}),
        "citation_coverage": result.get("citation_coverage"),
        "invalid_citations": result.get("invalid_citations", []),
        "sources": len(result.get("sources", [])),
        "revisions": result.get("revisions", 0),
        "verdict_passed": result.get("verdict_passed"),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(result["report"])
    print(f"\n[已保存] {out_dir / f'{stem}.md'}")
    m = result.get("metrics", {})
    print(
        f"[计量] {m.get('llm_calls')} 次调用，"
        f"{m.get('total_tokens')} tokens，"
        f"{m.get('llm_seconds')}s，"
        f"引用覆盖率 {result.get('citation_coverage')}"
    )
    # 本地嵌入式向量库在进程退出前显式关闭，避免 __del__ 告警
    try:
        get_store().close()
    except Exception as exc:  # noqa: BLE001 — 关闭失败不影响结果
        logging.getLogger(__name__).debug("关闭向量库失败：%s", exc)


if __name__ == "__main__":
    main()
