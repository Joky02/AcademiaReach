"""Run Codex behind a local Unix socket without exposing Codex auth to Docker."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from contextlib import suppress
from pathlib import Path
from typing import Any

from openai_codex import AsyncCodex, Sandbox

LOGGER = logging.getLogger("taoci.codex_worker")
MAX_REQUEST_BYTES = 2 * 1024 * 1024
HEARTBEAT_SECONDS = 8

DEVELOPER_INSTRUCTIONS = """
You are the research-discovery worker for Taoci, a PhD outreach application.
Follow the requested JSON schema exactly. Use live web search and prefer primary,
public sources such as official university pages, personal homepages, publication
pages, Google Scholar, and CSRankings. Never fabricate a name, email address,
publication, affiliation, or URL. Return an empty string when a field cannot be
verified. Do not modify files or run shell commands.
""".strip()


def _json_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


async def _send(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    writer.write(_json_line(payload))
    await writer.drain()


class CodexWorker:
    def __init__(
        self,
        codex: AsyncCodex,
        workspace: Path,
        concurrency: int,
        model: str | None,
    ) -> None:
        self.codex = codex
        self.workspace = workspace
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.model = model

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        request_id = ""
        try:
            raw = await reader.readline()
            if not raw:
                return
            if len(raw) > MAX_REQUEST_BYTES:
                raise ValueError("request is too large")
            request = json.loads(raw)
            request_id = str(request.get("id") or "")
            action = request.get("action")
            if action == "ping":
                await _send(
                    writer,
                    {
                        "id": request_id,
                        "type": "result",
                        "data": {
                            "ok": True,
                            "concurrency": self.concurrency,
                        },
                    },
                )
                return
            if action != "run":
                raise ValueError(f"unsupported action: {action}")

            prompt = str(request.get("prompt") or "").strip()
            output_schema = request.get("output_schema")
            if not prompt:
                raise ValueError("prompt is required")
            if not isinstance(output_schema, dict):
                raise ValueError("output_schema must be an object")

            async with self.semaphore:
                await self._run_codex(request_id, prompt, output_schema, writer)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, BrokenPipeError):
            LOGGER.info("Codex worker client disconnected")
        except Exception as exc:
            LOGGER.exception("Codex worker request failed")
            with suppress(ConnectionError, BrokenPipeError):
                await _send(
                    writer,
                    {"id": request_id, "type": "error", "message": str(exc)},
                )
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _run_codex(
        self,
        request_id: str,
        prompt: str,
        output_schema: dict[str, Any],
        writer: asyncio.StreamWriter,
    ) -> None:
        await _send(
            writer,
            {"id": request_id, "type": "progress", "message": "Codex 已接收搜索任务"},
        )
        thread = await self.codex.thread_start(
            cwd=str(self.workspace),
            developer_instructions=DEVELOPER_INSTRUCTIONS,
            ephemeral=True,
            model=self.model,
            sandbox=Sandbox.read_only,
            config={"web_search": "live"},
        )
        turn = await thread.turn(prompt, output_schema=output_schema)
        run_task = asyncio.create_task(
            turn.run(),
            name=f"codex-run-{request_id}",
        )
        try:
            elapsed = 0
            while True:
                done, _ = await asyncio.wait({run_task}, timeout=HEARTBEAT_SECONDS)
                if run_task in done:
                    break
                elapsed += HEARTBEAT_SECONDS
                await _send(
                    writer,
                    {
                        "id": request_id,
                        "type": "progress",
                        "message": f"Codex 正在检索并核验公开来源（{elapsed} 秒）",
                    },
                )

            result = await run_task
            parsed = json.loads(result.final_response)
            await _send(
                writer,
                {
                    "id": request_id,
                    "type": "result",
                    "data": parsed,
                    "thread_id": getattr(thread, "id", None),
                },
            )
        except BaseException:
            if not run_task.done():
                with suppress(Exception):
                    await turn.interrupt()
                run_task.cancel()
                with suppress(asyncio.CancelledError):
                    await run_task
            raise


async def serve(args: argparse.Namespace) -> None:
    socket_path = Path(args.socket).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    async with AsyncCodex() as codex:
        worker = CodexWorker(
            codex=codex,
            workspace=workspace,
            concurrency=max(1, args.concurrency),
            model=args.model or None,
        )
        server = await asyncio.start_unix_server(
            worker.handle,
            path=str(socket_path),
            limit=MAX_REQUEST_BYTES + 1,
        )
        os.chmod(socket_path, 0o660)
        LOGGER.info("Codex worker listening on %s", socket_path)
        async with server:
            await stop_event.wait()

    with suppress(FileNotFoundError):
        socket_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Taoci host-side Codex worker")
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--workspace", required=True, help="Read-only Codex workspace")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("TAOCI_CODEX_CONCURRENCY", "2")),
    )
    parser.add_argument("--model", default=os.getenv("TAOCI_CODEX_MODEL", ""))
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("TAOCI_CODEX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(serve(parse_args()))


if __name__ == "__main__":
    main()
