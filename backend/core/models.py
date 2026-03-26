"""Pydantic 数据模型 — 导师、邮件、回复等核心实体"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 枚举 ──────────────────────────────────────────────

class ProfessorSource(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class DraftStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SKIPPED = "skipped"
    SENT = "sent"


class ReplyStatus(str, enum.Enum):
    NO_REPLY = "no_reply"
    REPLIED = "replied"
    POSITIVE = "positive"
    NEGATIVE = "negative"


# ── 导师 ──────────────────────────────────────────────

class ProfessorBase(BaseModel):
    name: str
    email: str
    university: str
    department: Optional[str] = None
    homepage: Optional[str] = None
    research_summary: Optional[str] = None
    recent_papers: Optional[str] = None
    region: Optional[str] = None
    source: ProfessorSource = ProfessorSource.MANUAL


class ProfessorCreate(ProfessorBase):
    pass


class Professor(ProfessorBase):
    id: int
    reply_status: ReplyStatus = ReplyStatus.NO_REPLY
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


# ── 邮件草稿 ─────────────────────────────────────────

class DraftBase(BaseModel):
    professor_id: int
    subject: str
    body: str
    language: str = "en"


class DraftCreate(DraftBase):
    pass


class DraftUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    status: Optional[DraftStatus] = None


class Draft(DraftBase):
    id: int
    status: DraftStatus = DraftStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── 回复 ─────────────────────────────────────────────

class Reply(BaseModel):
    id: int
    professor_id: int
    subject: str
    body: str
    received_at: datetime
    is_read: bool = False

    class Config:
        from_attributes = True


# ── 统计 ─────────────────────────────────────────────

class Stats(BaseModel):
    total_professors: int = 0
    drafts_pending: int = 0
    emails_sent: int = 0
    replies_received: int = 0


# ── 搜索请求 ─────────────────────────────────────────

class SearchRequest(BaseModel):
    keywords: Optional[list[str]] = None
    regions: Optional[list[str]] = None
    max_results: int = 20


# ── 配置模型 ─────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "openai"
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class SMTPConfig(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True


class IMAPConfig(BaseModel):
    host: str = ""
    port: int = 993
    username: str = ""
    password: str = ""
    use_ssl: bool = True
    poll_interval: int = 300


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    smtp: SMTPConfig = Field(default_factory=SMTPConfig)
    imap: IMAPConfig = Field(default_factory=IMAPConfig)
    search_keywords: list[str] = Field(default_factory=list)
    search_regions: list[str] = Field(default_factory=list)
    max_professors: int = 20
    profile_content: str = ""
