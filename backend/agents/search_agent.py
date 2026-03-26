"""导师搜索 Agent — 自主决策式搜索，LLM 规划搜索策略并多轮迭代补充导师库"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm import get_llm, load_yaml_config, load_profile
from backend.core import database as db

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3          # 最多搜索轮数
QUERIES_PER_ROUND = 5   # 每轮最多搜索条数
RESULTS_PER_QUERY = 10  # 每条查询返回结果数

# ── Prompt: 规划搜索查询 ──────────────────────────────

PLAN_SYSTEM_PROMPT_BASE = """你是一个博士申请导师搜索策略专家。你需要根据用户的研究背景、目标地区
以及已有的导师库，智能规划下一步的 Google 搜索查询。

你的目标是帮用户找到与其研究方向匹配的、正在招 PhD 的教授。

分析时请考虑：
1. 用户的研究兴趣和已有导师覆盖了哪些方向/学校/地区
2. 哪些重要方向或目标地区还缺少导师
3. 搜索查询应该精准、具体，能找到教授个人主页或学校页面

{user_search_preference}

请返回一个 JSON 对象，格式如下：
{{
  "analysis": "对当前导师库的简要分析（中文，2-3句话）",
  "queries": ["搜索查询1", "搜索查询2", ...],
  "stop": false
}}

- queries: 最多 5 条 Google 搜索查询（英文），每条应精准定位某个方向+地区的教授
- stop: 如果你认为导师库已经足够丰富，不需要再搜索了，设为 true 并返回空 queries

只返回 JSON，不要其他文字。"""


def _get_plan_prompt() -> str:
    """构建搜索规划 prompt，注入用户自定义偏好"""
    cfg = load_yaml_config()
    prompts = cfg.get("prompts", {})
    pref = prompts.get("search_preference", "").strip()
    extra = f"用户特别要求：\n{pref}" if pref else ""
    return PLAN_SYSTEM_PROMPT_BASE.format(user_search_preference=extra)


# ── Prompt: 从搜索结果中提取导师 ─────────────────────

EXTRACT_SYSTEM_PROMPT = """你是一个学术信息提取专家。从 Google 搜索结果中提取博士导师信息。

对于每位导师，返回 JSON 数组，每个元素包含：
- name: 导师全名
- email: 邮箱地址（如果能找到）
- university: 所在大学
- department: 院系
- homepage: 个人主页 URL
- research_summary: 研究方向摘要（50字以内）
- recent_papers: 近期代表性论文（最多3篇，用分号分隔）
- region: 导师当前任职学校所在的国家/地区（如 China, US, UK, Singapore, Hong Kong 等）。注意：以学校所在地为准，而非导师国籍。

规则：
- 只提取大学教授/研究员，不要学生或公司研究员
- region 必须填写导师当前任职学校所在的国家或地区，不是导师的国籍
- 如果某个字段找不到信息，设为 null
- 邮箱找不到时也要保留该导师（email 设为 null），后续可以手动补充
- 不要编造信息，只从搜索结果中提取

只返回 JSON 数组，不要其他文字。"""


# ── 工具函数 ──────────────────────────────────────────

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


def _format_existing_professors(professors: list[dict]) -> str:
    """将已有导师列表格式化为文本摘要"""
    if not professors:
        return "（导师库为空，尚无任何导师）"
    lines = []
    for p in professors[:50]:  # 最多展示 50 位
        lines.append(f"- {p['name']} | {p['university']} | {p.get('region', '?')} | {p.get('research_summary', '?')}")
    summary = f"共 {len(professors)} 位导师"
    if len(professors) > 50:
        summary += f"（仅展示前 50 位）"
    return f"{summary}\n" + "\n".join(lines)


def _parse_json_response(content: str) -> any:
    """解析 LLM 返回的 JSON（处理 markdown 代码块包裹）"""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()
    return json.loads(content)


# ── 主流程 ────────────────────────────────────────────

async def search_professors(
    keywords: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    max_results: int = 20,
) -> AsyncGenerator[dict, None]:
    """
    自主决策式导师搜索（异步生成器，逐步 yield 进度消息）。

    流程：
      1. LLM 分析用户 profile + 已有导师库 → 规划搜索查询
      2. 执行搜索 → LLM 提取导师信息 → 存入数据库
      3. LLM 评估是否需要继续 → 重复或停止

    yield 的消息格式:
      {"type": "progress", "message": "..."}
      {"type": "professor", "data": {...}}
      {"type": "done", "total": N}
      {"type": "error", "message": "..."}
    """
    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {})
    serper_key = search_cfg.get("serper_api_key", "")

    if not serper_key or serper_key == "your-serper-api-key":
        yield {"type": "error", "message": "请先在 config.yaml 中配置 Serper API Key"}
        return

    profile = load_profile()
    keywords = keywords or search_cfg.get("keywords", [])
    regions = regions or search_cfg.get("regions", [])
    llm = get_llm()

    total_saved = 0

    for round_num in range(1, MAX_ROUNDS + 1):
        yield {"type": "progress", "message": f"═══ 第 {round_num}/{MAX_ROUNDS} 轮搜索 ═══"}

        # ── Step 1: LLM 规划搜索策略 ──
        yield {"type": "progress", "message": "Agent 正在分析导师库，规划搜索策略..."}

        existing = await db.get_professors()
        existing_text = _format_existing_professors(existing)

        hint_keywords = f"\n用户关注的研究方向: {', '.join(keywords)}" if keywords else ""
        hint_regions = f"\n用户目标地区: {', '.join(regions)}" if regions else ""

        plan_msg = f"""用户研究背景:
{profile[:1500]}
{hint_keywords}{hint_regions}

