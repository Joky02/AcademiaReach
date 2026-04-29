"""导师搜索 Agent — LLM 自主 Tool Calling 驱动搜索"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from backend.core.llm import get_llm, load_yaml_config, load_profile
from backend.core.prompts import load_prompt
from backend.core import database as db

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25

# ── Agent 共享状态（每次运行时设置）─────────────────────

_serper_key: str = ""
_progress_queue: Optional[asyncio.Queue] = None


# ── Tool 定义 ──────────────────────────────────────────

@tool
async def search_google(query: str) -> str:
    """Search Google for academic information. Input: an English search query. Returns titles, snippets, and links. Use this to find professor homepages, publications, and contact info."""
    global _serper_key, _progress_queue
    if _progress_queue:
        await _progress_queue.put({"type": "progress", "message": f"🔍 搜索: {query}"})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": 10},
                headers={"X-API-KEY": _serper_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            results = resp.json().get("organic", [])
    except Exception as e:
        return f"搜索出错: {e}"
    if not results:
        return "No results found."
    return "\n\n".join(
        f"Title: {r.get('title','')}\nSnippet: {r.get('snippet','')}\nLink: {r.get('link','')}"
        for r in results[:10]
    )


@tool
async def save_professor(
    name: str,
    university: str,
    email: str = "",
    department: str = "",
    homepage: str = "",
    research_summary: str = "",
    recent_papers: str = "",
    region: str = "",
    tags: str = "[]",
) -> str:
    """Save a professor to the database. Required: name, university. Optional: email, department, homepage, research_summary, recent_papers, region, tags (JSON array string like '["Fellow"]'). Do NOT fabricate info."""
    global _progress_queue
    if not name or not university:
        return "Error: name and university are required."
    if not email:
        email = f"unknown-{name.lower().replace(' ', '.')}@tbd"
    prof_data = {
        "name": name, "email": email, "university": university,
        "department": department, "homepage": homepage,
        "research_summary": research_summary, "recent_papers": recent_papers,
        "region": region, "source": "auto",
    }
    if tags and tags != "[]":
        prof_data["tags"] = tags
    try:
        saved = await db.create_professor(prof_data)
        if _progress_queue:
            await _progress_queue.put({"type": "professor", "data": saved})
        return f"✅ Saved: {name} @ {university} (ID: {saved.get('id', '?')})"
    except Exception as e:
        return f"Save failed (possibly duplicate): {e}"


@tool
async def get_existing_professors() -> str:
    """Get the current list of professors in the database. Use this to check coverage and avoid saving duplicates."""
    professors = await db.get_professors()
    if not professors:
        return "Database is empty, no professors yet."
    lines = [f"Total: {len(professors)} professors"]
    for p in professors[:50]:
        lines.append(f"- {p['name']} | {p['university']} | {p.get('region','?')} | {p.get('research_summary','?')}")
    if len(professors) > 50:
        lines.append(f"... and {len(professors) - 50} more")
    return "\n".join(lines)


@tool
async def get_user_profile() -> str:
    """Get the applicant's personal profile including research interests, education, and skills. Use this to understand what kind of professors to search for."""
    profile = load_profile()
    if not profile or profile.startswith("# 个人简介\n\n请在此填写"):
        return "User profile not filled in yet."
    return profile[:2000]


# ── Agent 系统 Prompt 构建 ─────────────────────────────

def _build_search_system_prompt() -> str:
    """构建搜索 Agent 的系统 Prompt，注入用户配置"""
    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {})
    prompts = cfg.get("prompts", {})
    parts = []
    kw = search_cfg.get("keywords", [])
    rg = search_cfg.get("regions", [])
    pref = prompts.get("search_preference", "").strip()
    if kw:
        parts.append(f"研究方向关键词: {', '.join(kw)}")
    if rg:
        parts.append(f"目标地区: {', '.join(rg)}")
    if pref:
        parts.append(f"用户特别要求: {pref}")
    extra = "\n".join(parts)
    template = load_prompt("search_system")
    return template.replace("{extra}", extra)


# ── 共用工具函数 ──────────────────────────────────────

