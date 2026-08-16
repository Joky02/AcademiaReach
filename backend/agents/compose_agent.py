"""邮件撰写 Agent — Deep Research + 个性化套磁邮件生成"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm import get_llm, load_profile, load_yaml_config
from backend.core.prompts import load_email_template, load_prompt
from backend.core.serper import SerperAPIError, search_serper
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
    return await search_serper(query, api_key, num=num)


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
        f'"{name}" {university} Google Scholar citations',
        f'"{name}" "{university}" "Cited by"',
        f'"{name}" {research.split(",")[0].strip() if research else ""} paper',
    ]

    all_results = []
    for q in queries:
        try:
            results = await _search_serper(q, serper_key, num=8)
            all_results.extend(results)
        except SerperAPIError as e:
            logger.warning("Serper unavailable during deep research for %s: %s", name, e)
            return f"（代表作检索暂不可用：{e}）"
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
        def _citation_count(paper: dict) -> int:
            value = paper.get("citation_count")
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                match = re.search(r"\d[\d,]*", value)
                if match:
                    return int(match.group(0).replace(",", ""))
            return -1

        papers = sorted(papers, key=_citation_count, reverse=True)
        lines.append("### Representative Papers")
        for p in papers:
            title = p.get("title", "Unknown")
            venue = p.get("venue", "")
            year = p.get("year", "")
            citation_count = _citation_count(p)
            citation_text = f", citations: {citation_count}" if citation_count >= 0 else ""
            summary = p.get("summary", "")
            lines.append(f"- **{title}** ({venue} {year}{citation_text}): {summary}")

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


def _format_chinese_teacher_name(name: str) -> str:
    """Return the name part used in 尊敬的X老师：."""
    cleaned = re.sub(r"\s+", "", str(name or "")).strip()
    cleaned = re.sub(r"(教授|老师)$", "", cleaned)
    return cleaned


def _strip_existing_chinese_salutation(paragraph: str) -> str:
    """Remove model-generated greetings so the formatter can add one canonical line."""
    text = paragraph.strip().lstrip("\u3000 ")
    patterns = [
        r"^尊敬的[^：:\n]{1,40}[：:]\s*",
        r"^尊敬的[^，,。！？!\n]{1,40}老师\s*",
        r"^[^，,。！？!\n]{1,40}老师您好[！!，,：:]?\s*",
        r"^[^，,。！？!\n]{1,40}老师好[！!，,：:]?\s*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, count=1)
    return text.strip()


def _format_chinese_email_body(body: str, professor_name: str) -> str:
    """Canonical Chinese email layout: salutation flush-left; paragraphs indented."""
    teacher_name = _format_chinese_teacher_name(professor_name)
    salutation = f"尊敬的{teacher_name}老师：" if teacher_name else "尊敬的老师："
    raw = str(body or "").replace("\\n", "\n").replace("\r\n", "\n")
    paragraphs = [
        re.sub(r"\s*\n\s*", " ", p).strip()
        for p in re.split(r"\n\s*\n+", raw)
        if p.strip()
    ]

    formatted_paragraphs = []
    for idx, paragraph in enumerate(paragraphs):
        text = _strip_existing_chinese_salutation(paragraph) if idx == 0 else paragraph.strip().lstrip("\u3000 ")
        if not text:
            continue
        formatted_paragraphs.append(f"\u3000\u3000{text}")

    if not formatted_paragraphs:
        return salutation
    return salutation + "\n\n" + "\n\n".join(formatted_paragraphs)


def _clean_english_paragraph(value: object) -> str:
    """Collapse model output to one plain-text paragraph."""
    text = str(value or "").replace("\\n", "\n").strip()
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _clean_english_salutation(value: object, professor_name: str) -> str:
    """Return only the name fragment used by `Dear Professor ...`."""
    text = _clean_english_paragraph(value)
    text = re.sub(r"^(?:dear\s+)?(?:professor|prof\.?|dr\.?)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[,.:;]+$", "", text).strip()
    if text:
        return text

    fallback = re.sub(
        r"^(?:professor|prof\.?|dr\.?)\s+",
        "",
        str(professor_name or "").strip(),
        flags=re.IGNORECASE,
    )
    return fallback.rstrip(",.:;").strip()


def _render_english_email(
    template: str,
    email_data: dict,
    professor_name: str,
) -> tuple[str, str]:
    """Render the private English template with only professor-specific fields."""
    normalized = str(template or "").replace("\r\n", "\n").strip()
    lines = normalized.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise ValueError("英文邮件模板第一行必须以 Subject: 开头")

    subject = lines[0].split(":", 1)[1].strip()
    body = "\n".join(lines[1:]).strip()
    if not subject or not body:
        raise ValueError("英文邮件模板缺少主题或正文")

    replacements = {
        "{{ professor_salutation }}": _clean_english_salutation(
            email_data.get("salutation"),
            professor_name,
        ),
        "{{ representative_work_paragraph }}": _clean_english_paragraph(
            email_data.get("representative_work_paragraph")
        ),
        "{{ research_fit_paragraph }}": _clean_english_paragraph(
            email_data.get("research_fit_paragraph")
        ),
    }
    for placeholder, value in replacements.items():
        if placeholder not in body:
            raise ValueError(f"英文邮件模板缺少占位符：{placeholder}")
        if not value:
            raise ValueError(f"英文邮件生成结果缺少字段：{placeholder}")
        body = body.replace(placeholder, value)

    if "{{" in body or "}}" in body:
        raise ValueError("英文邮件模板存在未解析占位符")
    if re.search(r"\[(?:Applicant|Institution|Country|Degree|Program|Advisor|Venue|Project|Company)", subject + body):
        raise ValueError("请先将英文 example 模板复制到本地并填写个人信息")

    paragraphs = [
        re.sub(r"[ \t]+\n", "\n", block).strip()
        for block in re.split(r"\n\s*\n+", body)
        if block.strip()
    ]
    return subject, "\n\n".join(paragraphs)


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
            teacher_name = _format_chinese_teacher_name(prof["name"])
            salutation_example = f"尊敬的{teacher_name}老师：" if teacher_name else "尊敬的老师："
            user_msg = f"""【导师基本信息】
{prof_info}

