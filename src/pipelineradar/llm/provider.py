"""LLM provider abstraction.

All agent code calls this module — never imports the Anthropic or Azure SDK
directly. Switching providers is a one-line change here.

Default: Anthropic Claude via the `anthropic` SDK.
Swap:    Set AZURE_OPENAI_* env vars and change the factory below.
"""

from __future__ import annotations

# Phase 3: implement AnthropicProvider and AzureOpenAIProvider behind a
# common LLMProvider protocol, expose a get_provider() factory.
