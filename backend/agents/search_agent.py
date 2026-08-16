"""导师搜索 Agent — LLM 自主 Tool Calling 驱动搜索"""

from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from backend.core.llm import get_llm, load_yaml_config, load_profile
from backend.core.prompts import load_prompt
from backend.core import database as db

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25
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

_serper_key: str = ""
_progress_queue: Optional[asyncio.Queue] = None
_csrankings_cache: dict[str, Any] = {"loaded_at": 0.0, "faculty": None, "institutions": None}


# ── Tool 定义 ──────────────────────────────────────────

@tool
async def search_google(query: str) -> str:
    """Search Google for academic information. Use English queries by default; use Chinese terms only to verify accurate Chinese names for mainland China professors. Returns titles, snippets, and links for professor homepages, publications, and contact info."""
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
        return f"CSRankings fetch failed: {e}. Fall back to search_google."

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


async def _candidate_enrichment_search(
    name: str,
    university: str,
    department: str = "",
    research_hint: str = "",
    region: str = "",
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
    if _is_mainland_china(region, university):
        queries = [
            f"{base} 中文名 教授",
            f"{base} 个人主页 教授",
            f"{base} 简历 学者",
            f"{base} site:edu.cn 教授",
            *queries,
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
    if region:
        known_info += f"\n地区: {region}"
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
    email = _normalize_email(enriched.get("email"))
    enriched["email"] = email or None
    return enriched


@tool
async def enrich_candidate_info(
    name: str,
    university: str,
    department: str = "",
    research_hint: str = "",
    region: str = "",
) -> str:
    """Before saving a professor, search for verified name, email, homepage, Google Scholar, department, recent papers, region, and tags. Convert anti-crawler email forms like name {at} uni {dot} edu to standard email addresses. Also marks candidates that are already in the local database so you can skip them and search for new professors. Mainland China professors need accurate Chinese names; all other regions should use English/romanized names. Returns JSON. Do not fabricate missing fields."""
    if not name or not university:
        return "Error: name and university are required."
    enriched = await _candidate_enrichment_search(name, university, department, research_hint, region)
    candidate = {
        "name": enriched.get("name") or name,
        "university": university,
        "email": enriched.get("email") or "",
        "homepage": enriched.get("homepage") or "",
        "google_scholar": enriched.get("google_scholar") or "",
    }
    match = await db.find_existing_professor_match(candidate)
    if match:
        existing = match["professor"]
        enriched["_already_in_database"] = True
        enriched["_existing_id"] = existing.get("id")
        enriched["_existing_name"] = existing.get("name")
        enriched["_existing_university"] = existing.get("university")
        enriched["_match_reason"] = match.get("reason")
    return json.dumps(enriched, ensure_ascii=False)


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
    region: str = "",
    tags: str = "[]",
) -> str:
    """Save a professor to the database. Required: name, university. Email may be a standard address or an anti-crawler form like name {at} uni {dot} edu, which will be normalized. For mainland China professors, name must be the accurate Chinese name; for other regions, use English/romanized name. Optional: email, department, homepage, google_scholar, research_summary, recent_papers, region, tags. Do NOT fabricate info."""
    global _progress_queue
    if not name or not university:
        return "Error: name and university are required."
    email = _normalize_email(email)
    # 黑名单：用户之前主动叉掉过的导师，不再保存
    if await db.is_blacklisted(name, university):
        if _progress_queue:
            await _progress_queue.put({"type": "progress", "message": f"⛔ 跳过（黑名单）: {name} @ {university}"})
        return f"Skipped: {name} @ {university} is on the user's blacklist. Do NOT try to save this professor again — pick a different one."

    mainland_candidate = _is_mainland_china(region, university)
    needs_enrichment = (
        not _valid_email(email)
        or not homepage
        or not google_scholar
        or not recent_papers
        or not research_summary
        or (mainland_candidate and not _has_cjk(name))
        or (not mainland_candidate and _has_cjk(name))
    )
    if needs_enrichment and _serper_key:
        enriched = await _candidate_enrichment_search(
            name=name,
            university=university,
            department=department,
            research_hint=research_summary,
            region=region,
        )
        enriched_name = (enriched.get("name") or "").strip()
        mainland_enriched = _is_mainland_china(region or enriched.get("region") or "", university)
        if enriched_name:
            if mainland_enriched and _has_cjk(enriched_name):
                name = enriched_name
            elif not mainland_enriched and not _has_cjk(enriched_name):
                name = enriched_name
        email = email or _normalize_email(enriched.get("email"))
        department = department or enriched.get("department") or ""
        homepage = homepage or enriched.get("homepage") or ""
        google_scholar = google_scholar or enriched.get("google_scholar") or ""
        research_summary = research_summary or enriched.get("research_summary") or ""
        recent_papers = recent_papers or enriched.get("recent_papers") or ""
        region = region or enriched.get("region") or ""
        if (not tags or tags == "[]") and enriched.get("tags"):
            tags = json.dumps(enriched["tags"], ensure_ascii=False)

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
        "region": region, "source": "auto",
    }
    if tags and tags != "[]":
        prof_data["tags"] = tags

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

    cfg = load_yaml_config()
    search_cfg = cfg.get("search", {})
    serper_key = search_cfg.get("serper_api_key", "")
    if not serper_key or serper_key == "your-serper-api-key":
        return {"success": False, "message": "请先配置 Serper API Key"}

    llm = get_llm()
    name = prof["name"]
    university = prof["university"]
    department = prof.get("department") or ""
    region = prof.get("region") or ""
    await emit(f"准备补全：{name} @ {university}")

    # 构造搜索查询
    queries = [
        f"{name} {university} professor homepage",
        f"{name} {university} {department} research email",
        f'"{name}" "{university}" google scholar',
    ]
    if _is_mainland_china(region, university):
        queries = [
            f'"{name}" "{university}" 中文名 教授',
            f'"{name}" "{university}" 个人主页 教授',
            f'"{name}" "{university}" 简历 学者',
            *queries,
        ]

    all_results = []
    for q in queries:
        await emit(f"搜索：{q}")
        try:
            results = await search_serper(q, serper_key, num=8)
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Enrich search failed for '{q}': {e}")
            await emit(f"搜索失败：{q} ({e})")
        await asyncio.sleep(0.3)

    if not all_results:
        await emit("未搜索到任何结果")
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
    await emit(f"搜索完成：去重后 {len(unique)} 条结果，开始提取字段")

    known_info = f"姓名: {name}\n学校: {university}"
    if department:
        known_info += f"\n院系: {department}"
    if region:
        known_info += f"\n地区: {region}"
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
        await emit(f"LLM 分析失败：{e}")
        return {"success": False, "message": f"LLM 分析失败: {e}"}

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
    tools = [
        search_csrankings,
        search_google,
        enrich_candidate_info,
        check_professor_exists,
        save_professor,
        get_existing_professors,
        get_user_profile,
    ]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    runtime_requirements = []
    if keywords:
        runtime_requirements.append(f"本次搜索关键词: {', '.join(keywords)}")
    if regions:
        runtime_requirements.append(f"本次目标地区: {', '.join(regions)}")
    runtime_extra = ("\n" + "\n".join(runtime_requirements)) if runtime_requirements else ""

    messages = [
        SystemMessage(content=_build_search_system_prompt()),
        HumanMessage(content=f"请开始搜索导师，目标找到约 {max_results} 位匹配的新导师。{runtime_extra}"),
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
