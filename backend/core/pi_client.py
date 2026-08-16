"""Unix-socket client for the isolated Pi SDK worker."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

DEFAULT_SOCKET = "/run/taoci-pi/worker.sock"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class PiWorkerError(RuntimeError):
    """Base error raised by the Pi worker client."""


class PiWorkerUnavailable(PiWorkerError):
    """Raised when the Pi worker socket cannot be reached."""


def socket_path() -> Path:
    return Path(os.getenv("TAOCI_PI_SOCKET", DEFAULT_SOCKET))


async def _connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    path = socket_path()
    try:
        return await asyncio.wait_for(
            asyncio.open_unix_connection(
                str(path),
                limit=MAX_RESPONSE_BYTES + 1,
            ),
            timeout=3,
        )
    except (FileNotFoundError, ConnectionRefusedError, asyncio.TimeoutError, OSError) as exc:
        raise PiWorkerUnavailable(
            f"Pi Worker 未运行或套接字不可访问：{path}"
        ) from exc


async def stream_pi_task(
    prompt: str,
    *,
    model_config: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
    timeout_seconds: int = 900,
    harness: str = "general",
) -> AsyncGenerator[dict[str, Any], None]:
    request_id = uuid.uuid4().hex
    reader, writer = await _connect()
    request = {
        "id": request_id,
        "action": "run",
        "prompt": prompt,
        "output_schema": output_schema,
        "harness": harness,
        "model": model_config,
        "timeout_seconds": timeout_seconds,
    }
    writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()

    try:
        # Give the worker a short grace period to abort the SDK session and
        # return its own precise timeout error.
        async with asyncio.timeout(max(30, timeout_seconds) + 5):
            while True:
                line = await reader.readline()
                if not line:
                    raise PiWorkerError("Pi Worker 在返回结果前断开连接")
                if len(line) > MAX_RESPONSE_BYTES:
                    raise PiWorkerError("Pi Worker 返回的数据过大")
                message = json.loads(line)
                if message.get("id") != request_id:
                    continue
                message_type = message.get("type")
                if message_type == "progress":
                    yield message
                elif message_type == "result":
                    yield message
                    return
                elif message_type == "error":
                    raise PiWorkerError(
                        str(message.get("message") or "Pi Worker 执行失败")
                    )
    except TimeoutError as exc:
        raise PiWorkerError(
            f"Pi 任务超过 {timeout_seconds} 秒，已停止"
        ) from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass


async def run_pi_text(
    prompt: str,
    *,
    model_config: dict[str, Any],
    timeout_seconds: int = 600,
    harness: str = "general",
    output_schema: dict[str, Any] | None = None,
) -> str:
    async for message in stream_pi_task(
        prompt=prompt,
        model_config=model_config,
        output_schema=output_schema,
        timeout_seconds=timeout_seconds,
        harness=harness,
    ):
        if message.get("type") == "result":
            content = message.get("content")
            if isinstance(content, str):
                return content
            data = message.get("data")
            if isinstance(data, dict) and isinstance(data.get("content"), str):
                return data["content"]
    raise PiWorkerError("Pi Worker 未返回文本结果")


async def get_pi_worker_status() -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    try:
        reader, writer = await _connect()
    except PiWorkerUnavailable as exc:
        return {"available": False, "message": str(exc)}

    try:
        writer.write(
            (
                json.dumps({"id": request_id, "action": "ping"}, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
        )
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=3)
        message = json.loads(line)
        data = message.get("data") if message.get("type") == "result" else {}
        return {"available": bool(data.get("ok")), **data}
    except Exception as exc:
        return {"available": False, "message": str(exc)}
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass
