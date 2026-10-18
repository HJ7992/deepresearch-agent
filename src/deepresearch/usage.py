"""Token 与耗时计量：LangChain 回调，挂在 graph.invoke 的 config 上。

面试话术：成本必须可观测——每次调研的输入/输出 token、耗时、估算费用都随
报告落盘（reports/*.json），评测时可直接汇总出「单任务成本」。
"""

from __future__ import annotations

import logging
import time

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class UsageTracker(BaseCallbackHandler):
    """统计 LLM 调用次数、token 用量与累计耗时。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_seconds = 0.0
        self._started: dict = {}

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._started[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        start = self._started.pop(run_id, None)
        if start is not None:
            self.total_seconds += time.perf_counter() - start
        self.calls += 1

        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        if not usage:
            try:
                message = response.generations[0][0].message
                usage = getattr(message, "usage_metadata", None) or {}
            except (IndexError, AttributeError):
                usage = {}
        self.prompt_tokens += int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        )
        self.completion_tokens += int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )

    def summary(self, price_input_per_mtok: float = 0.0,
                price_output_per_mtok: float = 0.0) -> dict:
        cost = (
            self.prompt_tokens / 1_000_000 * price_input_per_mtok
            + self.completion_tokens / 1_000_000 * price_output_per_mtok
        )
        return {
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "llm_seconds": round(self.total_seconds, 2),
            "estimated_cost": round(cost, 6),
            "cost_currency": "CNY" if price_input_per_mtok or price_output_per_mtok else "",
        }
