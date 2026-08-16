"""导师搜索 Agent — LLM 自主 Tool Calling 驱动搜索"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import io
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from backend.core.llm import (
    get_llm,
    get_model_api_config,
    load_yaml_config,
    load_profile,
    resolve_agent_backend,
)
from backend.core.agent_llm import agent_invoke_options, is_harness_llm
from backend.core.prompts import load_prompt
from backend.core.agent_client import stream_agent_task
from backend.core.codex_client import CodexWorkerError
from backend.core.pi_client import PiWorkerError
from backend.core import database as db

logger = logging.getLogger(__name__)

CS_RANKINGS_CACHE_TTL_SECONDS = 6 * 60 * 60
CS_RANKINGS_FACULTY_URLS = (
    "https://csrankings.org/csrankings.csv",
    "https://raw.githubusercontent.com/emeryberger/CSRankings/gh-pages/csrankings.csv",
    "https://cdn.jsdelivr.net/gh/emeryberger/CSRankings@gh-pages/csrankings.csv",
)
CS_RANKINGS_INSTITUTION_URLS = (
    "https://csrankings.org/institutions.csv",
    "https://raw.githubusercontent.com/emeryberger/CSRankings/gh-pages/institutions.csv",
    "https://cdn.jsdelivr.net/gh/emeryberger/CSRankings@gh-pages/institutions.csv",
)

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
EMAIL_SEARCH_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

NON_MAINLAND_HINTS = ("hong kong", "macau", "macao", "taiwan", "香港", "澳门", "澳門", "台湾", "臺灣")
MAINLAND_REGION_HINTS = (
    "china",
    "mainland china",
    "prc",
    "people's republic of china",
    "中国",
    "中国大陆",
    "大陆",
)
MAINLAND_UNIVERSITY_HINTS = (
    "tsinghua",
    "peking university",
    "fudan",
    "zhejiang university",
    "shanghai jiao tong",
    "sjtu",
    "nju",
    "nanjing university",
    "ustc",
    "university of science and technology of china",
    "renmin",
    "harbin institute",
    "beihang",
    "tongji",
    "southeast university",
    "sun yat-sen",
    "sysu",
    "xidian",
    "nudt",
    "national university of defense technology",
    "chinese academy of sciences",
    "中国科学院",
    "清华",
    "北京大学",
    "复旦",
    "浙江大学",
    "上海交通",
    "南京大学",
    "中国科学技术大学",
    "国防科技大学",
)
COUNTRY_ABBR_TO_REGION = {
    "us": "US",
    "ca": "Canada",
    "cn": "China",
    "hk": "Hong Kong",
    "mo": "Macau",
    "sg": "Singapore",
    "tw": "Taiwan",
    "gb": "UK",
    "au": "Australia",
    "nz": "New Zealand",
    "jp": "Japan",
    "kr": "South Korea",
    "de": "Germany",
    "fr": "France",
    "ch": "Switzerland",
    "nl": "Netherlands",
    "se": "Sweden",
    "dk": "Denmark",
    "fi": "Finland",
    "no": "Norway",
    "it": "Italy",
    "es": "Spain",
    "il": "Israel",
    "in": "India",
}
REGION_ALIASES = {
    "US": {"us", "usa", "u.s.", "united states", "north america", "northamerica"},
    "China": {"cn", "china", "mainland china", "prc", "中国", "中国大陆", "大陆"},
    "Hong Kong": {"hk", "hong kong", "香港"},
    "Macau": {"mo", "macau", "macao", "澳门", "澳門"},
    "Singapore": {"sg", "singapore", "新加坡"},
    "Taiwan": {"tw", "taiwan", "台湾", "臺灣"},
    "UK": {"uk", "gb", "united kingdom", "britain", "england"},
}

# ── Agent 共享状态（每次运行时设置）─────────────────────

_progress_queue: Optional[asyncio.Queue] = None
_csrankings_cache: dict[str, Any] = {"loaded_at": 0.0, "faculty": None, "institutions": None}


# ── Tool 定义 ──────────────────────────────────────────

@tool
async def search_csrankings(
    keywords: str = "",
    regions: str = "",
    universities: str = "",
    limit: int = 20,
) -> str:
    """Search CSRankings faculty data for structured professor candidates. Args are comma-separated strings. CSRankings provides name, affiliation, homepage, Google Scholar ID, and ORCID, but usually not email or detailed research summaries. Use this to discover candidates, then call enrich_candidate_info before save_professor."""
    global _progress_queue

    keyword_terms = _split_query_terms(keywords)
    region_terms = _split_query_terms(regions)
    university_terms = _split_query_terms(universities)
    try:
        limit = max(1, min(int(limit or 20), 80))
    except Exception:
        limit = 20

    if _progress_queue:
        scope = []
        if region_terms:
            scope.append(f"地区={', '.join(region_terms)}")
        if university_terms:
            scope.append(f"学校={', '.join(university_terms)}")
        if keyword_terms:
            scope.append(f"方向线索={', '.join(keyword_terms)}")
        await _progress_queue.put({
            "type": "progress",
            "message": f"📚 查询 CSRankings 候选源{('（' + '；'.join(scope) + '）') if scope else ''}",
        })

    try:
        faculty_rows, institution_map, source_url = await _load_csrankings_data()
    except Exception as e:
        return f"CSRankings fetch failed: {e}. Continue with the Harness web search."

    existing = await db.get_professors()
    blacklist = await db.get_blacklist()

    def norm_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())

    def norm_url(value: Any) -> str:
        return str(value or "").strip().lower().rstrip("/")

    existing_name_uni = {
        (norm_key(p.get("name")), norm_key(p.get("university")))
        for p in existing
        if p.get("name") and p.get("university")
    }
    existing_homepages = {norm_url(p.get("homepage")) for p in existing if p.get("homepage")}
    existing_scholars = {norm_url(p.get("google_scholar")) for p in existing if p.get("google_scholar")}
    blacklisted = {
        (norm_key(b.get("name")), norm_key(b.get("university")))
        for b in blacklist
        if b.get("name") and b.get("university")
    }

    candidates: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, str, str, str]] = set()
    for row in faculty_rows:
        name = _clean_csrankings_name(row.get("name"))
        university = _clean_csrankings_value(row.get("affiliation"))
        if not name or not university:
            continue

        institution_meta = institution_map.get(university) or {}
        region_label = _region_label_for_institution(university, institution_map)
        if not _matches_csrankings_region(region_terms, region_label, university, institution_meta):
            continue

        university_text = " ".join([
            university,
            institution_meta.get("homepage") or "",
            region_label,
            institution_meta.get("countryabbrv") or "",
        ]).lower()
        if university_terms and not any(term.lower() in university_text for term in university_terms):
            continue

        homepage = _clean_csrankings_value(row.get("homepage"))
        scholar = _csrankings_scholar_url(row.get("scholarid") or "")
        orcid = _clean_csrankings_value(row.get("orcid"))

        name_uni_key = (norm_key(name), norm_key(university))
        if name_uni_key in existing_name_uni or name_uni_key in blacklisted:
            continue
        if homepage and norm_url(homepage) in existing_homepages:
            continue
        if scholar and norm_url(scholar) in existing_scholars:
            continue

        candidate_key = (norm_key(name), norm_key(university), norm_url(homepage), norm_url(scholar))
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)

        text_blob = " ".join([name, university]).lower()
        keyword_hits = [term for term in keyword_terms if term.lower() in text_blob]
        score = 0
        if region_terms:
            score += 4
        if university_terms:
            score += 5
        if homepage:
            score += 2
        if scholar:
            score += 2
        score += len(keyword_hits)

        candidates.append({
            "name": name,
            "university": university,
            "department": "Computer Science",
            "region": region_label,
            "homepage": homepage,
            "google_scholar": scholar,
            "orcid": orcid if orcid and set(orcid) != {"0", "-"} else "",
            "source": "CSRankings",
            "notes": (
                "CSRankings faculty candidate. Verify current affiliation, email, "
                "research fit, and mainland Chinese name before saving."
            ),
            "_score": score,
            "_keyword_hits": keyword_hits,
        })

    selected = _round_robin_by_university(candidates, limit)
    for item in selected:
        item["keyword_hits"] = item.pop("_keyword_hits", [])
        item.pop("_score", None)

    if _progress_queue:
        await _progress_queue.put({
            "type": "progress",
            "message": f"📚 CSRankings 返回 {len(selected)} 位候选（已过滤本地已有记录和黑名单）",
        })

    return json.dumps({
        "source": "CSRankings",
        "source_url": source_url,
        "count": len(selected),
        "candidates": selected,
        "usage": (
            "For each promising candidate, call enrich_candidate_info with the CSRankings "
            "name, university, region, homepage/Scholar as evidence, then save only verified new professors."
        ),
    }, ensure_ascii=False)


def _plain_valid_email(value: str | None) -> bool:
    """Return True only for ordinary email addresses, not URLs or placeholders."""
    if not value:
        return False
    value = value.strip()
    return bool(EMAIL_RE.match(value)) and not value.endswith("@tbd")


def _normalize_email(value: str | None) -> str:
    """Normalize common anti-crawler email forms, e.g. name {at} uni {dot} edu."""
    if not value:
        return ""

    text = html.unescape(str(value)).strip()
    text = re.sub(r"(?i)^mailto:\s*", "", text)

    candidates = [text]
    obfuscated = text
    obfuscated = re.sub(r"(?i)\s*[\{\[\(<]\s*at\s*[\}\]\)>]\s*", "@", obfuscated)
    obfuscated = re.sub(r"(?i)\s*[\{\[\(<]\s*dot\s*[\}\]\)>]\s*", ".", obfuscated)
    obfuscated = re.sub(r"(?i)\s+(?:at)\s+", "@", obfuscated)
    obfuscated = re.sub(r"(?i)\s+(?:dot)\s+", ".", obfuscated)
    obfuscated = re.sub(r"\s*[＠@]\s*", "@", obfuscated)
    obfuscated = re.sub(r"\s*\.\s*", ".", obfuscated)
    candidates.append(obfuscated)

    for candidate in candidates:
        for match in EMAIL_SEARCH_RE.finditer(candidate):
            email = match.group(0).strip(".,;:)")
            if _plain_valid_email(email):
                return email

        compact = re.sub(r"\s+", "", candidate)
        if _plain_valid_email(compact):
            return compact

    return ""


def _valid_email(value: str | None) -> bool:
    return bool(_normalize_email(value))


def _has_cjk(value: str | None) -> bool:
    """Return True if a string contains a Chinese character."""
    return bool(value and CJK_RE.search(value))


def _is_mainland_china(region: str = "", university: str = "") -> bool:
    """Infer whether a professor is based in mainland China."""
    text = f"{region or ''} {university or ''}".lower()
    raw = f"{region or ''} {university or ''}"
    if any(hint in text or hint in raw for hint in NON_MAINLAND_HINTS):
        return False
    region_text = (region or "").strip().lower()
    if region_text in {"cn", "prc"}:
        return True
    if any(hint in region_text for hint in MAINLAND_REGION_HINTS):
        return True
    return any(hint in text or hint in raw for hint in MAINLAND_UNIVERSITY_HINTS)


def _split_query_terms(value: Any) -> list[str]:
    """Normalize tool args that may arrive as comma-separated strings or lists."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(_split_query_terms(item))
        return parts
    text = str(value)
    return [p.strip().strip('"').strip("'") for p in re.split(r"[,;|\n]+", text) if p.strip()]