当前导师库:
{existing_text}

请分析当前导师库的覆盖情况，规划接下来的搜索查询。
目标：找到与用户研究方向匹配的、不同学校和地区的博士导师，避免重复已有导师。"""

        try:
            plan_resp = await llm.ainvoke([
                SystemMessage(content=_get_plan_prompt()),
                HumanMessage(content=plan_msg),
            ])
            plan = _parse_json_response(plan_resp.content)
        except Exception as e:
            yield {"type": "error", "message": f"Agent 规划失败: {e}"}
            break

        analysis = plan.get("analysis", "")
        queries = plan.get("queries", [])[:QUERIES_PER_ROUND]
        should_stop = plan.get("stop", False)

        yield {"type": "progress", "message": f"Agent 分析: {analysis}"}

        if should_stop or not queries:
            yield {"type": "progress", "message": "Agent 判断导师库已足够丰富，停止搜索。"}
            break

        yield {"type": "progress", "message": f"Agent 规划了 {len(queries)} 条搜索查询"}

        # ── Step 2: 执行搜索 ──
        all_results = []
        for i, query in enumerate(queries):
            yield {"type": "progress", "message": f"搜索 ({i+1}/{len(queries)}): {query}"}
            try:
                results = await search_serper(query, serper_key, num=RESULTS_PER_QUERY)
                all_results.extend(results)
            except Exception as e:
                yield {"type": "progress", "message": f"搜索出错: {e}"}
            await asyncio.sleep(0.3)

        if not all_results:
            yield {"type": "progress", "message": "本轮未获得任何搜索结果，跳过。"}
            continue

        # 去重
        seen = set()
        unique = []
        for r in all_results:
            link = r.get("link", "")
            if link and link not in seen:
                seen.add(link)
                unique.append(r)

        yield {"type": "progress", "message": f"获得 {len(unique)} 条不重复结果，Agent 正在提取导师信息..."}

        # ── Step 3: LLM 提取导师 ──
        search_text = "\n\n".join(
            f"Title: {r.get('title', '')}\nSnippet: {r.get('snippet', '')}\nLink: {r.get('link', '')}"
            for r in unique[:20]
        )

        extract_msg = f"""用户研究背景:
{profile[:500]}

搜索结果:
{search_text}

请提取与用户研究方向相关的导师信息。"""

        try:
            extract_resp = await llm.ainvoke([
                SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=extract_msg),
            ])
            professors = _parse_json_response(extract_resp.content)
        except json.JSONDecodeError as e:
            yield {"type": "progress", "message": f"LLM 返回格式解析失败: {e}，跳过本轮。"}
            continue
        except Exception as e:
            yield {"type": "error", "message": f"LLM 提取失败: {e}"}
            break

        # ── Step 4: 保存到数据库 ──
        round_saved = 0
        for prof_data in professors:
            if not prof_data.get("name") or not prof_data.get("university"):
                continue
            if not prof_data.get("email"):
                prof_data["email"] = f"unknown-{prof_data['name'].lower().replace(' ', '.')}@tbd"
            prof_data["source"] = "auto"
            try:
                saved = await db.create_professor(prof_data)
                round_saved += 1
                total_saved += 1
                yield {"type": "professor", "data": saved}
            except Exception:
                pass  # 重复邮箱被 UNIQUE 约束拦截

        yield {"type": "progress", "message": f"本轮新增 {round_saved} 位导师"}

        if total_saved >= max_results:
            yield {"type": "progress", "message": f"已达到目标数量 {max_results}，停止搜索。"}
            break

    yield {"type": "done", "total": total_saved}