【导师研究参考资料（用于了解方向，不需要在邮件里逐篇分析）】
{research_result}

【申请者背景】
{profile}

请严格按 3 段自然段 + 1 段短签收的结构写一封中文套磁邮件。
关键要求：
- subject 使用「博士申请咨询：[具体研究方向]」格式，方括号内容换成申请者真实研究方向
- body 第一行必须顶格写「{salutation_example}」；称呼之后空一行；后面每个自然段和签收段都必须以两个中文全角空格开头
- 语言要像真人写给导师的短邮件：标准、清楚、克制；不要宣传稿口吻，不要 AI 套话，不要堆形容词
- 第一段：必须使用系统提示里的中文固定模板；不要再写「X老师您好」
- 第二段：选一个最匹配的项目，只讲做了什么/结论/能力收获；硬技能用顿号串在句子里，**禁止 Bullet 列表**
- 第三段（**最关键**）：先从【申请者背景】和第二段判断申请者的硕士方向、已有论文方向或希望博士阶段继续研究的方向，再从【导师研究参考资料】的 representative_papers 里挑一篇最能接上的代表作；同一方向下优先选引用数更高的工作。不要生搬硬套：只有自然相关时才给一个轻量的结合想法；如果连接牵强，就只提出一个可请教、可交流的问题。第三段不要提申请者具体论文标题或方法名，不要写“我的论文/方法受到您这项工作的启发”。不要写得很强势，不要给太多细节，不要做确定性断言；用“也许、可能、希望进一步请教”这类低风险表达。**representative_papers 真为空时**才退化为一句方向概括，绝不编造论文标题
- 签收：附简历 + 期待进一步交流 + 致谢 + 落款
- 总字数 360-480 字；通篇散文"""
        else:
            english_template = load_email_template("compose_en")
            user_msg = f"""[Professor Info]
{prof_info}

[Research Reference (for understanding their direction — do NOT analyze papers one by one in the email)]
{research_result}

[Applicant Background]
{profile}

[Fixed Email Template (for context only; do not repeat its fixed paragraphs)]
{english_template}

Write only the three JSON fields requested by the system prompt. The backend will insert them into the fixed template.
Key requirements:
- Use standard written academic English with no contractions. Keep it simple, concrete, and human; avoid AI-like phrasing, ornate adjectives, and generic admiration.
- representative_work_paragraph: infer the applicant's direction, then choose ONE naturally related representative work. Among similarly relevant works, prefer the more-cited one. Give one modest directional connection, without mentioning the applicant's paper title or method name and without claiming inspiration.
- research_fit_paragraph: state one future direction connected to the group and end by asking whether the applicant's background could fit.
- salutation: return only the reliable family-name form used after "Dear Professor".
- Never fabricate a paper title. If evidence is weak, discuss a verified direction instead.
- Do not repeat any sentence already present in the fixed template. No bullets, lists, Markdown, or AI clichés."""

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
            if lang == "cn":
                subject = email_data.get("subject", f"PhD Application - {prof['name']}")
                body = email_data.get("body", "")
                body = _format_chinese_email_body(body, prof["name"])
            else:
                subject, body = _render_english_email(
                    english_template,
                    email_data,
                    prof["name"],
                )

            draft = await db.create_draft({
                "professor_id": prof["id"],
                "subject": subject,
                "body": body,
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