def _clean_csrankings_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_csrankings_name(value: Any) -> str:
    # CSRankings follows DBLP disambiguation names such as "Name 0001".
    return re.sub(r"\s+\d{4}$", "", _clean_csrankings_value(value)).strip()


async def _fetch_first_available_csv(urls: tuple[str, ...]) -> tuple[list[dict[str, str]], str]:
    last_error = ""
    headers = {"User-Agent": "taoci-professor-search/1.0"}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                rows = list(csv.DictReader(io.StringIO(resp.text)))
                return rows, url
            except Exception as e:
                last_error = f"{url}: {e}"
                logger.warning(f"Failed to fetch CSRankings CSV from {url}: {e}")
    raise RuntimeError(last_error or "all CSRankings CSV URLs failed")


async def _load_csrankings_data() -> tuple[list[dict[str, str]], dict[str, dict[str, str]], str]:
    now = time.monotonic()
    faculty = _csrankings_cache.get("faculty")
    institutions = _csrankings_cache.get("institutions")
    loaded_at = float(_csrankings_cache.get("loaded_at") or 0)
    source = str(_csrankings_cache.get("source") or "")
    if faculty is not None and institutions is not None and now - loaded_at < CS_RANKINGS_CACHE_TTL_SECONDS:
        return faculty, institutions, source

    faculty_rows, faculty_source = await _fetch_first_available_csv(CS_RANKINGS_FACULTY_URLS)
    institution_rows, _ = await _fetch_first_available_csv(CS_RANKINGS_INSTITUTION_URLS)
    institution_map = {
        _clean_csrankings_value(row.get("institution")): {
            "region": _clean_csrankings_value(row.get("region")).lower(),
            "countryabbrv": _clean_csrankings_value(row.get("countryabbrv")).lower(),
            "homepage": _clean_csrankings_value(row.get("homepage")),
        }
        for row in institution_rows
        if _clean_csrankings_value(row.get("institution"))
    }

    _csrankings_cache.update({
        "loaded_at": now,
        "faculty": faculty_rows,
        "institutions": institution_map,
        "source": faculty_source,
    })
    return faculty_rows, institution_map, faculty_source


