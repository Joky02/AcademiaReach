"""Shared Serper API client with user-facing error messages."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx


class SerperAPIError(RuntimeError):
    """A Serper failure that is safe to surface in the UI."""


def _response_detail(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None

    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return re.sub(r"\s+", " ", response.text).strip()[:200]


def _error_message(status_code: int, detail: str) -> str:
    normalized = detail.lower()
    if "not enough credits" in normalized:
        return "Serper 搜索额度已用完，请充值或在设置中更换有额度的 API Key"
    if status_code in (401, 403):
        return "Serper API Key 无效或无权访问，请在设置中检查并更换"
    if status_code == 429:
        return "Serper 请求过于频繁，请稍后再试"
    if status_code == 400:
        suffix = f"：{detail}" if detail else ""
        return f"Serper 拒绝了搜索请求，请检查 API Key 和账户状态{suffix}"
    suffix = f"：{detail}" if detail else ""
    return f"Serper 搜索服务返回 HTTP {status_code}{suffix}"


async def search_serper(query: str, api_key: str, num: int = 10) -> list[dict]:
    """Run one Google search through Serper."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": num},
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
    except httpx.RequestError as exc:
        raise SerperAPIError(f"无法连接 Serper 搜索服务：{exc}") from exc

    if not response.is_success:
        detail = _response_detail(response)
        raise SerperAPIError(_error_message(response.status_code, detail))

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise SerperAPIError("Serper 返回了无法解析的响应，请稍后再试") from exc
    return data.get("organic", [])
