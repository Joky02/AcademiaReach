"""SQLite 数据库操作 — 异步，基于 aiosqlite"""

from __future__ import annotations

import aiosqlite
import json
import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "taoci.db")

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
    "icloud.com", "qq.com", "163.com", "126.com",
}

PROFESSOR_MERGE_FIELDS = {
    "name", "email", "university", "department", "homepage", "google_scholar",
    "research_summary", "recent_papers", "recommended_papers", "region", "source",
    "reply_status", "is_starred", "tags",
}


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """创建数据库表"""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS professors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                university TEXT NOT NULL,
                department TEXT,
                homepage TEXT,
                google_scholar TEXT,
                research_summary TEXT,
                recent_papers TEXT,
                recommended_papers TEXT DEFAULT '[]',
                region TEXT,
                source TEXT DEFAULT 'manual',
                reply_status TEXT DEFAULT 'no_reply',
                is_starred INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professor_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                language TEXT DEFAULT 'en',
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                sent_at TEXT,
                FOREIGN KEY (professor_id) REFERENCES professors(id)
            );

            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professor_id INTEGER NOT NULL,
                subject TEXT,
                body TEXT,
                received_at TEXT DEFAULT (datetime('now')),
                is_read INTEGER DEFAULT 0,
                FOREIGN KEY (professor_id) REFERENCES professors(id)
            );

            -- 黑名单：用户叉掉的导师，搜索时跳过避免重复推荐
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_norm TEXT NOT NULL,         -- 规范化的姓名（小写+去空格）
                university_norm TEXT NOT NULL,   -- 规范化的学校
                name TEXT NOT NULL,              -- 原始姓名（用于展示）
                university TEXT NOT NULL,        -- 原始学校
                reason TEXT,                     -- 可选：删除原因
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(name_norm, university_norm)
            );
        """)
        await db.commit()

        # ── 迁移：为已有表添加新列 ──
        cursor = await db.execute("PRAGMA table_info(professors)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "is_starred" not in cols:
            await db.execute("ALTER TABLE professors ADD COLUMN is_starred INTEGER DEFAULT 0")
        if "tags" not in cols:
            await db.execute("ALTER TABLE professors ADD COLUMN tags TEXT DEFAULT '[]'")
        if "google_scholar" not in cols:
            await db.execute("ALTER TABLE professors ADD COLUMN google_scholar TEXT")
        if "recommended_papers" not in cols:
            await db.execute("ALTER TABLE professors ADD COLUMN recommended_papers TEXT DEFAULT '[]'")
        await db.execute("DELETE FROM drafts WHERE professor_id NOT IN (SELECT id FROM professors)")
        await db.execute("DELETE FROM replies WHERE professor_id NOT IN (SELECT id FROM professors)")
        await db.commit()
    finally:
        await db.close()


# ── Professor CRUD ────────────────────────────────────

def _clean_str(value: object) -> str:
    return str(value or "").strip()


def _has_value(value: object) -> bool:
    text = _clean_str(value)
    return bool(text) and text.lower() not in {"none", "null", "n/a", "na", "unknown"}


def _has_cjk(value: object) -> bool:
    return bool(CJK_RE.search(_clean_str(value)))


def _valid_identity_email(value: object) -> Optional[str]:
    email = _clean_str(value).lower()
    if not email or email.endswith("@tbd") or email.startswith("unknown-") or email.startswith("http"):
        return None
    if not EMAIL_RE.match(email):
        return None
    return email


def _normalize_url(value: object) -> Optional[str]:
    raw = _clean_str(value)
    if not raw or raw.lower() in {"none", "null", "n/a"}:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.netloc:
        return None
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    return f"{netloc}{path}".lower()


def _normalize_scholar(value: object) -> Optional[str]:
    raw = _clean_str(value)
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    if "scholar.google." not in netloc:
        return None
    user = parse_qs(parsed.query).get("user", [""])[0].strip()
    if user:
        return user.lower()
    normalized = _normalize_url(raw)
    return normalized


def _generic_homepage(value: object) -> bool:
    normalized = _normalize_url(value)
    if not normalized:
        return True
    path = "/" + normalized.split("/", 1)[1] if "/" in normalized else "/"
    generic_paths = {
        "/", "/people", "/people.htm", "/en/people.htm", "/faculty",
        "/faculty.htm", "/people/faculty", "/people/faculty.htm",
        "/staff", "/staff.htm", "/members", "/members.htm",
    }
    if path in generic_paths:
        return True
    if re.search(r"/(people|faculty|staff|members)/?$", path):
        return True
    return False


def _professor_identity_values(data: dict) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    email = _valid_identity_email(data.get("email"))
    if email:
        identities.add(("email", email))

    for field in ("google_scholar", "homepage"):
        scholar = _normalize_scholar(data.get(field))
        if scholar:
            identities.add(("google_scholar", scholar))

    homepage = _normalize_url(data.get("homepage"))
    if homepage and not _normalize_scholar(data.get("homepage")) and not _generic_homepage(data.get("homepage")):
        identities.add(("homepage", homepage))
    return identities


def _norm_name_university(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _clean_str(value).lower())


def _same_named_institution(data: dict, existing: dict) -> bool:
    name = _clean_str(data.get("name"))
    existing_name = _clean_str(existing.get("name"))
    if (
        not name
        or not existing_name
        or not _has_cjk(name)
        or not _has_cjk(existing_name)
        or _norm_name_university(name) != _norm_name_university(existing_name)
    ):
        return False
    email = _valid_identity_email(data.get("email"))
    existing_email = _valid_identity_email(existing.get("email"))
    if not email or not existing_email:
        return False
    domain = email.rsplit("@", 1)[-1]
    existing_domain = existing_email.rsplit("@", 1)[-1]
    return (
        domain == existing_domain
        and domain not in PUBLIC_EMAIL_DOMAINS
    )


async def _fetch_professor(db: aiosqlite.Connection, prof_id: int) -> Optional[dict]:
    cursor = await db.execute("SELECT * FROM professors WHERE id = ?", (prof_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def _find_duplicate_professor(
    db: aiosqlite.Connection,
    data: dict,
    exclude_id: Optional[int] = None,
) -> Optional[dict]:
    identities = _professor_identity_values(data)
    if not identities:
        return None
    cursor = await db.execute("SELECT * FROM professors ORDER BY id ASC")
    rows = [dict(r) for r in await cursor.fetchall()]
    for row in rows:
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if identities & _professor_identity_values(row):
            return row
    return None


async def find_existing_professor_match(
    data: dict,
    exclude_id: Optional[int] = None,
) -> Optional[dict]:
    """Find an existing professor by strong identity or exact normalized name+university."""
    db = await get_db()
    try:
        duplicate = await _find_duplicate_professor(db, data, exclude_id=exclude_id)
        if duplicate:
            return {"professor": duplicate, "reason": "email/google_scholar/homepage"}

        name_key = _norm_name_university(data.get("name"))
        university_key = _norm_name_university(data.get("university"))
        if not name_key or not university_key:
            return None

        cursor = await db.execute("SELECT * FROM professors ORDER BY id ASC")
        rows = [dict(r) for r in await cursor.fetchall()]
        for row in rows:
            if exclude_id is not None and row["id"] == exclude_id:
                continue
            if (
                _norm_name_university(row.get("name")) == name_key
                and _norm_name_university(row.get("university")) == university_key
            ):
                return {"professor": row, "reason": "name/university"}
            if _same_named_institution(data, row):
                return {"professor": row, "reason": "name/institution-email-domain"}
        return None
    finally:
        await db.close()


def _parse_tags(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            return []
    return []


def _parse_object_list(raw: object) -> list[dict]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _merged_professor_update(keep: dict, incoming: dict) -> dict:
    update: dict = {}

    if _has_value(incoming.get("name")):
        if not _has_value(keep.get("name")) or (_has_cjk(incoming.get("name")) and not _has_cjk(keep.get("name"))):
            update["name"] = incoming["name"]

    incoming_email = _valid_identity_email(incoming.get("email"))
    keep_email = _valid_identity_email(keep.get("email"))
    if incoming_email and not keep_email:
        update["email"] = incoming["email"]

    for field in (
        "university", "department", "google_scholar", "research_summary",
        "recent_papers", "region",
    ):
        if _has_value(incoming.get(field)) and not _has_value(keep.get(field)):
            update[field] = incoming[field]

    if _has_value(incoming.get("homepage")):
        if not _has_value(keep.get("homepage")) or (_generic_homepage(keep.get("homepage")) and not _generic_homepage(incoming.get("homepage"))):
            update["homepage"] = incoming["homepage"]

    keep_recommendations = _parse_object_list(keep.get("recommended_papers"))
    incoming_recommendations = _parse_object_list(incoming.get("recommended_papers"))
    if incoming_recommendations and not keep_recommendations:
        update["recommended_papers"] = json.dumps(
            incoming_recommendations,
            ensure_ascii=False,
        )

    keep_tags = _parse_tags(keep.get("tags"))
    incoming_tags = _parse_tags(incoming.get("tags"))
    merged_tags = list(dict.fromkeys(keep_tags + incoming_tags))
    if merged_tags != keep_tags:
        update["tags"] = json.dumps(merged_tags, ensure_ascii=False)

    if incoming.get("reply_status") and keep.get("reply_status", "no_reply") == "no_reply":
        update["reply_status"] = incoming["reply_status"]

    if incoming.get("is_starred") and not keep.get("is_starred"):
        update["is_starred"] = 1

    if incoming.get("source") == "manual" and keep.get("source") != "manual":
        update["source"] = "manual"

    return {k: v for k, v in update.items() if k in PROFESSOR_MERGE_FIELDS}


async def _apply_professor_update(db: aiosqlite.Connection, prof_id: int, data: dict) -> None:
    update = {k: v for k, v in data.items() if k in PROFESSOR_MERGE_FIELDS and v is not None}
    if not update:
        return
    sets = [f"{k} = ?" for k in update]
    vals = list(update.values()) + [prof_id]
    await db.execute(f"UPDATE professors SET {', '.join(sets)} WHERE id = ?", vals)


async def merge_professors(keep_id: int, drop_id: int) -> dict:
    """Merge two duplicate professor rows, preserving drafts/replies on the kept row."""
    if keep_id == drop_id:
        return {"kept_id": keep_id, "dropped_id": drop_id, "merged": False}
    db = await get_db()
    try:
        await db.execute("BEGIN")
        keep = await _fetch_professor(db, keep_id)
        drop = await _fetch_professor(db, drop_id)
        if not keep or not drop:
            await db.rollback()
            return {"kept_id": keep_id, "dropped_id": drop_id, "merged": False, "reason": "missing row"}
        update = _merged_professor_update(keep, drop)
        await db.execute("UPDATE drafts SET professor_id = ? WHERE professor_id = ?", (keep_id, drop_id))
        await db.execute("UPDATE replies SET professor_id = ? WHERE professor_id = ?", (keep_id, drop_id))
        await db.execute("DELETE FROM professors WHERE id = ?", (drop_id,))
        await _apply_professor_update(db, keep_id, update)
        await db.commit()
        return {
            "kept_id": keep_id,
            "dropped_id": drop_id,
            "kept_name": update.get("name", keep.get("name")),
            "dropped_name": drop.get("name"),
            "merged": True,
        }
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def dedupe_professors() -> list[dict]:
    """Merge existing professors that share email, Google Scholar, or a non-generic homepage."""
    merges: list[dict] = []
    while True:
        professors = await get_professors()
        seen: dict[tuple[str, str], int] = {}
        pending: Optional[tuple[int, int]] = None
        for prof in sorted(professors, key=lambda p: p["id"]):
            identities = _professor_identity_values(prof)
            match_id = next((seen[i] for i in identities if i in seen and seen[i] != prof["id"]), None)
            if match_id is not None:
                pending = (match_id, prof["id"])
                break
            for identity in identities:
                seen[identity] = prof["id"]
        if not pending:
            break
        merges.append(await merge_professors(pending[0], pending[1]))
    return merges


async def create_professor(data: dict) -> dict:
    db = await get_db()
    try:
        duplicate = await _find_duplicate_professor(db, data)
        if duplicate:
            update = _merged_professor_update(duplicate, data)
            await _apply_professor_update(db, duplicate["id"], update)
            await db.commit()
            merged = await _fetch_professor(db, duplicate["id"])
            return {**(merged or duplicate), "_deduped": True}

        cursor = await db.execute(
            """INSERT INTO professors
               (name, email, university, department, homepage, google_scholar,
                research_summary, recent_papers, recommended_papers, region, source, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"], data["email"], data["university"],
                data.get("department"), data.get("homepage"),
                data.get("google_scholar"),
                data.get("research_summary"), data.get("recent_papers"),
                data.get("recommended_papers") or "[]",
                data.get("region"), data.get("source", "manual"),
                data.get("tags", "[]"),
            ),
        )
        await db.commit()
        prof_id = cursor.lastrowid
        return {**data, "id": prof_id}
    except aiosqlite.IntegrityError:
        email = data.get("email")
        if email:
            cursor = await db.execute("SELECT * FROM professors WHERE email = ?", (email,))
            row = await cursor.fetchone()
            if row:
                existing = dict(row)
                update = _merged_professor_update(existing, data)
                await _apply_professor_update(db, existing["id"], update)
                await db.commit()
                merged = await _fetch_professor(db, existing["id"])
                return {**(merged or existing), "_deduped": True}
        raise
    finally:
        await db.close()


