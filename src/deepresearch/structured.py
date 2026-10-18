"""结构化输出的兼容性适配层。

不同 OpenAI 兼容端点对「结构化输出」的支持差异很大：
- OpenAI 官方：function_calling / json_schema 均可；
- DeepSeek 思考型模型（deepseek-flash 等）：不支持强制 tool_choice，
  只能用 response_format=json_object（即 json_mode）；
- 更保守的端点：两者都不支持，只能纯提示词 + 手工解析。

所以这里实现自动降级链：function_calling → json_mode → prompted。
遇到兼容性错误（信息里提到 tool_choice / response_format 等）就换下一种，
成功后记住该模式，后续调用不再重复踩坑——「换模型不用改代码」的关键。
"""

from __future__ import annotations

import json
import logging
import re

from .config import settings

logger = logging.getLogger(__name__)

# 出现这些关键词，基本可判定是「端点不支持该输出方式」，而不是网络/鉴权错误
_COMPAT_HINTS = (
    "tool_choice",
    "response_format",
    "json_schema",
    "does not support",
    "not support",
    "unavailable",
)


def _is_compat_error(exc: Exception) -> bool:
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
    """把「按 schema 输出结构化结果」包装成自动降级的调用器。"""

    def __init__(self, llm, schema, modes: tuple[str, ...] | None = None):
        self.llm = llm
        self.schema = schema
        preferred = modes or (settings.structured_mode, "json_mode", "prompted")
        # 去重但保序：首选模式在最前，其余按兼容性从强到弱兜底
        chain: list[str] = []
        for mode in preferred:
            if mode not in chain:
                chain.append(mode)
        self.modes = chain

    def invoke(self, messages):
        last_exc: Exception | None = None
        while self.modes:
            mode = self.modes[0]
            try:
                return self._invoke(mode, messages)
            except Exception as exc:  # 需要按错误信息分类降级，故捕获基类
                if not _is_compat_error(exc):
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
        if mode == "prompted":
            return self._prompted(messages)
        if mode == "json_mode":
            # 部分端点（如 DeepSeek）要求提示词里必须出现 "json" 才允许
            # response_format=json_object，这里自动补一条 schema 提示。
            schema_json = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
            hint = f"请只输出符合下面 JSON Schema 的 JSON：{schema_json}"
            messages = [("system", hint)] + list(messages)
        # function_calling 与 json_mode 都交给 LangChain 处理
        return self.llm.with_structured_output(self.schema, method=mode).invoke(messages)

    def _prompted(self, messages):
        """最保守的模式：把 schema 写进提示词，自己解析返回的 JSON。"""
        schema_json = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
        system = (
            "你是一个严格的 JSON 输出器：只输出符合下面 JSON Schema 的 JSON，"
            "不要输出解释文字，也不要用代码块包裹。\n"
            f"JSON Schema：{schema_json}"
        )
        reply = self.llm.invoke([("system", system)] + list(messages))
        text = getattr(reply, "text", None) or str(getattr(reply, "content", ""))
        return self.schema.model_validate_json(_extract_json(text))
