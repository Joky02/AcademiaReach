"""回复跟踪服务 — IMAP 轮询收件箱，匹配导师回复"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from datetime import datetime
from email.header import decode_header
from typing import Optional

import re

from backend.core.llm import load_yaml_config
from backend.core import database as db

logger = logging.getLogger(__name__)

# 简单的邮箱格式校验：纯 ASCII、包含 @、域名部分有点号
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def _get_imap_config() -> dict:
    cfg = load_yaml_config()
    return cfg.get("imap", {})


def _decode_header_value(value: str) -> str:
    """解码邮件头部"""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_email_body(msg: email.message.Message) -> str:
    """提取邮件正文"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # fallback: try html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _save_reply(new_replies: list, reply_data: dict):
    """同步辅助：收集待保存的回复（实际写入在主函数中完成）"""
    new_replies.append(reply_data)


def _parse_msg(msg: email.message.Message) -> dict:
    """从邮件消息中提取 subject / body / received_at"""
    subject = _decode_header_value(msg.get("Subject", ""))
    body = _get_email_body(msg)
    date_str = msg.get("Date", "")
    try:
        received_at = email.utils.parsedate_to_datetime(date_str).isoformat()
    except Exception:
        received_at = datetime.utcnow().isoformat()
    return {"subject": subject, "body": body[:5000], "received_at": received_at}


async def check_replies() -> list[dict]:
    """
    检查收件箱中是否有导师的回复邮件。
    双策略匹配：
      1. FROM 匹配 — 导师用已知邮箱回复
      2. SUBJECT 匹配 — 导师用其他邮箱回复，但主题匹配已发送邮件
    返回新匹配到的回复列表。
    """
    imap_cfg = _get_imap_config()
    if not imap_cfg.get("username") or imap_cfg["username"] == "your-email@gmail.com":
        logger.warning("IMAP 未配置，跳过回复检查")
        return []

    professors = await db.get_professors()
    if not professors:
        return []

    # 已有回复的导师，避免重复
    existing_replies = await db.get_replies()
    replied_prof_ids = {r["professor_id"] for r in existing_replies}

    # 策略 1 数据：导师邮箱 → 导师
    prof_email_map = {}
    for p in professors:
        addr = (p.get("email") or "").strip()
        if not addr or not _EMAIL_RE.match(addr):
            continue
        prof_email_map[addr.lower()] = p

    # 策略 2 数据：已发送邮件的主题 → 导师（用于主题匹配）
    drafts = await db.get_drafts()
    sent_drafts = [d for d in drafts if d.get("status") == "sent" and d.get("subject")]
    # subject 关键词 → professor_id
    subject_prof_map = {}
    for d in sent_drafts:
        subject_prof_map[d["subject"].strip()] = d["professor_id"]

    if not prof_email_map and not subject_prof_map:
        logger.info("没有可用于回复检查的导师邮箱或已发送邮件")
        return []

    # 建 professor id → professor 的快查表
    prof_by_id = {p["id"]: p for p in professors}

    new_replies = []
    matched_msg_ids = set()  # 避免同一封邮件被两个策略重复匹配

    try:
        if imap_cfg.get("use_ssl", True):
            mail = imaplib.IMAP4_SSL(imap_cfg["host"], imap_cfg.get("port", 993))
        else:
            mail = imaplib.IMAP4(imap_cfg["host"], imap_cfg.get("port", 143))

        mail.login(imap_cfg["username"], imap_cfg["password"])
        mail.select("INBOX")

        # ── 策略 1：按 FROM 匹配 ──
        for prof_email, prof in prof_email_map.items():
            if prof["id"] in replied_prof_ids:
                continue
            try:
                _, msg_nums = mail.search(None, f'(FROM "{prof_email}")')
                if not msg_nums[0]:
                    continue
                for num in msg_nums[0].split():
                    if num in matched_msg_ids:
                        continue
                    matched_msg_ids.add(num)
                    _, msg_data = mail.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    parsed = _parse_msg(msg)
                    reply_data = {"professor_id": prof["id"], **parsed}
                    try:
                        saved = await db.create_reply(reply_data)
                        new_replies.append(saved)
                        await db.update_professor_reply_status(prof["id"], "replied")
                        replied_prof_ids.add(prof["id"])
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"[FROM] 检查 {prof_email} 的回复时出错: {e}")

        # ── 策略 2：按 SUBJECT 匹配已发送邮件的回复 ──
        for orig_subject, prof_id in subject_prof_map.items():
            if prof_id in replied_prof_ids:
                continue
            try:
                # IMAP SUBJECT 搜索需要用 UTF-8 编码处理非 ASCII 字符
                search_subject = orig_subject
                try:
                    search_subject.encode("ascii")
                    _, msg_nums = mail.search(None, f'(SUBJECT "{search_subject}")')
                except UnicodeEncodeError:
                    _, msg_nums = mail.search("UTF-8", f'(SUBJECT "{search_subject}")'.encode("utf-8"))

                if not msg_nums[0]:
                    continue

                for num in msg_nums[0].split():
                    if num in matched_msg_ids:
                        continue
                    _, msg_data = mail.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    parsed = _parse_msg(msg)

                    # 只匹配 "Re:" 开头的回复（排除自己发出的原始邮件）
                    subj = parsed["subject"].strip()
                    if not subj.lower().startswith("re:"):
                        continue

                    matched_msg_ids.add(num)
                    reply_data = {"professor_id": prof_id, **parsed}
                    try:
                        saved = await db.create_reply(reply_data)
                        new_replies.append(saved)
                        await db.update_professor_reply_status(prof_id, "replied")
                        replied_prof_ids.add(prof_id)
                        logger.info(f"[SUBJECT] 匹配到回复: prof_id={prof_id}, subject={subj[:50]}")
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"[SUBJECT] 检查主题匹配时出错: {e}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP 连接错误: {e}")
    except Exception as e:
        logger.error(f"回复检查出错: {e}")

    return new_replies


async def start_reply_polling():
    """后台轮询任务：定期检查收件箱"""
    imap_cfg = _get_imap_config()
    interval = imap_cfg.get("poll_interval", 300)

    while True:
        try:
            new_replies = await check_replies()
            if new_replies:
                logger.info(f"发现 {len(new_replies)} 封新回复")
        except Exception as e:
            logger.error(f"轮询出错: {e}")
        await asyncio.sleep(interval)