async def get_professors() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM professors ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_professor(prof_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM professors WHERE id = ?", (prof_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_professor_reply_status(prof_id: int, status: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE professors SET reply_status = ? WHERE id = ?", (status, prof_id)
        )
        await db.commit()
    finally:
        await db.close()


async def delete_professor(prof_id: int):
    db = await get_db()
    try:
        await db.execute("BEGIN")
        await db.execute("DELETE FROM drafts WHERE professor_id = ?", (prof_id,))
        await db.execute("DELETE FROM replies WHERE professor_id = ?", (prof_id,))
        cursor = await db.execute("DELETE FROM professors WHERE id = ?", (prof_id,))
        await db.commit()
        return cursor.rowcount > 0
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def update_professor_info(prof_id: int, data: dict):
    """批量更新导师字段（只更新非 None 值）"""
    db = await get_db()
    try:
        allowed = {"name", "email", "university", "department", "homepage",
                   "google_scholar", "research_summary", "recent_papers",
                   "recommended_papers", "region", "tags"}
        update = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not update:
            return

        current = await _fetch_professor(db, prof_id)
        if not current:
            return

        candidate = {**current, **update}
        duplicate = await _find_duplicate_professor(db, candidate, exclude_id=prof_id)
        if duplicate:
            await db.close()
            await merge_professors(prof_id, duplicate["id"])
            db = await get_db()

        await _apply_professor_update(db, prof_id, update)
        await db.commit()

        current = await _fetch_professor(db, prof_id)
        duplicate = await _find_duplicate_professor(db, current or {}, exclude_id=prof_id) if current else None
        if duplicate:
            await db.close()
            await merge_professors(prof_id, duplicate["id"])
            return
    finally:
        try:
            await db.close()
        except Exception:
            pass


