"""LangChain-compatible chat model backed by the host-side Codex harness."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional, Sequence

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.core.codex_client import run_codex_text


def _message_role(message: BaseMessage) -> str:
    if isinstance(message, SystemMessage):
        return "SYSTEM INSTRUCTIONS"
    if isinstance(message, HumanMessage):
        return "USER"
    if isinstance(message, AIMessage):
        return "ASSISTANT"
    if isinstance(message, ToolMessage):
        return "TOOL RESULT"
    return message.type.upper()


def _message_content(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, ensure_ascii=False)


def serialize_messages(messages: Sequence[BaseMessage]) -> str:
    sections = []
    for message in messages:
        sections.append(
            f"## {_message_role(message)}\n{_message_content(message).strip()}"
        )
    return "\n\n".join(sections).strip()


class CodexChatModel(BaseChatModel):
    """Expose the Codex App Server worker through LangChain's chat interface."""

    model_name: str = ""
    timeout_seconds: int = 600

    @property
    def _llm_type(self) -> str:
        return "codex-app-server"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model_name or "account-default",
            "timeout_seconds": self.timeout_seconds,
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
                self._agenerate(
                    messages,
                    stop=stop,
                    run_manager=None,
                    **kwargs,
                )
            )
        raise RuntimeError("CodexChatModel synchronous invoke cannot run inside an event loop")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop:
            raise ValueError("CodexChatModel does not support stop sequences")
        content = await run_codex_text(
            serialize_messages(messages),
            timeout_seconds=int(kwargs.get("timeout_seconds", self.timeout_seconds)),
            harness=str(kwargs.get("codex_harness", "general")),
            model=str(kwargs.get("model") or self.model_name).strip() or None,
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
            "CodexChatModel uses named App Server harnesses instead of LangChain tool binding"
        )


def is_codex_llm(llm: BaseChatModel) -> bool:
    return isinstance(llm, CodexChatModel)


def codex_invoke_options(
    llm: BaseChatModel,
    harness: str,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_codex_llm(llm):
        return {}
    options: dict[str, Any] = {"codex_harness": harness}
    if output_schema is not None:
        options["output_schema"] = output_schema
    return options
