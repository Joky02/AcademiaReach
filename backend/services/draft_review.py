"""Deterministic, explainable scoring for the outreach review queue."""

from __future__ import annotations

import json
import math
import re
from typing import Any


HIGH_IMPACT_VENUES = (
    "nature",
    "science",
    "cell",
    "neurips",
    "icml",
    "iclr",
    "acl",
    "kdd",
    "aaai",
    "ijcai",
    "pnas",
)
PROFILE_STOPWORDS = {
    "about", "also", "application", "background", "current", "degree",
    "education", "experience", "from", "have", "interested", "master",
    "paper", "project", "research", "student", "study", "using", "with",
}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _paper_impact(paper: dict[str, Any]) -> int:
    citations = paper.get("citation_count")
    citation_score = 0
    if isinstance(citations, int) and citations > 0:
        citation_score = min(20, round(5 * math.log10(citations + 1)))

    venue = str(paper.get("venue") or "").lower()
    venue_score = 0
    if "nature" in venue or venue == "science":
        venue_score = 18
    elif "science robotics" in venue or "cell" in venue or "pnas" in venue:
        venue_score = 16
    elif any(name in venue for name in HIGH_IMPACT_VENUES):
        venue_score = 13
    elif venue and "arxiv" not in venue and "biorxiv" not in venue:
        venue_score = 8
    elif venue:
        venue_score = 3

    year = paper.get("year")
    recency_score = 0
    if isinstance(year, int):
        recency_score = 5 if year >= 2024 else 3 if year >= 2020 else 1
    return min(35, citation_score + venue_score + recency_score)