def _region_label_for_institution(university: str, institution_map: dict[str, dict[str, str]]) -> str:
    meta = institution_map.get(university) or {}
    abbr = (meta.get("countryabbrv") or "").lower()
    if abbr in COUNTRY_ABBR_TO_REGION:
        return COUNTRY_ABBR_TO_REGION[abbr]
    if _is_mainland_china("", university):
        return "China"
    return abbr.upper() if abbr else ""


def _matches_csrankings_region(
    target_terms: list[str],
    region_label: str,
    university: str,
    institution_meta: dict[str, str],
) -> bool:
    if not target_terms:
        return True

    haystack = {
        region_label.lower(),
        university.lower(),
        (institution_meta.get("region") or "").lower(),
        (institution_meta.get("countryabbrv") or "").lower(),
    }
    for target in target_terms:
        t = target.lower()
        if t in {"all", "world", "global", "the world", "any"}:
            return True
        aliases = REGION_ALIASES.get(region_label, {region_label.lower()})
        if t in aliases or any(t in item for item in haystack if item):
            return True
        for canonical, alias_set in REGION_ALIASES.items():
            if t in alias_set and canonical.lower() == region_label.lower():
                return True
    return False


def _csrankings_scholar_url(scholar_id: str) -> str:
    scholar_id = _clean_csrankings_value(scholar_id)
    if not scholar_id or scholar_id.upper() == "NOSCHOLARPAGE":
        return ""
    return f"https://scholar.google.com/citations?user={scholar_id}"


def _round_robin_by_university(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.get("university") or "", []).append(candidate)

    for group in groups.values():
        group.sort(key=lambda item: (-int(item.get("_score", 0)), item.get("name", "")))

    selected: list[dict[str, Any]] = []
    universities = sorted(groups, key=lambda uni: (-max(int(c.get("_score", 0)) for c in groups[uni]), uni))
    while len(selected) < limit and universities:
        next_universities = []
        for uni in universities:
            group = groups[uni]
            if group and len(selected) < limit:
                selected.append(group.pop(0))
            if group:
                next_universities.append(uni)
        universities = next_universities
    return selected


