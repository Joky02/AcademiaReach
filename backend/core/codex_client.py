"""Unix-socket client for the host-side Codex worker."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

DEFAULT_SOCKET = "/run/taoci-codex/worker.sock"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class CodexWorkerError(RuntimeError):
    """Base error raised by the Codex worker client."""


class CodexWorkerUnavailable(CodexWorkerError):
    """Raised when the host worker socket cannot be reached."""


def socket_path() -> Path:
    return Path(os.getenv("TAOCI_CODEX_SOCKET", DEFAULT_SOCKET))


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
        raise CodexWorkerUnavailable(
            f"Codex Worker 未运行或套接字不可访问：{path}"
        ) from exc


async def stream_codex_task(
    prompt: str,
    output_schema: dict[str, Any],
    timeout_seconds: int = 900,
) -> AsyncGenerator[dict[str, Any], None]:
    request_id = uuid.uuid4().hex
    reader, writer = await _connect()
    request = {
        "id": request_id,
        "action": "run",
        "prompt": prompt,
        "output_schema": output_schema,
    }
    writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()

    try:
        async with asyncio.timeout(max(30, timeout_seconds)):
            while True:
                line = await reader.readline()
                if not line:
                    raise CodexWorkerError("Codex Worker 在返回结果前断开连接")
                if len(line) > MAX_RESPONSE_BYTES:
                    raise CodexWorkerError("Codex Worker 返回的数据过大")
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
                    raise CodexWorkerError(
                        str(message.get("message") or "Codex Worker 执行失败")
                    )
    except TimeoutError as exc:
        raise CodexWorkerError(
            f"Codex 搜索超过 {timeout_seconds} 秒，任务已停止"
        ) from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass


async def get_codex_worker_status() -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    try:
        reader, writer = await _connect()
    except CodexWorkerUnavailable as exc:
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
