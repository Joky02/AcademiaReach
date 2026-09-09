from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from codex_worker.server import CodexWorker, _is_stale_configuration_error


class _FreshCodexContext:
    def __init__(self, codex: object, enter_error: Exception | None = None) -> None:
        self.codex = codex
        self.enter_error = enter_error

    async def __aenter__(self) -> object:
        if self.enter_error:
            raise self.enter_error
        return self.codex

    async def __aexit__(self, *_args: object) -> None:
        return None


class CodexWorkerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_identifies_only_missing_configuration_files(self) -> None:
        self.assertTrue(
            _is_stale_configuration_error(
                RuntimeError(
                    "JSON-RPC error -32600: failed to load configuration: "
                    "No such file or directory (os error 2)"
                )
            )
        )
        self.assertTrue(
            _is_stale_configuration_error(
                RuntimeError(
                    "Codex process closed stdout. stderr_tail=Error: "
                    "error loading default config after config error: "
                    "No such file or directory (os error 2)"
                )
            )
        )
        self.assertFalse(
            _is_stale_configuration_error(RuntimeError("model request failed"))
        )

    async def test_retries_stale_app_server_with_fresh_process(self) -> None:
        worker = CodexWorker(
            workspace=Path("/tmp"),
            concurrency=2,
            model=None,
        )
        fresh_codex = object()
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()

        with (
            patch.object(
                worker,
                "_run_with_codex",
                new=AsyncMock(return_value=None),
            ) as run_with_codex,
            patch(
                "codex_worker.server.AsyncCodex",
                return_value=_FreshCodexContext(fresh_codex),
            ),
        ):
            await worker._run_codex(
                "request-1",
                "prompt",
                "search",
                None,
                None,
                writer,
            )

        run_with_codex.assert_awaited_once()
        self.assertIs(run_with_codex.await_args.args[0], fresh_codex)

    async def test_retries_transient_fresh_process_initialization(self) -> None:
        worker = CodexWorker(
            workspace=Path("/tmp"),
            concurrency=2,
            model=None,
        )
        stale = RuntimeError(
            "error loading default config after config error: "
            "No such file or directory (os error 2)"
        )
        fresh_codex = object()
        writer = MagicMock()

        with (
            patch.object(
                worker,
                "_run_with_codex",
                new=AsyncMock(return_value=None),
            ) as run_with_codex,
            patch(
                "codex_worker.server.AsyncCodex",
                side_effect=[
                    _FreshCodexContext(object(), enter_error=stale),
                    _FreshCodexContext(fresh_codex),
                ],
            ),
            patch("codex_worker.server.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            await worker._run_with_fresh_codex(
                "request-2",
                "prompt",
                "compose",
                None,
                None,
                writer,
                {"web_search": False, "instructions": "compose"},
                {"web_search": "disabled"},
            )

        sleep.assert_awaited_once_with(0.5)
        run_with_codex.assert_awaited_once()
        self.assertIs(run_with_codex.await_args.args[0], fresh_codex)


if __name__ == "__main__":
    unittest.main()
