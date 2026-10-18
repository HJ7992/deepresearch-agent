"""checkpoint 工厂：默认 SQLite（零部署，进程重启可恢复），配 DATABASE_URL 用 Postgres。

面试话术：checkpoint 是「断点续跑」和「人工审核暂停」的地基——每一步状态按
thread_id 落库，进程挂了重启后能从断点继续；同一个 thread_id 再次提问，
还能复用上一次的对话状态（多轮记忆）。
"""

from __future__ import annotations

import logging
import pathlib
import sqlite3
import threading

from .config import settings

logger = logging.getLogger(__name__)

_saver = None
_lock = threading.Lock()


def make_checkpointer():
    """返回进程级单例 checkpointer。SQLite 默认写 data/checkpoints.sqlite。"""
    global _saver
    with _lock:
        if _saver is not None:
            return _saver

        if settings.database_url:
            # Postgres 需要额外依赖：uv sync --extra postgres
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver

            conn = psycopg.connect(
                settings.database_url, autocommit=True, prepare_threshold=0
            )
            saver = PostgresSaver(conn)
            saver.setup()
            logger.info("checkpoint：Postgres")
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = pathlib.Path(settings.checkpoint_db)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            saver = SqliteSaver(conn)
            logger.info("checkpoint：SQLite %s", path)

        _saver = saver
        return _saver
