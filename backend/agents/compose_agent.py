"""邮件撰写 Agent — Deep Research + 个性化套磁邮件生成"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm import get_llm, load_profile, load_yaml_config
from backend.core.prompts import load_prompt
from backend.core import database as db

logger = logging.getLogger(__name__)

# ── Prompts 已抽到 backend/prompts/*.md，每次调用 load_prompt 实时读取 ──


def _get_compose_prompt(lang: str) -> str:
    """构建邮件撰写 prompt，注入用户自定义风格和额外要求"""
    cfg = load_yaml_config()
    prompts = cfg.get("prompts", {})

    base = load_prompt(f"compose_{lang}")
    if lang == "cn":
        style = prompts.get("compose_style_cn", "").strip()
        extra = prompts.get("compose_extra_cn", "").strip()
    else:
        style = prompts.get("compose_style_en", "").strip()
        extra = prompts.get("compose_extra_en", "").strip()

    additions = []
    if style:
        label = "用户风格要求" if lang == "cn" else "User style preference"
        additions.append(f"\n## {label}\n{style}")
    if extra:
        label = "用户额外要求" if lang == "cn" else "Additional user instructions"
        additions.append(f"\n## {label}\n{extra}")

    if additions:
        # Insert before the JSON return instruction
        return base + "\n".join(additions)
    return base


# ── Serper 搜索 ──────────────────────────────────────

async def _search_serper(query: str, api_key: str, num: int = 10) -> list[dict]:
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


async def _deep_research_professor(prof: dict, llm, serper_key: str) -> str:
    """
    对导师进行 deep research：搜索其代表作，用 LLM 分析论文并整理信息。
    返回格式化的研究分析文本，供邮件撰写 prompt 使用。
    """
    name = prof["name"]
    university = prof["university"]
    research = prof.get("research_summary", "") or ""

    # 构造搜索查询
    queries = [
        f'"{name}" {university} publications papers',
        f'"{name}" {research.split(",")[0].strip() if research else ""} paper',
    ]

    all_results = []
    for q in queries:
        try:
            results = await _search_serper(q, serper_key, num=8)
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Deep research 搜索失败 ({q}): {e}")
        await asyncio.sleep(0.3)

    if not all_results:
        return "（未搜索到该导师的详细论文信息）"

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

    # LLM 分析论文
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=load_prompt("research_analyze")),
            HumanMessage(content=f"导师: {name}\n学校: {university}\n研究方向: {research}\n\n搜索结果:\n{search_text}"),
        ])
        content = resp.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0].strip()
        research_data = json.loads(content)
    except Exception as e:
        logger.warning(f"Deep research LLM 分析失败 ({name}): {e}")
        return f"搜索到 {len(unique)} 条相关结果，但分析失败。原始信息:\n{search_text[:2000]}"

    # 格式化为文本
    lines = []
    papers = research_data.get("representative_papers", [])
    if papers:
        lines.append("### Representative Papers")
        for p in papers:
            title = p.get("title", "Unknown")
            venue = p.get("venue", "")
            year = p.get("year", "")
            summary = p.get("summary", "")
            lines.append(f"- **{title}** ({venue} {year}): {summary}")

    themes = research_data.get("research_themes", [])
    if themes:
        lines.append(f"\n### Research Themes: {', '.join(themes)}")

    focus = research_data.get("recent_focus", "")
    if focus:
        lines.append(f"\n### Recent Focus: {focus}")

    lab = research_data.get("lab_info", "")
    if lab:
        lines.append(f"\n### Lab/Team: {lab}")

    return "\n".join(lines) if lines else "（未提取到具体论文信息）"


def _detect_language(region: Optional[str]) -> str:
    """根据导师所在地区判断使用中文还是英文（学校所在地为中国大陆则用中文）"""
    if not region:
        return "en"
    r = region.strip().lower()
    cn_keywords = {"cn", "china", "中国", "中国大陆", "mainland china"}
    if r in cn_keywords or "china" in r:
        return "cn"
    return "en"


async def compose_emails(
    professor_ids: Optional[list[int]] = None,
) -> AsyncGenerator[dict, None]:
    """
    为导师列表生成套磁邮件草稿（异步生成器）。

    yield 的消息格式:
      {"type": "progress", "message": "..."}
      {"type": "draft", "data": {...}}
      {"type": "done", "total": N}
      {"type": "error", "message": "..."}
    """
    profile = load_profile()
    if not profile or profile.startswith("# 个人简介\n\n请在此填写"):
        yield {"type": "error", "message": "请先在 config/my_profile.md 中填写你的个人信息"}
        return

    # 获取待生成邮件的导师列表
    if professor_ids:
        professors = []
        for pid in professor_ids:
            p = await db.get_professor(pid)
            if p:
                professors.append(p)
    else:
        professors = await db.get_professors()

    if not professors:
        yield {"type": "error", "message": "没有找到导师数据，请先搜索或手动添加导师"}
        return

    # 检查已有草稿，避免重复生成
    existing_drafts = await db.get_drafts()
    existing_prof_ids = {d["professor_id"] for d in existing_drafts}

    professors = [p for p in professors if p["id"] not in existing_prof_ids]
    if not professors:
        yield {"type": "done", "total": 0, "message": "所有导师都已有草稿，无需重复生成"}
        return

    yield {"type": "progress", "message": f"将为 {len(professors)} 位导师生成套磁邮件（含 Deep Research）..."}

    llm = get_llm()
    cfg = load_yaml_config()
    serper_key = cfg.get("search", {}).get("serper_api_key", "")
    total_created = 0

    for i, prof in enumerate(professors):
        lang = _detect_language(prof.get("region"))
        system_prompt = _get_compose_prompt(lang)

        # ── Step 1: Deep Research ──
        yield {
            "type": "progress",
            "message": f"🔍 Deep Research ({i+1}/{len(professors)}): {prof['name']} @ {prof['university']}",
        }

        research_result = "（Serper API Key 未配置，跳过论文搜索）"
        if serper_key and serper_key != "your-serper-api-key":
            try:
                research_result = await _deep_research_professor(prof, llm, serper_key)
            except Exception as e:
                research_result = f"（Deep Research 出错: {e}）"
                logger.warning(f"Deep research failed for {prof['name']}: {e}")

        # ── Step 2: 组装 prompt 并生成邮件 ──
        yield {
            "type": "progress",
            "message": f"✉️ 正在撰写 ({i+1}/{len(professors)}): {prof['name']}",
        }

        prof_info = (
            f"姓名/Name: {prof['name']}\n"
            f"学校/University: {prof['university']}\n"
            f"院系/Department: {prof.get('department', 'N/A')}\n"
            f"研究方向/Research: {prof.get('research_summary', 'N/A')}\n"
            f"近期论文/Recent Papers: {prof.get('recent_papers', 'N/A')}\n"
            f"主页/Homepage: {prof.get('homepage', 'N/A')}\n"
            f"地区/Region: {prof.get('region', 'N/A')}"
        )

        if lang == "cn":
            user_msg = f"""【导师基本信息】
{prof_info}