async def search_serper(query: str, api_key: str, num: int = 10) -> list[dict]:
    """调用 Serper API 进行 Google 搜索"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": num},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("organic", [])



def _parse_json_response(content: str) -> any:
    """解析 LLM 返回的 JSON（处理 markdown 代码块包裹）"""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()
    return json.loads(content)


# ── 单个导师信息补全 ──────────────────────────────────


async def enrich_professor(prof_id: int) -> dict:
    """根据导师的已有信息（名字、学校等），搜索并补全详细信息"""
    from backend.core import database as db_mod

    prof = await db_mod.get_professor(prof_id)
    if not prof:
        return {"success": False, "message": "导师不存在"}

    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {})
    serper_key = search_cfg.get("serper_api_key", "")
    if not serper_key or serper_key == "your-serper-api-key":
        return {"success": False, "message": "请先配置 Serper API Key"}

    llm = get_llm()
    name = prof["name"]
    university = prof["university"]
    department = prof.get("department") or ""

    # 构造搜索查询
    queries = [
        f"{name} {university} professor homepage",
        f"{name} {university} {department} research email",
    ]

    all_results = []
    for q in queries:
        try:
            results = await search_serper(q, serper_key, num=8)
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Enrich search failed for '{q}': {e}")
        await asyncio.sleep(0.3)

    if not all_results:
        return {"success": False, "message": "未搜索到任何结果"}

    # 去重
    seen = set()
    unique = []
    for r in all_results:
        link = r.get("link", "")
        if link and link not in seen:
            seen.add(link)
            unique.append(r)

    search_text = "\n\n".join(
        f"Title: {r.get('title', '')}\nSnippet: {r.get('snippet', '')}\nLink: {r.get('link', '')}"
        for r in unique[:15]
    )

    known_info = f"姓名: {name}\n学校: {university}"
    if department:
        known_info += f"\n院系: {department}"
    if prof.get("homepage"):
        known_info += f"\n主页: {prof['homepage']}"

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=load_prompt("enrich_professor")),
            HumanMessage(content=f"已知信息:\n{known_info}\n\n搜索结果:\n{search_text}\n\n请补全这位导师的信息。"),
        ])
        enriched = _parse_json_response(resp.content)
    except Exception as e:
        logger.error(f"Enrich LLM failed: {e}")
        return {"success": False, "message": f"LLM 分析失败: {e}"}

    # 构建更新字段 — 只更新原来为空的字段
    update_data = {}
    field_map = ["email", "department", "homepage", "research_summary", "recent_papers", "region"]
    for field in field_map:
        new_val = enriched.get(field)
        old_val = prof.get(field)
        if new_val and (not old_val or old_val.endswith("@tbd")):
            update_data[field] = new_val

    # tags: 合并已有 + 新发现的
    new_tags = enriched.get("tags", [])
    if isinstance(new_tags, list) and new_tags:
        import json as _json
        old_tags_raw = prof.get("tags", "[]")
        try:
            old_tags = _json.loads(old_tags_raw) if isinstance(old_tags_raw, str) else (old_tags_raw or [])
        except Exception:
            old_tags = []
        merged = list(dict.fromkeys(old_tags + new_tags))  # 去重保序
        update_data["tags"] = json.dumps(merged, ensure_ascii=False)

    if update_data:
        await db_mod.update_professor_info(prof_id, update_data)

    return {"success": True, "updated_fields": list(update_data.keys())}


# ── 主流程：Agent Tool-Calling Loop ──────────────────────

async def search_professors(
    keywords: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    max_results: int = 20,
) -> AsyncGenerator[dict, None]:
    """
    LLM 自主 Tool Calling 驱动的导师搜索（异步生成器）。

    LLM 自主决定何时搜索、搜什么、保存谁，通过 Tool Calling 与外部工具交互。

    yield 的消息格式:
      {"type": "progress", "message": "..."}
      {"type": "professor", "data": {...}}
      {"type": "done", "total": N}
      {"type": "error", "message": "..."}
    """
    global _serper_key, _progress_queue

    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {})
    _serper_key = search_cfg.get("serper_api_key", "")

    if not _serper_key or _serper_key == "your-serper-api-key":
        yield {"type": "error", "message": "请先在 config.yaml 中配置 Serper API Key"}
        return

    _progress_queue = asyncio.Queue()

    llm = get_llm()
    tools = [search_google, save_professor, get_existing_professors, get_user_profile]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=_build_search_system_prompt()),
        HumanMessage(content=f"请开始搜索导师，目标找到约 {max_results} 位匹配的导师。"),
    ]

    yield {"type": "progress", "message": "🤖 Agent 已启动，正在自主规划搜索策略..."}

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            yield {"type": "error", "message": f"Agent LLM 调用失败: {e}"}
            break

        messages.append(response)

        # If LLM returns no tool calls → agent is done
        if not response.tool_calls:
            if response.content:
                yield {"type": "progress", "message": f"🤖 Agent 总结:\n{response.content}"}
            break

        # Execute each tool call
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            yield {"type": "progress", "message": f"⚡ 调用工具: {tool_name}"}

            fn = tool_map.get(tool_name)
            if fn:
                try:
                    result = await fn.ainvoke(tool_args)
                except Exception as e:
                    result = f"工具执行出错: {e}"
            else:
                result = f"未知工具: {tool_name}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

            # Drain progress queue (tools push messages here)
            while not _progress_queue.empty():
                yield await _progress_queue.get()

        await asyncio.sleep(0.3)

    _progress_queue = None
    all_profs = await db.get_professors()
    yield {"type": "done", "total": len(all_profs)}