async def toggle_star_professor(prof_id: int) -> bool:
    """切换导师收藏状态，返回新状态"""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT is_starred FROM professors WHERE id = ?", (prof_id,))
        row = await cursor.fetchone()
        if not row:
            return False
        new_val = 0 if row[0] else 1
        await db.execute("UPDATE professors SET is_starred = ? WHERE id = ?", (new_val, prof_id))
        await db.commit()
        return bool(new_val)
    finally:
        await db.close()


async def update_professor_tags(prof_id: int, tags: list[str]) -> list[str]:
    """更新导师标签，返回新标签列表"""
    db = await get_db()
    try:
        tags_json = json.dumps(tags, ensure_ascii=False)
        await db.execute("UPDATE professors SET tags = ? WHERE id = ?", (tags_json, prof_id))
        await db.commit()
        return tags
    finally:
        await db.close()


# ── Draft CRUD ────────────────────────────────────────

async def create_draft(data: dict) -> dict:
    db = await get_db()
    try:
        prof = await _fetch_professor(db, data["professor_id"])
        if not prof:
            raise ValueError(f"Professor {data['professor_id']} does not exist")
        cursor = await db.execute(
            """INSERT INTO drafts (professor_id, subject, body, language)
               VALUES (?, ?, ?, ?)""",
            (data["professor_id"], data["subject"], data["body"],
             data.get("language", "en")),
        )
        await db.commit()
        return {**data, "id": cursor.lastrowid, "status": "pending"}
    finally:
        await db.close()