【导师研究参考资料（用于了解方向，不需要在邮件里逐篇分析）】
{research_result}

【申请者背景】
{profile}

请严格按 3 段自然段 + 1 段短签收的结构写一封中文套磁邮件。
关键要求：
- subject 使用「博士申请咨询：[具体研究方向]」格式，方括号内容换成申请者真实研究方向
- 语言要像真人写给导师的短邮件：标准、清楚、克制；不要宣传稿口吻，不要 AI 套话，不要堆形容词
- 第一段：身份 + 来意 + 把申请者**最强信号**亮出来；不要暴露弱点
- 第二段：选一个最匹配的项目，只讲做了什么/结论/能力收获；硬技能用顿号串在句子里，**禁止 Bullet 列表**
- 第三段（**最关键**）：从【导师研究参考资料】的 representative_papers 里**挑一篇最相关的论文**，说出论文标题或一句话内容，并接一句具体的想法或问题（让导师感到"这个学生真读过我的东西"）；然后说明这正是联系他的原因。**representative_papers 真为空时**才退化为一句方向概括，绝不编造论文标题
- 签收：附简历 + 期待进一步交流 + 致谢 + 落款
- 总字数 280-420 字；通篇散文"""
        else:
            user_msg = f"""[Professor Info]
{prof_info}

[Research Reference (for understanding their direction — do NOT analyze papers one by one in the email)]
{research_result}

[Applicant Background]
{profile}

Write a cold email strictly as 3 content paragraphs + 1 short sign-off. Flowing prose only.
Key requirements:
- Use standard written academic English with no contractions. Keep it simple, concrete, and human; avoid AI-like phrasing, ornate adjectives, and generic admiration.
- Paragraph 1: identity, intent, AND surface the applicant's strongest signal. Never expose weaknesses.
- Paragraph 2: pick ONE most-relevant project; outcome + capabilities only, never process. Weave 3-4 skills into a sentence. NO bullets.
- Paragraph 3 (**the differentiator**): pick ONE paper from the [Research Reference] representative_papers, name it (title or a one-line description), then add a concrete thought or question about it — make the professor feel you actually read it. Then state that the alignment is why you are writing. **Only fall back to a direction summary if representative_papers is genuinely empty — never fabricate a paper title.**
- Sign-off: attached CV, offer to discuss, thanks, signature.
- Total 180-250 words. Plain prose throughout — no bullets, no lists, no Markdown, no AI clichés."""

        try:
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ])

            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]

            email_data = json.loads(content)
            subject = email_data.get("subject", f"PhD Application - {prof['name']}")

            draft = await db.create_draft({
                "professor_id": prof["id"],
                "subject": subject,
                "body": email_data.get("body", ""),
                "language": lang,
            })
            total_created += 1
            yield {"type": "draft", "data": {**draft, "professor_name": prof["name"]}}

        except json.JSONDecodeError:
            yield {"type": "progress", "message": f"⚠️ {prof['name']} 的邮件解析失败，跳过"}
        except Exception as e:
            yield {"type": "progress", "message": f"⚠️ {prof['name']} 生成出错: {e}"}

        await asyncio.sleep(1)  # 避免 API 限频

    yield {"type": "done", "total": total_created}
