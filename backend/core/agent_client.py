"""Dispatch named harness tasks to Codex or Pi workers."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from backend.core.codex_client import stream_codex_task
from backend.core.pi_client import stream_pi_task


async def stream_agent_task(
    prompt: str,
    *,
    backend: str,
    output_schema: dict[str, Any] | None = None,
    timeout_seconds: int = 900,
    harness: str = "general",
    model: str | None = None,
    model_config: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    if backend == "codex":
        async for message in stream_codex_task(
            prompt=prompt,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            harness=harness,
            model=model,
        ):
            yield message
        return

    if backend == "pi":
        if not model_config:
            raise ValueError("Pi model_config is required")
        async for message in stream_pi_task(
            prompt=prompt,
            model_config=model_config,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            harness=harness,
        ):
            yield message
        return

    raise ValueError(f"Unsupported agent backend: {backend}")
