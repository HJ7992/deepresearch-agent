"""checkpoint 工厂：把「每一步的状态」存下来，让图能暂停、能续跑。

谁在用：runner.build_app() 建图时传入；CLI 的 --resume、API 的 HITL 恢复都靠它。

为什么需要它：checkpoint 是「断点续跑」和「人工审核暂停」的地基。每一步状态按
thread_id 落库，进程挂了重启后能从断点继续；同一 thread_id 再次提问还能复用上次
的状态（多轮记忆）。

默认 SQLite（零部署），配了 DATABASE_URL 就用 Postgres（多进程、生产形态）。
"""

import logging
import pathlib
import sqlite3
import threading

from .config import settings

logger = logging.getLogger(__name__)

# 进程级单例 + 锁：SQLite 连接不能每个请求都新建，也不能被并发抢建
_saver = None
_lock = threading.Lock()


def make_checkpointer():
    """返回本进程共用的 checkpointer（第一次调用时创建）。"""
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
            saver.setup()  # 建表（幂等），首次运行也能用
            logger.info("checkpoint：Postgres")
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = pathlib.Path(settings.checkpoint_db)
            path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False：API 的后台线程也要能用这条连接
            conn = sqlite3.connect(str(path), check_same_thread=False)
            saver = SqliteSaver(conn)
            logger.info("checkpoint：SQLite %s", path)

        _saver = saver
        return _saver