@tool
async def check_professor_exists(
    name: str,
    university: str,
    email: str = "",
    homepage: str = "",
    google_scholar: str = "",
) -> str:
    """Check whether a candidate professor is already in the local database by email, Google Scholar, non-generic homepage, or exact normalized name+university. Use this before enriching/saving when you suspect a candidate may already exist. If exists=true, skip this candidate and search for someone new."""
    if not name or not university:
        return "Error: name and university are required."
    candidate = {
        "name": name,
        "university": university,
        "email": _normalize_email(email),
        "homepage": homepage,
        "google_scholar": google_scholar,
    }
    match = await db.find_existing_professor_match(candidate)
    if not match:
        return json.dumps({"exists": False}, ensure_ascii=False)
    existing = match["professor"]
    return json.dumps({
        "exists": True,
        "id": existing.get("id"),
        "name": existing.get("name"),
        "university": existing.get("university"),
        "reason": match.get("reason"),
    }, ensure_ascii=False)


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
    recommended_papers: str = "[]",
    region: str = "",
    tags: str = "[]",
) -> str:
    """Save a professor to the database. Required: name, university. Email may be a standard address or an anti-crawler form like name {at} uni {dot} edu, which will be normalized. For mainland China professors, name must be the accurate Chinese name; for other regions, use English/romanized name. Optional: email, department, homepage, google_scholar, research_summary, recent_papers, recommended_papers JSON, region, tags. Do NOT fabricate info."""
    global _progress_queue
    if not name or not university:
        return "Error: name and university are required."
    email = _normalize_email(email)
    # 黑名单：用户之前主动叉掉过的导师，不再保存
    if await db.is_blacklisted(name, university):
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"⛔ 跳过（黑名单）: {name} @ {university}"})
        return f"Skipped: {name} @ {university} is on the user's blacklist. Do NOT try to save this professor again — pick a different one."

    if _is_mainland_china(region, university) and not _has_cjk(name):
        msg = (
            "Error: Mainland China professor must be saved with the accurate Chinese name. "
            "Please search the official Chinese university homepage/news/CV first, then call save_professor again with the Chinese name in the name field."
        )
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"⚠️ 未保存：{university} 的大陆导师需要先确认准确中文名"})
        return msg

    if await db.is_blacklisted(name, university):
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"⛔ 跳过（黑名单）: {name} @ {university}"})
        return f"Skipped: {name} @ {university} is on the user's blacklist. Do NOT try to save this professor again — pick a different one."

    prof_data = {
        "name": name, "email": email, "university": university,
        "department": department, "homepage": homepage,
        "google_scholar": google_scholar,
        "research_summary": research_summary, "recent_papers": recent_papers,
        "recommended_papers": _serialize_recommended_papers(recommended_papers),
        "region": region, "source": "auto",
        "tags": _new_professor_tags(tags),
    }

    match = await db.find_existing_professor_match(prof_data)
    if match:
        existing = match["professor"]
        if _progress_queue:
            await _progress_queue.put({
                "type": "progress",
                "message": f"↪️ 跳过已有导师：{existing.get('name')} @ {existing.get('university')}，继续找新人",
            })
        return (
            f"Skipped existing professor: {existing.get('name')} @ {existing.get('university')} "
            f"(ID: {existing.get('id')}, match: {match.get('reason')}). "
            "Do NOT update this record during search; find and save a different NEW professor."
        )

    if not email:
        safe_name = re.sub(r"[^a-z0-9.]+", ".", name.lower()).strip(".") or "professor"
        email = f"unknown-{safe_name}@tbd"
        prof_data["email"] = email

    try:
        saved = await db.create_professor(prof_data)
        if _progress_queue:
            await _progress_queue.put({"type": "professor", "data": saved})
        if saved.get("_deduped"):
            return (
                f"Skipped existing professor after final database dedupe: {saved.get('name', name)} "
                f"@ {saved.get('university', university)} (ID: {saved.get('id', '?')}). "
                "Continue searching for a different NEW professor."
            )
        return f"✅ Saved: {name} @ {university} (ID: {saved.get('id', '?')})"
    except Exception as e:
        return f"Save failed (possibly duplicate): {e}"


@tool
async def get_existing_professors() -> str:
    """Get a compact index of all professors already in the local database, plus the user's blacklist of removed professors. Use this before searching so you prioritize NEW professors and avoid wasting tool calls on existing records."""
    professors = await db.get_professors()
    blacklist = await db.get_blacklist()
    lines = []
    if professors:
        lines.append(f"Total in DB: {len(professors)} professors. Treat these as already covered; search for NEW people not listed here.")
        for p in professors[:500]:
            identity_bits = []
            if p.get("email") and _valid_email(p.get("email")):
                identity_bits.append(f"email={p['email']}")
            if p.get("google_scholar"):
                identity_bits.append("scholar=yes")
            if p.get("homepage"):
                identity_bits.append("homepage=yes")
            identity = f" | {'; '.join(identity_bits)}" if identity_bits else ""
            lines.append(f"- {p['id']}: {p['name']} | {p['university']} | {p.get('region','?')}{identity}")
        if len(professors) > 500:
            lines.append(f"... and {len(professors) - 500} more. Use check_professor_exists for any candidate before saving.")
    else:
        lines.append("Database is empty, no professors yet.")
    if blacklist:
        lines.append("")
        lines.append(f"⛔ Blacklist (removed by user, DO NOT re-save these — pick different people):")
        for b in blacklist[:50]:
            lines.append(f"- {b['name']} | {b['university']}")
        if len(blacklist) > 50:
            lines.append(f"... and {len(blacklist) - 50} more blacklisted")
    lines.append("")
    lines.append("Rule: if a candidate matches this index or check_professor_exists returns exists=true, skip the candidate and search for a different NEW professor.")
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

def _parse_json_response(content: str) -> any:
    """解析 LLM 返回的 JSON（处理 markdown 代码块包裹）"""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0].strip()
    return json.loads(content)


def _new_professor_tags(raw: Any) -> str:
    if isinstance(raw, list):
        tags = [str(tag).strip() for tag in raw if str(tag).strip()]
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            tags = (
                [str(tag).strip() for tag in parsed if str(tag).strip()]
                if isinstance(parsed, list)
                else []
            )
        except json.JSONDecodeError:
            tags = []
    else:
        tags = []
    return json.dumps(list(dict.fromkeys(["新", *tags])), ensure_ascii=False)


