"""导师搜索 Agent — LLM 自主 Tool Calling 驱动搜索"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from backend.core.llm import get_llm, load_yaml_config, load_profile
from backend.core.prompts import load_prompt
from backend.core import database as db

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

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


def _valid_email(value: str | None) -> bool:
    """Return True only for ordinary email addresses, not URLs or placeholders."""
    if not value:
        return False
    value = value.strip()
    return bool(EMAIL_RE.match(value)) and not value.endswith("@tbd")


async def _candidate_enrichment_search(
    name: str,
    university: str,
    department: str = "",
    research_hint: str = "",
) -> dict:
    """Search contact/Scholar/homepage signals and ask the enrichment prompt to extract fields."""
    global _serper_key, _progress_queue

    query_bits = [name, university]
    if department:
        query_bits.append(department)
    base = " ".join(f'"{bit}"' for bit in query_bits if bit)
    loose_base = " ".join(bit for bit in query_bits if bit)
    queries = [
        f"{base} email",
        f"{base} contact",
        f"{base} professor homepage",
        f"{base} site:scholar.google.com/citations",
        f"{base} Google Scholar citations",
    ]
    if research_hint:
        queries.append(f"{loose_base} {research_hint} recent papers")

    if _progress_queue:
        await _progress_queue.put({"type": "progress", "message": f"🧭 补全候选人: {name} @ {university}"})

    all_results = []
    for q in queries:
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"🔍 补全搜索: {q}"})
        try:
            all_results.extend(await search_serper(q, _serper_key, num=6))
        except Exception as e:
            logger.warning(f"Candidate enrichment search failed for '{q}': {e}")
        await asyncio.sleep(0.2)

    seen = set()
    unique = []
    for r in all_results:
        link = r.get("link", "")
        if link and link not in seen:
            seen.add(link)
            unique.append(r)

    if not unique:
        return {}

    search_text = "\n\n".join(
        f"Title: {r.get('title', '')}\nSnippet: {r.get('snippet', '')}\nLink: {r.get('link', '')}"
        for r in unique[:18]
    )
    known_info = f"姓名: {name}\n学校: {university}"
    if department:
        known_info += f"\n院系: {department}"
    if research_hint:
        known_info += f"\n研究方向线索: {research_hint}"

    try:
        resp = await get_llm().ainvoke([
            SystemMessage(content=load_prompt("enrich_professor")),
            HumanMessage(content=f"已知信息:\n{known_info}\n\n搜索结果:\n{search_text}\n\n请补全这位导师的信息。"),
        ])
        enriched = _parse_json_response(resp.content)
    except Exception as e:
        logger.warning(f"Candidate enrichment LLM failed for {name} @ {university}: {e}")
        return {}

    if not isinstance(enriched, dict):
        return {}
    email = enriched.get("email")
    if email and not _valid_email(email):
        enriched["email"] = None
    return enriched


@tool
async def enrich_candidate_info(
    name: str,
    university: str,
    department: str = "",
    research_hint: str = "",
) -> str:
    """Before saving a professor, search for verified email, homepage, Google Scholar, department, recent papers, region, and tags. Input: candidate name/university plus optional department or research_hint. Returns JSON. Do not fabricate missing fields."""
    if not name or not university:
        return "Error: name and university are required."
    enriched = await _candidate_enrichment_search(name, university, department, research_hint)
    return json.dumps(enriched, ensure_ascii=False)


@tool
async def save_professor(
    name: str,
    university: str,
    email: str = "",
    department: str = "",
    homepage: str = "",
    google_scholar: str = "",
    research_summary: str = "",
    recent_papers: str = "",
    region: str = "",
    tags: str = "[]",
) -> str:
    """Save a professor to the database. Required: name, university. Optional: email, department, homepage, google_scholar (Google Scholar profile URL), research_summary, recent_papers, region, tags (JSON array string like '["Fellow"]'). Do NOT fabricate info."""
    global _progress_queue
    if not name or not university:
        return "Error: name and university are required."
    # 黑名单：用户之前主动叉掉过的导师，不再保存
    if await db.is_blacklisted(name, university):
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"⛔ 跳过（黑名单）: {name} @ {university}"})
        return f"Skipped: {name} @ {university} is on the user's blacklist. Do NOT try to save this professor again — pick a different one."

    needs_enrichment = (
        not _valid_email(email)
        or not homepage
        or not google_scholar
        or not recent_papers
        or not research_summary
    )
    if needs_enrichment and _serper_key:
        enriched = await _candidate_enrichment_search(
            name=name,
            university=university,
            department=department,
            research_hint=research_summary,
        )
        email = email if _valid_email(email) else (enriched.get("email") or "")
        department = department or enriched.get("department") or ""
        homepage = homepage or enriched.get("homepage") or ""
        google_scholar = google_scholar or enriched.get("google_scholar") or ""
        research_summary = research_summary or enriched.get("research_summary") or ""
        recent_papers = recent_papers or enriched.get("recent_papers") or ""
        region = region or enriched.get("region") or ""
        if (not tags or tags == "[]") and enriched.get("tags"):
            tags = json.dumps(enriched["tags"], ensure_ascii=False)

    if not email:
        email = f"unknown-{name.lower().replace(' ', '.')}@tbd"
    prof_data = {
        "name": name, "email": email, "university": university,
        "department": department, "homepage": homepage,
        "google_scholar": google_scholar,
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
    """Get the current list of professors in the database, plus the user's blacklist of removed professors. Use this to check coverage, avoid duplicates, AND avoid re-recommending professors the user has already rejected."""
    professors = await db.get_professors()
    blacklist = await db.get_blacklist()
    lines = []
    if professors:
        lines.append(f"Total in DB: {len(professors)} professors")
        for p in professors[:50]:
            lines.append(f"- {p['name']} | {p['university']} | {p.get('region','?')} | {p.get('research_summary','?')}")
        if len(professors) > 50:
            lines.append(f"... and {len(professors) - 50} more")
    else:
        lines.append("Database is empty, no professors yet.")
    if blacklist:
        lines.append("")
        lines.append(f"⛔ Blacklist (removed by user, DO NOT re-save these — pick different people):")
        for b in blacklist[:50]:
            lines.append(f"- {b['name']} | {b['university']}")
        if len(blacklist) > 50:
            lines.append(f"... and {len(blacklist) - 50} more blacklisted")
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
        f'"{name}" "{university}" google scholar',
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
    if prof.get("google_scholar"):
        known_info += f"\nGoogle Scholar: {prof['google_scholar']}"

    try:
        resp = await llm.ainvoke([
            SystemMessage(content=load_prompt("enrich_professor")),
            HumanMessage(content=f"已知信息:\n{known_info}\n\n搜索结果:\n{search_text}\n\n请补全这位导师的信息。"),
        ])
        enriched = _parse_json_response(resp.content)
    except Exception as e:
        logger.error(f"Enrich LLM failed: {e}")
        return {"success": False, "message": f"LLM 分析失败: {e}"}

    # 构建更新字段
    # email: 只在原值为空 / 占位邮箱时才覆盖（保护用户手动改过的真实邮箱）
    # 其他字段: 只要 LLM 给出新值就覆盖（enrich 是用户主动触发的"刷新"动作，
    #   应当采纳更准确的搜索结果，否则首次搜索时填的粗糙摘要永远不会被更新）
    update_data = {}
    new_email = enriched.get("email")
    old_email = prof.get("email") or ""
    if new_email and (not old_email or old_email.endswith("@tbd")):
        update_data["email"] = new_email

    for field in ("department", "homepage", "google_scholar",
                  "research_summary", "recent_papers", "region"):
        new_val = enriched.get(field)
        if new_val:
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
    tools = [search_google, enrich_candidate_info, save_professor, get_existing_professors, get_user_profile]
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
