"""邮件撰写 Agent — Deep Research + 个性化套磁邮件生成"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm import get_llm, load_profile, load_yaml_config
from backend.core import database as db

logger = logging.getLogger(__name__)

# ── Deep Research: 论文分析 Prompt ─────────────────────

RESEARCH_SYSTEM_PROMPT = """你是一位学术研究分析专家。根据搜索结果，为后续撰写套磁邮件整理该导师的研究信息。

请返回一个 JSON 对象：
{
  "representative_papers": [
    {"title": "论文标题", "venue": "发表会议/期刊", "year": "年份", "summary": "一句话概括该论文的核心贡献"}
  ],
  "research_themes": ["主要研究主题1", "主要研究主题2", ...],
  "recent_focus": "该导师近 1-2 年最活跃的研究方向（1-2 句话）",
  "lab_info": "实验室名称或团队信息（如果能找到）"
}

规则：
- representative_papers 最多列 5 篇最有代表性的论文，优先选高影响力或高引用的
- 不要编造论文，只从搜索结果中提取真实存在的论文
- 如果信息不足，对应字段填 null 或空数组
- 只返回 JSON，不要其他文字。"""


# ── 邮件撰写 Prompt ────────────────────────────────────

COMPOSE_SYSTEM_PROMPT_EN = """You write PhD-application cold emails that demonstrate genuine understanding of the professor's work. The email should be substantive and detailed — NOT a generic template.

## Style rules (critical)
- Write like a thoughtful graduate student who has actually read the professor's papers.
- NEVER use filler phrases like "I am writing to express my interest", "I was deeply impressed", "I am particularly fascinated", "I would be honored", "your groundbreaking work". These scream AI.
- NEVER start with "I hope this email finds you well" or any similar cliché.
- Use simple, direct English. No flowery adjectives. No hollow praise.
- The subject line should be specific, e.g., "Prospective PhD Student — ML for Combinatorial Optimization"

## Required content (write in this order)
1. **Opening**: Get straight to the point. Name a specific paper or research direction of theirs and briefly state your understanding of its core contribution or insight. Show you actually read it.
2. **Connection**: Explain the concrete intersection between your research and theirs. What specific problems or methods do you share? Be technical and specific — mention paper names, methods, datasets if relevant.
3. **Your background**: Describe your most relevant research experiences and results. Don't just list — explain what you did, what the contribution was, and why it matters.
4. **Future vision**: Describe 1-2 specific research ideas or directions you'd like to explore in their group. These should be grounded in both your experience and their recent work — show you've thought about what the collaboration could look like.
5. **Closing**: A natural, low-pressure ask. "Would you be open to a brief chat?" or "I'd be happy to share more details about my work."
6. **Sign-off**: Name, school, degree.

## Length
- Be thorough. A good cold email with real substance is typically 300-500 words. Do NOT artificially shorten it. Quality and specificity matter more than brevity.
- Every sentence should carry information. No filler, no padding, no repetition.

Return a JSON object:
{"subject": "...", "body": "..."}
Only return the JSON, nothing else."""

COMPOSE_SYSTEM_PROMPT_CN = """你帮学生写博士申请套磁邮件。要求内容充实、有深度，展现出对导师研究的真正理解——不是泛泛而谈的模板。

## 风格要求（极其重要）
- 像一个认真研究过对方论文的硕士生在写邮件：自信、具体、有见解。
- 绝对禁止以下表达："冒昧打扰"、"久仰大名"、"拜读了您的大作"、"深受启发"、"非常荣幸"、"您的研究令我深感钦佩"。这些一看就是模板。
- 不要用"尊敬的XX教授"开头，直接用"XX老师您好"，这是国内学术圈的真实习惯。
- 用朴实、直接的中文。不要堆砌形容词。不要写得像申请书或表彰词。

## 必须包含的内容（按顺序写）
1. **开头**：直接说你为什么联系这位老师。提到他们的一篇具体论文或研究方向，并简要说出你对这篇论文核心贡献的理解。要让老师感觉你真的读过。
2. **研究交集**：具体解释你的研究和老师的研究有什么交集。什么具体问题、方法、技术是你们共同关注的？要有技术细节——提到论文名、方法名、数据集等。
3. **自我介绍**：描述你最相关的研究经历和成果。不要单纯罗列，要解释你做了什么、贡献是什么、为什么重要。
4. **未来想法**：描述 1-2 个你想在老师组里探索的具体研究方向或想法。这些想法要建立在你的经验和老师近期工作的基础上——展现你思考过合作的可能性。
5. **收尾**：自然、轻松的询问。"不知您是否方便抽空交流一下？"或"如果您觉得合适，我可以发送更详细的材料。"
6. **落款**：姓名、学校、学位。

## 篇幅
- 写充实。一封有真正内容的套磁邮件通常 400-800 字。不要刻意缩短。质量和具体性比简短更重要。
- 每句话都要有信息量。不要水字数，不要重复，不要空话。

以 JSON 格式返回：
{"subject": "邮件主题", "body": "邮件正文"}
只返回 JSON，不要其他任何文字。"""


def _get_compose_prompt(lang: str) -> str:
    """构建邮件撰写 prompt，注入用户自定义风格和额外要求"""
    cfg = load_yaml_config()
    prompts = cfg.get("prompts", {})

    if lang == "cn":
        base = COMPOSE_SYSTEM_PROMPT_CN
        style = prompts.get("compose_style_cn", "").strip()
        extra = prompts.get("compose_extra_cn", "").strip()
    else:
        base = COMPOSE_SYSTEM_PROMPT_EN
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
            SystemMessage(content=RESEARCH_SYSTEM_PROMPT),
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

【导师论文与研究深度分析】
{research_result}

【申请者背景】
{profile}

请根据以上全部信息，写一封充实、有深度的中文套磁邮件。
要求：
- 必须提到导师的具体论文并展现你对论文核心贡献的理解
- 必须具体分析你的研究和导师研究的交集
- 必须提出你想在导师组里做的 1-2 个具体研究方向/想法
- 不要 AI 味，像一个认真研究过对方工作的真人写的"""
        else:
            user_msg = f"""[Professor Info]
{prof_info}

[Deep Research — Professor's Publications & Analysis]
{research_result}

[Applicant Background]
{profile}

Write a substantive, detailed cold email based on ALL the above information.
Requirements:
- MUST reference specific papers by the professor and show genuine understanding of their contributions
- MUST analyze the concrete intersection between your research and theirs
- MUST propose 1-2 specific research directions/ideas you'd like to explore in their group
- No AI clichés, sound like a real person who has done their homework"""

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

            draft = await db.create_draft({
                "professor_id": prof["id"],
                "subject": email_data.get("subject", f"PhD Application - {prof['name']}"),
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