def _recommended_paper_schema() -> dict[str, Any]:
    nullable_integer = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "venue": {"type": "string"},
            "year": nullable_integer,
            "citation_count": nullable_integer,
            "url": {"type": "string"},
            "why_recommended": {"type": "string"},
        },
        "required": [
            "title",
            "venue",
            "year",
            "citation_count",
            "url",
            "why_recommended",
        ],
        "additionalProperties": False,
    }


def _normalize_recommended_papers(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []

    papers: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        reason = str(item.get("why_recommended") or "").strip()
        title_key = re.sub(r"\W+", "", title.lower())
        if (
            not title
            or not title_key
            or title_key in seen_titles
            or not url.startswith(("https://", "http://"))
            or not reason
        ):
            continue

        def optional_int(value: Any, minimum: int, maximum: int) -> int | None:
            if value is None or isinstance(value, bool):
                return None
            if isinstance(value, str):
                match = re.search(r"\d[\d,]*", value)
                if not match:
                    return None
                value = match.group(0).replace(",", "")
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return None
            return parsed if minimum <= parsed <= maximum else None

        seen_titles.add(title_key)
        papers.append({
            "title": title[:500],
            "venue": str(item.get("venue") or "").strip()[:160],
            "year": optional_int(item.get("year"), 1900, 2100),
            "citation_count": optional_int(
                item.get("citation_count"),
                0,
                10_000_000,
            ),
            "url": url[:2048],
            "why_recommended": reason[:1000],
        })
        if len(papers) >= 5:
            break
    return papers


def _serialize_recommended_papers(raw: Any) -> str:
    return json.dumps(_normalize_recommended_papers(raw), ensure_ascii=False)


def _applicant_recommendation_context() -> str:
    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {}) or {}
    prompt_cfg = cfg.get("prompts", {}) or {}
    keywords = search_cfg.get("keywords", []) or []
    preference = str(prompt_cfg.get("search_preference") or "").strip()
    profile = load_profile().strip()
    return (
        "申请者研究背景与申请需求（仅用于选择推荐论文，不得据此虚构导师信息）：\n"
        f"目标方向: {', '.join(str(value) for value in keywords) or '(未单独配置)'}\n"
        f"搜索偏好: {preference or '(未单独配置)'}\n"
        f"Profile:\n{profile[:6000] or '(未配置)'}"
    )


def _enrich_output_schema() -> dict[str, Any]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "name": nullable_string,
            "email": nullable_string,
            "department": nullable_string,
            "homepage": nullable_string,
            "google_scholar": nullable_string,
            "research_summary": nullable_string,
            "recent_papers": nullable_string,
            "recommended_papers": {
                "type": "array",
                "items": _recommended_paper_schema(),
            },
            "region": nullable_string,
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "name",
            "email",
            "department",
            "homepage",
            "google_scholar",
            "research_summary",
            "recent_papers",
            "recommended_papers",
            "region",
            "tags",
        ],
        "additionalProperties": False,
    }


def _recommend_papers_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "recommended_papers": {
                "type": "array",
                "items": _recommended_paper_schema(),
            },
        },
        "required": ["recommended_papers"],
        "additionalProperties": False,
    }


async def _recommend_papers_for_professor(
    prof: dict,
    llm,
    emit: Callable[[str], Awaitable[None]],
) -> list[dict[str, Any]]:
    name = str(prof.get("name") or "").strip()
    university = str(prof.get("university") or "").strip()
    research = str(prof.get("research_summary") or "").strip()
    known_info = (
        f"导师: {name}\n学校: {university}\n"
        f"研究方向: {research or '(待核验)'}\n"
        f"主页: {prof.get('homepage') or '(未知)'}\n"
        f"Google Scholar: {prof.get('google_scholar') or '(未知)'}\n"
        f"已有论文线索: {prof.get('recent_papers') or '(未知)'}"
    )
    applicant_context = _applicant_recommendation_context()

    if not is_harness_llm(llm):
        return []
    evidence = (
        "请使用实时网页搜索核验论文标题、作者关系、来源链接和明确被引数。"
        "优先检查导师主页、Google Scholar 和正式论文页面。"
    )

    try:
        response = await llm.ainvoke([
            SystemMessage(content=load_prompt("recommend_papers")),
            HumanMessage(content=(
                f"导师信息:\n{known_info}\n\n"
                f"{applicant_context}\n\n"
                f"公开证据与检索要求:\n{evidence}"
            )),
        ], **agent_invoke_options(
            llm,
            "research",
            _recommend_papers_output_schema(),
        ))
        data = _parse_json_response(response.content)
        return _normalize_recommended_papers(
            data.get("recommended_papers") if isinstance(data, dict) else []
        )
    except Exception as exc:
        logger.warning("Dedicated paper recommendation failed for %s: %s", name, exc)
        await emit(f"推荐论文生成失败：{exc}")
        return []


# ── 单个导师信息补全 ──────────────────────────────────


