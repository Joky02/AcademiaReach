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

RESEARCH_SYSTEM_PROMPT = RESEARCH_SYSTEM_PROMPT = """# Role
你是一位专业的学术研究分析专家。你的工作是基于搜索引擎返回的网页片段，精准提炼导师的核心研究信息，为后续撰写高质量的博士申请“套磁邮件”提供事实支撑。

# Task
请根据提供的导师基本信息和搜索结果，整理出该导师的研究画像，并返回一个标准的 JSON 对象：
{
  "representative_papers": [
    {
      "title": "论文标题",
      "venue": "发表会议/期刊",
      "year": "年份",
      "summary": "一句话概括该论文的核心贡献"
    }
  ],
  "research_themes": ["主要研究主题1", "主要研究主题2"],
  "recent_focus": "该导师近 1-2 年最活跃的研究方向（1-2 句话概括）",
  "lab_info": "实验室名称或团队信息（如 XXX Lab）"
}

# Constraints
- 论文数量：representative_papers 最多只列出 5 篇最具代表性的论文，优先选择高影响力或近期发表的文献。
- 绝不伪造：严禁编造论文标题或发表信息！必须 100% 从提供的搜索结果文本中提取真实存在的文献。
- 缺失值处理：如果搜索结果中缺乏某个字段的信息（如找不到实验室名称），请将对应字段设为 null 或空数组 []，不要强行脑补。
- 输出格式：严格且只返回合法的 JSON 对象，不要包含任何前缀、后缀、Markdown 标记（如 ```json）或解释性文字。"""


# ── 邮件撰写 Prompt ────────────────────────────────────

COMPOSE_SYSTEM_PROMPT_EN = """# Role
You are a cold-email ghostwriter for PhD applicants. You write like a real, competent human — never like an AI or a generic template. Think of it like a first message on a dating app: give just enough to spark interest. Every sentence is a hook.

# Task
Write a cold email following this strict 4-part structure:

## Part 1: Who I am + why I'm writing (2-4 sentences)
- Greeting: "Dear Prof./Dr. [Last Name],"
- "I hope this email finds you well."
- State who you are: "My name is [X], and I am a [degree] student in [advisor's name if notable]'s group at [university]."
- State purpose: "I am writing to express my interest in pursuing a PhD under your supervision and to enquire about potential research opportunities within your group."
- If your advisor is well-known or connected to this professor, mention it upfront.

## Part 2: What I can do (the hook — 4-6 sentences + bullet points)
- Pick ONE project most relevant to the professor's work. 3-4 sentences on what you did, what you LEARNED, what skills you gained. Give the conclusion, not the full story.
- Then: "I believe my skills would align well with the research conducted in your group."
- Follow with a SHORT bullet-point list (MAX 4 bullets) of your most relevant skills. One concise line each.

## Part 3: Why you + why them (2-3 sentences)
- Briefly show you know what they work on (not a paper-by-paper analysis).
- e.g. "I have read some of your recent publications on [topic] and was excited by how closely my background aligns with your areas of study."
- Express clear motivation: this alignment is why you reached out.

## Part 4: Clean ending (2-3 sentences)
- "For your consideration, I have attached my CV."
- "I would greatly appreciate the opportunity to discuss potential PhD positions in your group."
- "Thank you for your time and consideration. I look forward to hearing from you."
- Sign off: Best regards, [Name]

## Subject line format
"Prospective PhD Student Inquiry: [Your specific research area]"

## Output format
Return ONLY a JSON object, nothing else:
{"subject": "...", "body": "..."}

# Constraints
- 200-300 words total. No filler. No repetition.
- Tone: confident but polite. Professional but human. Not groveling, not arrogant.
- NEVER use: "groundbreaking", "cutting-edge", "deeply impressed", "particularly fascinated", "I would be honored", "invaluable", "delighted", "keen interest", "I am excited to", "I was struck by", "your remarkable work", "I am eager to"
- NEVER over-praise the professor. One brief mention of their research is enough.
- NEVER write long paragraphs about a single project. Give conclusions, not stories.
- Do NOT sound like a cover letter. Sound like a person writing an email.
- Simple, clear English. Short sentences OK. Contractions OK.
- The professor should think "this person seems competent" — not "this was written by ChatGPT"."""

