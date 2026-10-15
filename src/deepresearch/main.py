"""命令行入口：python -m deepresearch.main "你的调研问题"

跑完整流水线，报告自动存到 reports/ 目录（已 gitignore）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import pathlib
import re

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
    path = out_dir / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{_slugify(args.question)}.md"
    path.write_text(result["report"], encoding="utf-8")

    print(result["report"])
    print(f"\n[已保存] {path}")


if __name__ == "__main__":
    main()