async def enrich_professor(
    prof_id: int,
    progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> dict:
    """根据导师的已有信息（名字、学校等），搜索并补全详细信息"""
    from backend.core import database as db_mod

    async def emit(message: str) -> None:
        if progress:
            await progress(message)

    prof = await db_mod.get_professor(prof_id)
    if not prof:
        return {"success": False, "message": "导师不存在"}

    llm = get_llm()
    harness_mode = is_harness_llm(llm)
    if not harness_mode:
        return {"success": False, "message": "导师补全需要 Codex 或 Pi Harness"}

    name = prof["name"]
    university = prof["university"]
    department = prof.get("department") or ""
    region = prof.get("region") or ""
    await emit(f"准备补全：{name} @ {university}")

    known_info = f"姓名: {name}\n学校: {university}"
    if department:
        known_info += f"\n院系: {department}"
    if region:
        known_info += f"\n地区: {region}"
    if prof.get("homepage"):
        known_info += f"\n主页: {prof['homepage']}"
    if prof.get("google_scholar"):
        known_info += f"\nGoogle Scholar: {prof['google_scholar']}"
    applicant_context = _applicant_recommendation_context()

    try:
        await emit("Agent Harness 正在实时搜索并核验公开学术信息")
        user_content = (
            f"已知信息:\n{known_info}\n\n{applicant_context}\n\n"
            "请使用实时网页搜索补全这位导师的信息。优先核验学校官网、"
            "个人主页和 Google Scholar，并遵守中国大陆中文名规则。"
            "另外推荐 3-5 篇与申请者方向自然相关且较有代表性的真实论文；"
            "相关性相近时优先选择明确被引更高的工作。"
        )

        resp = await llm.ainvoke([
            SystemMessage(content=load_prompt("enrich_professor")),
            HumanMessage(content=user_content),
        ], **agent_invoke_options(
            llm,
            "enrich",
            _enrich_output_schema(),
        ))
        enriched = _parse_json_response(resp.content)
    except Exception as e:
        logger.error(f"Enrich LLM failed: {e}")
        await emit(f"LLM 分析失败：{e}")
        return {"success": False, "message": f"LLM 分析失败: {e}"}

    recommendations = _normalize_recommended_papers(
        enriched.get("recommended_papers")
    )
    existing_recommendations = _normalize_recommended_papers(
        prof.get("recommended_papers")
    )
    if not recommendations and not existing_recommendations:
        await emit("常规补全未返回推荐论文，启动专项论文推荐")
        recommendations = await _recommend_papers_for_professor(
            {**prof, **enriched},
            llm,
            emit,
        )
    if recommendations:
        enriched["recommended_papers"] = recommendations

    # 构建更新字段
    # email: 只在原值为空 / 占位邮箱时才覆盖（保护用户手动改过的真实邮箱）
    # 其他字段: 只要 LLM 给出新值就覆盖（enrich 是用户主动触发的"刷新"动作，
    #   应当采纳更准确的搜索结果，否则首次搜索时填的粗糙摘要永远不会被更新）
    update_data = {}
    new_email = _normalize_email(enriched.get("email"))
    old_email = prof.get("email") or ""
    if new_email and (not old_email or old_email.endswith("@tbd")):
        update_data["email"] = new_email

    new_name = (enriched.get("name") or "").strip()
    if new_name:
        mainland = _is_mainland_china(
            enriched.get("region") or region,
            university,
        )
        if mainland and _has_cjk(new_name):
            update_data["name"] = new_name
        elif not mainland and not _has_cjk(new_name):
            update_data["name"] = new_name

    for field in ("department", "homepage", "google_scholar",
                  "research_summary", "recent_papers", "region"):
        new_val = enriched.get(field)
        if new_val:
            update_data[field] = new_val

    recommended_papers = _normalize_recommended_papers(
        enriched.get("recommended_papers")
    )
    if recommended_papers:
        update_data["recommended_papers"] = json.dumps(
            recommended_papers,
            ensure_ascii=False,
        )

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
        await emit(f"已更新字段：{', '.join(update_data.keys())}")
    else:
        await emit("补全完成，但没有发现需要更新的字段")

    return {"success": True, "updated_fields": list(update_data.keys())}


# ── 主流程：Codex/Pi Harness 搜索 ──────────────────────

def _codex_search_output_schema() -> dict[str, Any]:
    candidate = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "university": {"type": "string"},
            "department": {"type": "string"},
            "email": {"type": "string"},
            "homepage": {"type": "string"},
            "google_scholar": {"type": "string"},
            "research_summary": {"type": "string"},
            "recent_papers": {"type": "string"},
            "recommended_papers": {
                "type": "array",
                "items": _recommended_paper_schema(),
            },
            "region": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "name",
            "university",
            "department",
            "email",
            "homepage",
            "google_scholar",
            "research_summary",
            "recent_papers",
            "recommended_papers",
            "region",
            "tags",
            "sources",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "candidates": {"type": "array", "items": candidate},
            "summary": {"type": "string"},
        },
        "required": ["candidates", "summary"],
        "additionalProperties": False,
    }


def _compact_professor_index(professors: list[dict], blacklist: list[dict]) -> str:
    lines = []
    for prof in professors[:200]:
        name = str(prof.get("name") or "").strip()
        university = str(prof.get("university") or "").strip()
        lines.append(" | ".join(value for value in (name, university) if value))
    if blacklist:
        lines.append("REMOVED BY USER:")
        lines.extend(
            f"{item.get('name', '')} | {item.get('university', '')}"
            for item in blacklist[:100]
        )
    return ("\n".join(lines)[:16000] or "(empty)").rstrip()


