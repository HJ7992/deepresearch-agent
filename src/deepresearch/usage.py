"""token 与耗时计量：一个 LangChain 回调，挂在 graph.invoke 的 config 上。

谁在用：runner.run()/resume() 每次执行都 new 一个 UsageTracker 塞进 callbacks，
执行完调 summary() 把数字补进返回值，最终随报告一起落到 reports/*.json。

为什么值得做：成本必须可见。评测时把每题的 metrics 一平均，就能得到「一次调研
多少钱、多少秒」，而不是靠感觉拍数字。
"""

import logging
import time

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


def _usage_of(response) -> dict:
    """从 LLMResult 里取 token 用量。

    不同端点/不同 LangChain 版本把用量放在两个地方之一：
    llm_output["token_usage"]（OpenAI 老式）或 message.usage_metadata（新式）。
    都取不到就返回空字典，计量退化成 0，不影响主流程。
    """
    usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
    if usage:
        return usage
    try:
        message = response.generations[0][0].message
        return getattr(message, "usage_metadata", None) or {}
    except (IndexError, AttributeError):
        return {}


class UsageTracker(BaseCallbackHandler):
    """统计 LLM 调用次数、token 用量和累计耗时。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_seconds = 0.0
        # run_id -> 开始时间。并行的 researcher 会同时有多条记录在飞，
        # 所以必须按 run_id 分开记，不能只存一个全局起点。
        self._started: dict = {}

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        """记下这次调用的开始时间（跑完再配对算耗时）。"""
        self._started[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        """调用结束：累计耗时和 token。"""
        start = self._started.pop(run_id, None)
        if start is not None:
            self.total_seconds += time.perf_counter() - start
        self.calls += 1

        usage = _usage_of(response)
        # 两种命名都要兼容：OpenAI 叫 prompt/completion，新式叫 input/output
        self.prompt_tokens += int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        )
        self.completion_tokens += int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )

    def summary(self, price_input_per_mtok: float = 0.0,
                price_output_per_mtok: float = 0.0) -> dict:
        """汇总成可直接落盘的字典。单价为 0 时 estimated_cost 就是 0。"""
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
            # 没填单价就不写币种，避免出现「0 元」这种误导性结论
            "cost_currency": "CNY" if price_input_per_mtok or price_output_per_mtok else "",
        }
