"""Shared helpers for named task harness backends."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from backend.core.codex_llm import CodexChatModel, is_codex_llm
from backend.core.pi_llm import PiChatModel, is_pi_llm


def is_harness_llm(llm: BaseChatModel) -> bool:
    return is_codex_llm(llm) or is_pi_llm(llm)


def agent_invoke_options(
    llm: BaseChatModel,
    harness: str,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_harness_llm(llm):
        return {}
    options: dict[str, Any] = {"agent_harness": harness}
    if output_schema is not None:
        options["output_schema"] = output_schema
    return options


__all__ = [
    "CodexChatModel",
    "PiChatModel",
    "agent_invoke_options",
    "is_harness_llm",
]
