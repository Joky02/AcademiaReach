"""SQLite 数据库操作 — 异步，基于 aiosqlite"""

from __future__ import annotations

import aiosqlite
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "taoci.db")


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
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
        await db.commit()
    finally:
        await db.close()


# ── Professor CRUD ────────────────────────────────────

async def create_professor(data: dict) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO professors
               (name, email, university, department, homepage, google_scholar,
                research_summary, recent_papers, region, source, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"], data["email"], data["university"],
                data.get("department"), data.get("homepage"),
                data.get("google_scholar"),
                data.get("research_summary"), data.get("recent_papers"),
                data.get("region"), data.get("source", "manual"),
                data.get("tags", "[]"),
            ),
        )
        await db.commit()
        prof_id = cursor.lastrowid
        return {**data, "id": prof_id}
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
        await db.execute("DELETE FROM professors WHERE id = ?", (prof_id,))
        await db.commit()
    finally:
        await db.close()


async def update_professor_info(prof_id: int, data: dict):
    """批量更新导师字段（只更新非 None 值）"""
    db = await get_db()
    try:
        allowed = {"name", "email", "university", "department", "homepage",
                   "google_scholar", "research_summary", "recent_papers",
                   "region", "tags"}
        sets, vals = [], []
        for k, v in data.items():
            if k in allowed and v is not None:
                sets.append(f"{k} = ?")
                vals.append(v)
        if sets:
            vals.append(prof_id)
            await db.execute(
                f"UPDATE professors SET {', '.join(sets)} WHERE id = ?", vals
            )
            await db.commit()
    finally:
        await db.close()


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
        await db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        await db.commit()
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