def _codex_search_batch_specs(
    keywords: list[str],
    regions: list[str],
    max_results: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    clean_keywords = [str(value).strip() for value in keywords if str(value).strip()]
    clean_regions = [str(value).strip() for value in regions if str(value).strip()]
    keyword_lanes = clean_keywords or ["applicant profile fit"]
    region_lanes = clean_regions or ["global"]
    discovery_paths = (
        "official university faculty directories and personal homepages",
        "CSRankings followed by official affiliation verification",
        "Google Scholar profiles followed by official faculty pages",
    )
    batch_count = (max_results + batch_size - 1) // batch_size
    specs = []
    for index in range(batch_count):
        target = min(batch_size, max_results - index * batch_size)
        region = region_lanes[index % len(region_lanes)]
        keyword = keyword_lanes[(index // len(region_lanes)) % len(keyword_lanes)]
        discovery_path = discovery_paths[index % len(discovery_paths)]
        specs.append({
            "index": index + 1,
            "target": target,
            "focus": (
                f"Region lane: {region}\n"
                f"Research lane: {keyword}\n"
                f"Primary discovery path: {discovery_path}"
            ),
        })
    return specs


async def _build_codex_search_prompt(
    keywords: list[str],
    regions: list[str],
    max_results: int,
    focus: str = "",
) -> str:
    cfg = load_yaml_config()
    preference = str(
        (cfg.get("prompts", {}) or {}).get("search_preference", "")
    ).strip()
    profile = load_profile().strip()
    professors = await db.get_professors()
    blacklist = await db.get_blacklist()
    existing_index = _compact_professor_index(professors, blacklist)

    return f"""
Find up to {max_results} NEW faculty members who are plausible PhD supervisors for
the applicant below.

Target research directions:
{", ".join(keywords) or "(infer from applicant profile)"}

Target regions:
{", ".join(regions) or "(no region restriction)"}

This batch has one narrow discovery focus:
{focus or "(use the general target above)"}

User search preference:
{preference or "(none)"}

Applicant profile:
{profile[:6000] or "(profile not configured)"}

Professors already covered by the local database or removed by the user:
{existing_index}

Requirements:
- Prioritize professors not present in the existing index. Do not return an
  existing or removed professor merely because the fit is strong.
- Use several discovery paths, especially official faculty pages, personal
  homepages, Google Scholar, and CSRankings. Prefer current, active faculty.
- This is a small batch. Use at most four focused web searches, verify at most
  {max_results} strong candidates, and return as soon as those candidates are
  verified. Do not broaden the search after reaching the batch target.
- For a professor based in mainland China, verify and return the exact Chinese
  name from an official Chinese source. For every other region, return the
  English or romanized name and do not use a Chinese name.
- Verify contact fields from public sources. Decode anti-crawler forms such as
  "name {{at}} school {{dot}} edu", but leave email empty if it cannot be verified.
- recent_papers should be a concise plain-text list of verified representative or
  recent works. Never invent titles or publication status.
- For each candidate, recommend up to three papers that are naturally relevant
  to the applicant profile and target direction. Among similarly relevant works,
  prefer explicitly more-cited papers. Every recommended_papers item needs a
  verified HTTP(S) URL and a brief Chinese why_recommended note. Use null for an
  unverified year or citation count; omit uncertain papers rather than guessing.
- sources must contain the public URLs used to verify identity and affiliation.
  Return no candidate without at least one credible source URL.
- Return only the requested JSON. Use empty strings or empty arrays for unknown
  fields.
""".strip()


async def _save_codex_candidate(candidate: dict[str, Any]) -> tuple[str, dict | None]:
    name = str(candidate.get("name") or "").strip()
    university = str(candidate.get("university") or "").strip()
    region = str(candidate.get("region") or "").strip()
    if not name or not university:
        return "跳过字段不完整的候选人", None

    mainland = _is_mainland_china(region, university)
    if mainland and not _has_cjk(name):
        return f"跳过 {name}：未核验到准确中文名", None
    if not mainland and _has_cjk(name):
        return f"跳过 {name}：非中国大陆导师应使用英文姓名", None
    if await db.is_blacklisted(name, university):
        return f"跳过黑名单导师：{name} @ {university}", None

    sources = [
        str(url).strip()
        for url in candidate.get("sources", [])
        if str(url).strip().startswith(("https://", "http://"))
    ]
    if not sources:
        return f"跳过 {name}：缺少可核验的公开来源", None

    email = _normalize_email(candidate.get("email"))
    homepage = str(candidate.get("homepage") or "").strip()
    google_scholar = str(candidate.get("google_scholar") or "").strip()
    prof_data = {
        "name": name,
        "email": email,
        "university": university,
        "department": str(candidate.get("department") or "").strip(),
        "homepage": homepage if homepage.startswith(("https://", "http://")) else "",
        "google_scholar": (
            google_scholar
            if google_scholar.startswith(("https://", "http://"))
            else ""
        ),
        "research_summary": str(candidate.get("research_summary") or "").strip(),
        "recent_papers": str(candidate.get("recent_papers") or "").strip(),
        "recommended_papers": _serialize_recommended_papers(
            candidate.get("recommended_papers")
        ),
        "region": region,
        "source": "auto",
        "tags": _new_professor_tags(candidate.get("tags", [])),
    }
    match = await db.find_existing_professor_match(prof_data)
    if match:
        existing = match["professor"]
        return (
            f"跳过已有导师：{existing.get('name')} @ {existing.get('university')}",
            None,
        )

    if not email:
        safe_name = re.sub(r"[^a-z0-9.]+", ".", name.lower()).strip(".")
        safe_name = (safe_name or "professor")[:40]
        identity_hash = hashlib.sha256(
            f"{name}|{university}".encode("utf-8")
        ).hexdigest()[:12]
        prof_data["email"] = f"unknown-{safe_name}-{identity_hash}@tbd"

    saved = await db.create_professor(prof_data)
    if saved.get("_deduped"):
        return f"跳过数据库已合并导师：{name} @ {university}", None
    return f"已保存：{name} @ {university}", saved


async def _search_professors_codex(
    keywords: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    max_results: int = 20,
    agent_backend: str = "codex",
) -> AsyncGenerator[dict, None]:
    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {}) or {}
    agent_cfg = (
        search_cfg.get(agent_backend, {})
        or search_cfg.get("agent", {})
        or search_cfg.get("codex", {})
        or {}
    )
    llm_codex_cfg = (cfg.get("llm", {}) or {}).get("codex", {}) or {}
    resolved_keywords = keywords or search_cfg.get("keywords", []) or []
    resolved_regions = regions or search_cfg.get("regions", []) or []
    max_results = max(1, min(int(max_results or 20), 40))
    batch_size = max(2, min(int(agent_cfg.get("batch_size", 3)), 5))
    parallel_batches = max(
        1,
        min(int(agent_cfg.get("parallel_batches", 2)), 3),
    )
    timeout_seconds = max(
        45,
        min(int(agent_cfg.get("timeout_seconds", 120)), 180),
    )
    batch_specs = _codex_search_batch_specs(
        resolved_keywords,
        resolved_regions,
        max_results,
        batch_size,
    )
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    semaphore = asyncio.Semaphore(parallel_batches)
    model_config = (
        get_model_api_config(cfg)
        if agent_backend == "pi"
        else None
    )
    model = (
        str(model_config.get("model") or "").strip()
        if model_config
        else str(llm_codex_cfg.get("model") or "").strip()
    ) or None
    agent_label = "Pi" if agent_backend == "pi" else "Codex"

    yield {
        "type": "progress",
        "message": (
            f"{agent_label} Search Agent 已启动：{len(batch_specs)} 个小批次，"
            f"最多 {parallel_batches} 批并行"
        ),
    }

    async def run_batch(spec: dict[str, Any]) -> None:
        index = int(spec["index"])
        try:
            async with semaphore:
                prompt = await _build_codex_search_prompt(
                    resolved_keywords,
                    resolved_regions,
                    int(spec["target"]),
                    str(spec["focus"]),
                )
                await queue.put({
                    "kind": "progress",
                    "index": index,
                    "message": f"第 {index}/{len(batch_specs)} 批开始检索",
                })
                result_data: dict[str, Any] | None = None
                async for worker_message in stream_agent_task(
                    prompt=prompt,
                    backend=agent_backend,
                    output_schema=_codex_search_output_schema(),
                    timeout_seconds=timeout_seconds,
                    harness="search",
                    model=model,
                    model_config=model_config,
                ):
                    if worker_message.get("type") == "progress":
                        await queue.put({
                            "kind": "progress",
                            "index": index,
                            "message": str(worker_message.get("message") or ""),
                        })
                    elif worker_message.get("type") == "result":
                        data = worker_message.get("data")
                        if isinstance(data, dict):
                            result_data = data
                if result_data is None:
                    raise RuntimeError("Agent Worker 未返回结构化结果")
                await queue.put({
                    "kind": "result",
                    "index": index,
                    "target": int(spec["target"]),
                    "data": result_data,
                })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put({
                "kind": "error",
                "index": index,
                "message": str(exc),
            })

    tasks = [
        asyncio.create_task(run_batch(spec), name=f"codex-search-batch-{spec['index']}")
        for spec in batch_specs
    ]
    saved_count = 0
    completed_batches = 0
    successful_batches = 0
    failures: list[str] = []
    try:
        while completed_batches < len(batch_specs) and saved_count < max_results:
            event = await queue.get()
            index = int(event["index"])
            kind = event["kind"]
            if kind == "progress":
                message = str(event.get("message") or "").strip()
                if message:
                    yield {
                        "type": "progress",
                        "message": f"[批次 {index}] {message}",
                    }
                continue

            completed_batches += 1
            if kind == "error":
                error = str(event.get("message") or "未知错误")
                failures.append(error)
                yield {
                    "type": "progress",
                    "message": f"[批次 {index}] 未完成：{error}，继续其他批次",
                }
                continue

            successful_batches += 1
            result_data = event.get("data") or {}
            candidates = result_data.get("candidates")
            if not isinstance(candidates, list):
                failures.append("candidates 格式无效")
                yield {
                    "type": "progress",
                    "message": f"[批次 {index}] 返回格式无效，继续其他批次",
                }
                continue
            yield {
                "type": "progress",
                "message": (
                    f"[批次 {index}] 找到 {len(candidates)} 位候选，"
                    "正在本地校验和去重"
                ),
            }
            for raw_candidate in candidates[: int(event["target"])]:
                if saved_count >= max_results:
                    break
                if not isinstance(raw_candidate, dict):
                    continue
                message, saved = await _save_codex_candidate(raw_candidate)
                yield {"type": "progress", "message": message}
                if saved:
                    saved_count += 1
                    yield {"type": "professor", "data": saved}

            summary = str(result_data.get("summary") or "").strip()
            if summary:
                yield {
                    "type": "progress",
                    "message": f"[批次 {index}] {summary}",
                }
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if successful_batches == 0 and failures:
        raise RuntimeError(f"{agent_label} 分批搜索均未完成：{failures[0]}")

    all_professors = await db.get_professors()
    yield {
        "type": "done",
        "total": len(all_professors),
        "message": f"搜索完成，本次新增 {saved_count} 位导师",
    }


async def search_professors(
    keywords: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    max_results: int = 20,
) -> AsyncGenerator[dict, None]:
    """Discover professors through the selected Codex or Pi Harness."""
    agent_backend = resolve_agent_backend(load_yaml_config().get("llm", {}) or {})
    if agent_backend not in {"codex", "pi"}:
        yield {
            "type": "error",
            "message": "导师搜索需要 Codex 或 Pi Harness，请在设置中选择对应执行引擎",
        }
        return
    try:
        async for message in _search_professors_codex(
            keywords=keywords,
            regions=regions,
            max_results=max_results,
            agent_backend=agent_backend,
        ):
            yield message
    except (CodexWorkerError, PiWorkerError, RuntimeError, ValueError) as exc:
        yield {"type": "error", "message": str(exc)}