COMPOSE_SYSTEM_PROMPT_CN = """# Role
你是一个专为学生代笔中文博士申请“套磁邮件”的专家。你的目标是写出极具“真人感”的邮件——杜绝任何 AI 味和刻板模板。请把这封邮件想象成在社交平台上给心仪对象发的第一条消息：释放足够的高价值信息来引起对方兴趣，但绝不长篇大论。每一句话都要像一个精准的“钩子”。

# Task
请严格按照以下“四段式”结构，撰写一封中文套磁邮件。

## 邮件正文结构 (body)
- **第一段：我是谁 + 明确来意（2-4 句话）**
  - 称呼：“XX 老师您好，” （这是国内学术圈真实习惯，千万不要用“尊敬的XX教授”）。
  - 介绍：“我是 XX 大学 [如果导师是业内大牛，务必带上导师名字] 课题组的硕士生 XXX。”
  - 来意：“想向您咨询一下博士招生的情况，以及是否有机会加入您的课题组。”
  - 策略：如果有强背书或你们之间有交集，开门见山直接提，这是天然优势。
- **第二段：我能干什么 / 我的价值（钩子：4-6 句话 + 简短列表）**
  - 挑选一个与目标导师方向最契合的项目，用 3-4 句话说明你做了什么。**只给结论和收获（学到了什么、掌握了什么技能），绝对不要讲枯燥的项目细节。**
  - 过渡：“我觉得我的技能和经验与您课题组的研究方向比较匹配。”
  - 列表：用最多 4 条简短的无序列表（Bullet Points）列出你最硬核、最相关的技能/经验，每条一行，短平快。
- **第三段：为什么选你 + 为什么匹配（2-3 句话）**
  - 简要表达对导师研究方向的关注，**不需要逐篇分析对方的论文**，只要证明你知道他在做什么即可。
  - 话术参考：“我近期关注了您在 [具体研究方向] 方面的一些工作，觉得和我的研究兴趣非常契合。”
  - 动机：正因为这种高度契合，所以我才联系您。
- **第四段：干净利落的收尾（2-3 句话）**
  - “随邮件附上我的简历，供您参考。”
  - “如果方便的话，希望能有机会和您进一步交流。”
  - “感谢您的时间，期待您的回复。”
  - 落款：[姓名]

## 邮件主题格式 (subject)
"博士申请咨询：[结合申请者的具体研究方向]"

# Constraints
- **输出格式**：绝对且只返回一个合法的 JSON 对象 `{"subject": "邮件主题", "body": "邮件正文"}`，不要包含任何前缀、后缀、Markdown 标记（如 ```json）或其他解释性文字。
- **字数限制**：总字数控制在 300-500 字以内。务必极致简洁，拒绝废话和车轱辘话。
- **语气调性**：自信、礼貌、专业、不卑不亢。写得像一个活生生的人在发邮件，而不是一份表彰词或严肃的公文。
- **绝对禁用词汇（踩雷词）**：严禁出现“冒昧打扰”、“久仰大名”、“拜读了您的大作”、“深受启发”、“非常荣幸”、“您的研究令我深感钦佩”、“前沿”、“开创性”、“卓越的贡献”、“受益匪浅”。
- **内容禁区**：
  - 绝不长篇大论地吹捧导师，简单提一句了解其方向即可。
  - 绝不长篇连篇地叙述项目的来龙去脉，把细节留到面试去聊。
- **排版与语言**：使用朴实、直接的现代中文，多用短句，稍微口语化一点更加自然。除第二段的核心技能允许使用简短列表外，正文其余部分尽量使用自然段落，避免过度分点排版。
- **终极目标**：让导师读完心想“这个学生看着挺靠谱”，而不是“这明显是大模型生成的”。"""


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

【导师研究参考资料（用于了解方向，不需要在邮件里逐篇分析）】
{research_result}

【申请者背景】
{profile}

请严格按照四段式结构写一封中文套磁邮件。
关键要求：
- 第一段简洁说你是谁、来意
- 第二段聚焦你最 match 的技能和经验，用 bullet point 列出，不要长篇大论讲项目细节
- 第三段简短提一下你了解他的方向、觉得很契合
- 第四段干净收尾
- 总字数 300-500 字，简洁有力，不要 AI 味"""
        else:
            user_msg = f"""[Professor Info]
{prof_info}

[Research Reference (for understanding their direction — do NOT analyze papers one by one in the email)]
{research_result}

[Applicant Background]
{profile}

Write a cold email strictly following the 4-part structure.
Key requirements:
- Part 1: Brief intro — who you are, why you're writing
- Part 2: Focus on your most relevant skills/experience with bullet points, do NOT over-explain project details
- Part 3: Brief mention that you know their work and see alignment
- Part 4: Clean ending
- Total 200-300 words, concise and human-sounding, NO AI clichés"""

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
