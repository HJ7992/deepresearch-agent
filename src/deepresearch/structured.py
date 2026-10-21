"""结构化输出的兼容性适配层：一条自动降级的调用链。

谁在用：nodes.py 的 planner 和 critic 都要「按 schema 拿结果」，它们都用
StructuredCaller 而不是直接调 with_structured_output。

为什么要这一层：不同 OpenAI 兼容端点对结构化输出的支持差别很大——
- OpenAI 官方：function_calling / json_schema 都行；
- DeepSeek 思考型模型（deepseek-flash 等）：不支持强制 tool_choice，只能
  response_format=json_object（即 json_mode）；
- 更保守的端点：两个都不支持，只能纯提示词 + 自己解析 JSON（prompted）。

所以降级链是 function_calling → json_mode → prompted：遇到「端点不支持这种输出
方式」的报错就换下一种，成功后记住当前模式，后续调用不再重复踩坑。
这就是「换模型不用改代码」的实现。
"""

import json
import logging
import re

from .config import settings

logger = logging.getLogger(__name__)

# 出现这些关键词，基本可判定是「端点不支持该输出方式」，
# 而不是网络抖动或鉴权失败（那两类必须原样抛出去）
_COMPAT_HINTS = (
    "tool_choice",
    "response_format",
    "json_schema",
    "does not support",
    "not support",
    "unavailable",
)


def _is_compat_error(exc: Exception) -> bool:
    """这个异常是不是「端点不支持」，而不是 401/超时之类的真实故障。"""
    text = str(exc).lower()
    return any(hint in text for hint in _COMPAT_HINTS)


def _extract_json(text: str) -> str:
    """从模型输出里抠出 JSON：优先 ```json 代码块，其次首尾大括号之间。"""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    raise ValueError(f"模型输出里找不到 JSON：{text[:200]}")


class StructuredCaller:
    """把「按 schema 输出结构化结果」包装成一个会自动降级的调用器。"""

    def __init__(self, llm, schema, modes: tuple[str, ...] | None = None):
        self.llm = llm
        self.schema = schema
        preferred = modes or (settings.structured_mode, "json_mode", "prompted")
        # 去重但保序：首选模式排最前，其余按兼容性从强到弱兜底
        chain: list[str] = []
        for mode in preferred:
            if mode not in chain:
                chain.append(mode)
        # 注意：这个列表随调用推进不断 pop，即「记住」了当前端点可用的模式
        self.modes = chain

    def invoke(self, messages):
        """依次尝试各种模式，直到有一种成功。"""
        last_exc: Exception | None = None
        while self.modes:
            mode = self.modes[0]
            try:
                return self._invoke(mode, messages)
            except Exception as exc:  # 需要按错误信息分类降级，故捕获基类
                if not _is_compat_error(exc):
                    # 鉴权失败、超时等不属于「不兼容」，直接抛给上层
                    raise
                last_exc = exc
                logger.warning(
                    "结构化输出模式 %s 不被当前端点支持，自动降级（%s）",
                    mode,
                    str(exc)[:120],
                )
                self.modes.pop(0)
        raise RuntimeError("所有结构化输出模式都不可用，请检查端点配置") from last_exc

    def _invoke(self, mode: str, messages):
        """按指定模式真正发一次请求。"""
        if mode == "prompted":
            return self._prompted(messages)
        if mode == "json_mode":
            # 部分端点（如 DeepSeek）要求提示词里必须出现 "json" 才允许
            # response_format=json_object，这里自动补一条 schema 提示。
            schema_json = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
            hint = f"请只输出符合下面 JSON Schema 的 JSON：{schema_json}"
            messages = [("system", hint)] + list(messages)
        # function_calling 和 json_mode 都交给 LangChain 处理
        return self.llm.with_structured_output(self.schema, method=mode).invoke(messages)

    def _prompted(self, messages):
        """最保守的模式：把 schema 写进提示词，自己解析模型返回的 JSON。"""
        schema_json = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
        system = (
            "你是一个严格的 JSON 输出器：只输出符合下面 JSON Schema 的 JSON，"
            "不要输出解释文字，也不要用代码块包裹。\n"
            f"JSON Schema：{schema_json}"
        )
        reply = self.llm.invoke([("system", system)] + list(messages))
        text = getattr(reply, "text", None) or str(getattr(reply, "content", ""))
        # 交给 Pydantic 校验：格式不对就在这里报错，不会流到下游
        return self.schema.model_validate_json(_extract_json(text))
