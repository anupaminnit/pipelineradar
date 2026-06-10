"""LLM provider abstraction.

All agent code calls this module — never imports the Anthropic or Azure SDK
directly. Switching providers is a one-line change in get_provider().

Default: Anthropic Claude (claude-haiku-4-5-20251001) via the anthropic SDK.
Swap:    Replace AnthropicProvider with an AzureOpenAIProvider below.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import anthropic


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int = 256) -> str: ...


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system: str, user: str, max_tokens: int = 256) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        block = message.content[0]
        if block.type != "text":
            return ""
        return block.text.strip()


def get_provider() -> LLMProvider:
    from pipelineradar.config import get_settings

    settings = get_settings()
    return AnthropicProvider(api_key=settings.anthropic_api_key)