def _find_discussed_paper(body: str, papers: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_body = re.sub(r"\s+", " ", body).casefold()
    matches = [
        paper
        for paper in papers
        if str(paper.get("title") or "").strip()
        and str(paper["title"]).strip().casefold() in normalized_body
    ]
    if matches:
        return max(matches, key=_paper_impact)
    return None


def _profile_terms(profile: str) -> set[str]:
    """Extract research terms without encoding a particular applicant profile."""
    lowered = profile.casefold()
    english_terms = {
        word
        for word in re.findall(r"[a-z][a-z0-9+.-]{2,}", lowered)
        if word not in PROFILE_STOPWORDS
    }
    phrase_terms = {
        phrase.strip(" #*_-.")
        for phrase in re.split(r"[,，、;/|：:()（）\n]", lowered)
        if 2 <= len(phrase.strip(" #*_-.")) <= 40
    }
    return english_terms | phrase_terms


def _tailored_subject(subject: str, is_chinese: bool) -> bool:
    text = subject.strip()
    if not text:
        return False
    if is_chinese:
        return len(text) >= 8
    lowered = text.lower()
    match = re.match(r"^(?:20\d{2}\s+)?phd application\s*:\s*(.+)$", lowered)
    return bool(match and len(match.group(1).strip()) >= 8)


def _message_length(body: str) -> tuple[int, str, bool]:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", body))
    word_count = len(re.findall(r"\b[\w'-]+\b", body))
    is_chinese = chinese_chars >= max(20, word_count)
    return (chinese_chars, "字", True) if is_chinese else (word_count, "words", False)


def _length_score(length: int, is_chinese: bool) -> int:
    if is_chinese:
        return 6 if 280 <= length <= 750 else 3 if 180 <= length <= 900 else 0
    return 6 if 190 <= length <= 360 else 3 if 160 <= length <= 430 else 0


def _rank_label(score: int) -> str:
    if score >= 82:
        return "优先审核"
    if score >= 70:
        return "值得审核"
    if score >= 58:
        return "补充审核"
    return "建议重写"


def score_draft(row: dict[str, Any], applicant_profile: str = "") -> dict[str, Any]:
    """Return transparent ranking scores without pretending to be calibrated odds."""
    body = str(row.get("body") or "")
    subject = str(row.get("subject") or "")
    tags = [str(tag) for tag in _json_list(row.get("professor_tags"))]
    papers = [
        item
        for item in _json_list(row.get("recommended_papers"))
        if isinstance(item, dict)
    ]
    discussed_paper = _find_discussed_paper(body, papers)
    paper_score = _paper_impact(discussed_paper) if discussed_paper else 0
    max_paper_score = max((_paper_impact(paper) for paper in papers), default=0)
    content_length, length_unit, is_chinese = _message_length(body)
    tailored_subject = _tailored_subject(subject, is_chinese)

    searchable = " ".join(
        tags
        + [
            str(row.get("research_summary") or ""),
            str(row.get("recent_papers") or ""),
        ]
    ).lower()
    direction_hits = sum(1 for keyword in _profile_terms(applicant_profile) if keyword in searchable)

    relevance = 22 if discussed_paper else 5 if papers else 0
    relevance += paper_score
    relevance += min(20, direction_hits * 3)
    relevance += 10 if tailored_subject else 2
    relevance += _length_score(content_length, is_chinese)
    if is_chinese:
        relevance += 4 if any(token in body for token in ("最近读了", "近期读了", "拜读了")) else 0
        relevance += 3 if any(token in body for token in ("希望", "探讨", "交流", "可能")) else 0
    else:
        relevance += 4 if "i recently read" in body.lower() else 0
        relevance += 3 if any(token in body.lower() for token in ("question", "whether", "could", "may")) else 0
    relevance = min(100, relevance)

    tag_set = {tag.casefold() for tag in tags}
    direct_recruiting = "recruiting-explicit" in tag_set
    program_recruiting = "recruiting-program-current" in tag_set
    institutional_email = bool(
        re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(row.get("professor_email") or ""))
        and not str(row.get("professor_email") or "").endswith("@tbd")
    )
    seniority_text = " ".join(tags).lower()
    if "assistant" in seniority_text or " ap" in f" {seniority_text}":
        seniority_points = 10
        seniority_reason = "早期职业阶段导师"
    elif "associate" in seniority_text:
        seniority_points = 7
        seniority_reason = "副教授阶段"
    elif "full prof" in seniority_text or "fellow" in seniority_text:
        seniority_points = 2
        seniority_reason = "资深导师通常来信量更高"
    else:
        seniority_points = 5
        seniority_reason = "导师资历信息有限"

    reply = 16
    reply += 25 if direct_recruiting else 12 if program_recruiting else 2
    reply += 8 if institutional_email else 0
    reply += seniority_points
    reply += 7 if _length_score(content_length, is_chinese) == 6 else 3 if _length_score(content_length, is_chinese) == 3 else 0
    reply += 6 if tailored_subject else 0
    reply += round(relevance * 0.15)
    reply += 3 if row.get("is_starred") else 0
    reply = max(8, min(85, reply))

    priority = round(relevance * 0.65 + reply * 0.35)
    strengths: list[str] = []
    cautions: list[str] = []
    if discussed_paper:
        citation_count = discussed_paper.get("citation_count")
        if isinstance(citation_count, int):
            strengths.append(f"正文展开被引 {citation_count} 次的代表作")
        else:
            strengths.append("正文展开已核验的推荐作品")
        if paper_score >= max_paper_score:
            strengths.append("所选作品处于推荐列表最高影响力档")
        elif max_paper_score - paper_score >= 8:
            cautions.append("存在影响力更强且可能相关的推荐作品")
    else:
        cautions.append("正文未匹配到推荐论文标题")
    if direct_recruiting:
        strengths.append("有导师或实验室直接招生证据")
    elif program_recruiting:
        cautions.append("仅有项目层面的当前招生证据")
    else:
        cautions.append("招生状态仍需确认")
    if tailored_subject:
        strengths.append("标题包含导师专属研究问题")
    else:
        cautions.append("标题仍偏通用")
    if institutional_email:
        strengths.append("使用已核验的机构邮箱")
    cautions.append(seniority_reason)

    return {
        "relevance_score": relevance,
        "reply_likelihood_score": reply,
        "priority_score": priority,
        "priority_label": _rank_label(priority),
        "content_length": content_length,
        "length_unit": length_unit,
        "selected_paper": discussed_paper,
        "selected_paper_impact": paper_score,
        "max_recommended_impact": max_paper_score,
        "strengths": strengths[:4],
        "cautions": cautions[:3],
        "score_version": "heuristic-v2",
    }


def rank_drafts(rows: list[dict[str, Any]], applicant_profile: str = "") -> list[dict[str, Any]]:
    scored = [
        {**row, **score_draft(row, applicant_profile=applicant_profile)}
        for row in rows
    ]
    return sorted(
        scored,
        key=lambda item: (
            int(item["priority_score"]),
            int(item["relevance_score"]),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
