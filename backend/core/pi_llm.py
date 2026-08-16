"""LangChain-compatible chat model backed by the Pi SDK worker."""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Sequence

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.core.codex_llm import serialize_messages
from backend.core.pi_client import run_pi_text


class PiChatModel(BaseChatModel):
    """Run Pi's harness while keeping Taoci's selected API as the model host."""

    provider_name: str
    model_name: str
    base_url: str
    api_key: str = ""
    timeout_seconds: int = 600
    context_window: int = 128000
    max_tokens: int = 16384

    @property
    def _llm_type(self) -> str:
        return "pi-sdk-worker"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
        }

    def model_config_payload(self, model: str | None = None) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": (model or self.model_name).strip(),
            "base_url": self.base_url,
            "api_key": self.api_key,
            "context_window": self.context_window,
            "max_tokens": self.max_tokens,
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._agenerate(messages, stop=stop, run_manager=None, **kwargs)
            )
        raise RuntimeError("PiChatModel synchronous invoke cannot run inside an event loop")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop:
            raise ValueError("PiChatModel does not support stop sequences")
        content = await run_pi_text(
            serialize_messages(messages),
            model_config=self.model_config_payload(
                str(kwargs.get("model") or self.model_name)
            ),
            timeout_seconds=int(kwargs.get("timeout_seconds", self.timeout_seconds)),
            harness=str(kwargs.get("agent_harness", "general")),
            output_schema=kwargs.get("output_schema"),
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError(
            "PiChatModel uses named Pi harnesses instead of LangChain tool binding"
        )


def is_pi_llm(llm: BaseChatModel) -> bool:
    return isinstance(llm, PiChatModel)
