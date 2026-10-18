"""计量测试：token 累计、成本估算、无 usage 时的容错。"""

import uuid

from langchain_core.outputs import Generation, LLMResult

from deepresearch.usage import UsageTracker


def _response(prompt=100, completion=50):
    return LLMResult(
        generations=[[Generation(text="ok")]],
        llm_output={"token_usage": {"prompt_tokens": prompt, "completion_tokens": completion}},
    )


def test_accumulates_tokens_and_calls():
    tracker = UsageTracker()
    for _ in range(2):
        rid = uuid.uuid4()
        tracker.on_llm_start({}, [], run_id=rid)
        tracker.on_llm_end(_response(100, 50), run_id=rid)

    summary = tracker.summary()
    assert summary["llm_calls"] == 2
    assert summary["prompt_tokens"] == 200
    assert summary["completion_tokens"] == 100
    assert summary["total_tokens"] == 300


def test_estimates_cost():
    tracker = UsageTracker()
    rid = uuid.uuid4()
    tracker.on_llm_start({}, [], run_id=rid)
    tracker.on_llm_end(_response(1_000_000, 500_000), run_id=rid)

    summary = tracker.summary(price_input_per_mtok=2.0, price_output_per_mtok=8.0)
    # 1M input * 2 + 0.5M output * 8 = 2 + 4 = 6
    assert summary["estimated_cost"] == 6.0
    assert summary["cost_currency"] == "CNY"


def test_missing_usage_is_tolerated():
    tracker = UsageTracker()
    rid = uuid.uuid4()
    tracker.on_llm_start({}, [], run_id=rid)
    tracker.on_llm_end(LLMResult(generations=[[Generation(text="ok")]]), run_id=rid)
    assert tracker.summary()["total_tokens"] == 0
    assert tracker.summary()["llm_calls"] == 1