async def get_drafts(status: Optional[str] = None) -> list[dict]:
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                """SELECT d.*, p.name as professor_name, p.email as professor_email,
                          p.university as professor_university
                   FROM drafts d JOIN professors p ON d.professor_id = p.id
                   WHERE d.status = ? ORDER BY d.created_at DESC""",
                (status,),
            )
        else:
            cursor = await db.execute(
                """SELECT d.*, p.name as professor_name, p.email as professor_email,
                          p.university as professor_university
                   FROM drafts d JOIN professors p ON d.professor_id = p.id
                   ORDER BY d.created_at DESC"""
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_draft_summaries() -> list[dict]:
    """Lightweight draft metadata for list pages that only need per-professor status."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT d.id, d.professor_id, d.subject, d.language, d.status,
                      d.created_at, d.sent_at,
                      p.name as professor_name, p.email as professor_email,
                      p.university as professor_university
               FROM drafts d JOIN professors p ON d.professor_id = p.id
               ORDER BY d.created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_draft(draft_id: int) -> Optional[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT d.*, p.name as professor_name, p.email as professor_email
               FROM drafts d JOIN professors p ON d.professor_id = p.id
               WHERE d.id = ?""",
            (draft_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_draft(draft_id: int, data: dict):
    db = await get_db()
    try:
        sets = []
        vals = []
        for k, v in data.items():
            if v is not None:
                sets.append(f"{k} = ?")
                vals.append(v)
        if sets:
            vals.append(draft_id)
            await db.execute(
                f"UPDATE drafts SET {', '.join(sets)} WHERE id = ?", vals
            )
            await db.commit()
    finally:
        await db.close()


async def delete_draft(draft_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ── Reply CRUD ────────────────────────────────────────

async def create_reply(data: dict) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO replies (professor_id, subject, body, received_at)
               VALUES (?, ?, ?, ?)""",
            (data["professor_id"], data.get("subject", ""),
             data.get("body", ""), data.get("received_at", datetime.utcnow().isoformat())),
        )
        await db.commit()
        return {**data, "id": cursor.lastrowid}
    finally:
        await db.close()


async def get_replies() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT r.*, p.name as professor_name, p.email as professor_email,
                      p.university as professor_university
               FROM replies r JOIN professors p ON r.professor_id = p.id
               ORDER BY r.received_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def mark_reply_read(reply_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE replies SET is_read = 1 WHERE id = ?", (reply_id,))
        await db.commit()
    finally:
        await db.close()


# ── Blacklist ─────────────────────────────────────────


def _norm(s: str) -> str:
    """规范化用于黑名单匹配：小写 + 去空格"""
    return (s or "").strip().lower().replace(" ", "")


async def add_to_blacklist(name: str, university: str, reason: Optional[str] = None) -> dict:
    """加入黑名单（同 name+university 唯一；重复加入静默忽略）"""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO blacklist
               (name_norm, university_norm, name, university, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (_norm(name), _norm(university), name, university, reason),
        )
        await db.commit()
        return {"name": name, "university": university}
    finally:
        await db.close()


async def is_blacklisted(name: str, university: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM blacklist WHERE name_norm = ? AND university_norm = ?",
            (_norm(name), _norm(university)),
        )
        row = await cursor.fetchone()
        return row is not None
    finally:
        await db.close()


async def get_blacklist() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, university, reason, created_at FROM blacklist ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


async def remove_from_blacklist(entry_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM blacklist WHERE id = ?", (entry_id,))
        await db.commit()
    finally:
        await db.close()


# ── 统计 ──────────────────────────────────────────────

async def get_stats() -> dict:
    db = await get_db()
    try:
        total = (await (await db.execute("SELECT COUNT(*) FROM professors")).fetchone())[0]
        pending = (await (await db.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        )).fetchone())[0]
        sent = (await (await db.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'sent'"
        )).fetchone())[0]
        total_drafts = (await (await db.execute("SELECT COUNT(*) FROM drafts")).fetchone())[0]
        replies = (await (await db.execute("SELECT COUNT(*) FROM replies")).fetchone())[0]
        unread_replies = (await (await db.execute(
            "SELECT COUNT(*) FROM replies WHERE is_read = 0"
        )).fetchone())[0]
        positive_replies = (await (await db.execute(
            "SELECT COUNT(*) FROM professors WHERE reply_status = 'positive'"
        )).fetchone())[0]
        starred_without_draft = (await (await db.execute(
            """SELECT COUNT(*) FROM professors p
               WHERE p.is_starred = 1
                 AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.professor_id = p.id)"""
        )).fetchone())[0]
        # email 待补全：占位邮箱（@tbd）或为空
        profs_pending_email = (await (await db.execute(
            "SELECT COUNT(*) FROM professors WHERE email LIKE '%@tbd' OR email IS NULL OR email = ''"
        )).fetchone())[0]
        return {
            "total_professors": total,
            "drafts_pending": pending,
            "emails_sent": sent,
            "total_drafts": total_drafts,
            "replies_received": replies,
            "unread_replies": unread_replies,
            "positive_replies": positive_replies,
            "starred_without_draft": starred_without_draft,
            "profs_pending_email": profs_pending_email,
        }
    finally:
        await db.close()
