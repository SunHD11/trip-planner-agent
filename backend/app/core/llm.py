"""OpenAI 兼容 LLM 客户端（DeepSeek 等）。

两种调用方式：
- chat():  非流式，返回完整 assistant message（可能带 tool_calls）—— agent 循环专用
- think(): 流式，返回纯文本 —— 简单问答 / 调试用

v1 约定：agent 的 tool-calling 全程非流式。
流式下 tool_calls 是分片到达的，拼接复杂且易错，不要混用。
"""

import logging
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage

from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败（网络、鉴权、空响应等）。调用方必须能感知，不允许静默吞掉。"""


class LLM:
    """调用任何 OpenAI 兼容接口的客户端。

    参数全部可选：缺省时从 app.config.settings（即 .env）读取。
    密钥缺失的校验已由 settings 在导入时完成（启动即校验）。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.model = model or settings.llm_model_id
        self.client = OpenAI(
            api_key=api_key or settings.llm_api_key,
            base_url=base_url or settings.llm_base_url,
            timeout=timeout or settings.llm_timeout,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> ChatCompletionMessage:
        """非流式调用，返回完整的 assistant message。

        返回值可能带 content（最终回答），也可能带 tool_calls（要求执行工具），
        调用方两者都要处理。tools 原样透传给 API（OpenAI function calling 格式）。
        """
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        logger.debug("调用 LLM: model=%s, messages=%d 条, tools=%d 个",
                     self.model, len(messages), len(tools or []))
        try:
            response = self.client.chat.completions.create(**params)
        except Exception as exc:  # openai 的异常体系较散，统一包装后上抛
            raise LLMError(f"调用 LLM 失败（model={self.model}）: {exc}") from exc

        if not response.choices:
            raise LLMError("LLM 响应中没有 choices")

        message = response.choices[0].message
        tool_call_count = len(message.tool_calls or [])
        logger.debug("LLM 响应: tool_calls=%d 个, content 长度=%d",
                     tool_call_count, len(message.content or ""))
        return message

    def think(self, messages: list[dict[str, Any]], temperature: float = 0.0) -> str:
        """流式调用，收集并返回完整文本。仅用于简单问答/调试，不用于 agent。"""
        logger.info("流式调用 %s ...", self.model)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
            )
            chunks: list[str] = []
            for chunk in response:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content or ""
                chunks.append(content)
            result = "".join(chunks)
            logger.debug("流式响应完成，共 %d 字符", len(result))
            return result
        except Exception as exc:
            raise LLMError(f"流式调用 LLM 失败（model={self.model}）: {exc}") from exc


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    client = LLM()
    answer = client.think(
        [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "用一句话介绍北京"},
        ]
    )
    logger.info("回答: %s", answer)
