"""邮件发送服务 — SMTP 发送 + 发送记录"""

from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from pathlib import Path
from typing import Optional

from backend.core.llm import load_yaml_config
from backend.core import database as db
from backend.core.attachments import PAPERS_DIR, get_attachment_path, migrate_legacy_attachments
from backend.services.smtp_client import create_smtp_client, describe_smtp_connection_error


def _get_smtp_config() -> dict:
    cfg = load_yaml_config()
    return cfg.get("smtp", {})


def _get_cv_path(language: str) -> Optional[Path]:
    """根据语言返回对应的简历文件路径"""
    migrate_legacy_attachments()
    return get_attachment_path("cv", "cn" if language == "cn" else "en")


def _get_transcript_path(language: str) -> Optional[Path]:
    """根据语言返回对应的成绩单文件路径"""
    migrate_legacy_attachments()
    return get_attachment_path("transcript", "cn" if language == "cn" else "en")


def _get_papers() -> list[Path]:
    """返回 papers/ 目录下所有 PDF（按文件名排序）"""
    if not PAPERS_DIR.exists():
        return []
    return sorted(p for p in PAPERS_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


def _parse_recipients(value: str) -> list[str]:
    """Parse a comma-separated address field and discard malformed entries."""
    return [address for _, address in getaddresses([value]) if "@" in address]


def _attach_pdf(msg: MIMEMultipart, path: Path) -> None:
    """把一个 PDF 文件挂到 mime message 上"""
    with open(path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)


def _deliver_message(
    smtp_cfg: dict,
    from_email: str,
    recipients: list[str],
    message: str,
) -> dict:
    """Perform blocking SMTP I/O outside the FastAPI event loop."""
    server = create_smtp_client(smtp_cfg)
    try:
        server.login(from_email, smtp_cfg["password"])
        return server.sendmail(from_email, recipients, message)
    finally:
        try:
            server.quit()
        except Exception:
            server.close()


async def send_email(draft_id: int, include_cc: bool = False) -> dict:
    """
    发送单封邮件。

    返回:
      {"success": True/False, "message": "..."}
    """
    draft = await db.get_draft(draft_id)
    if not draft:
        return {"success": False, "message": "草稿不存在"}

    if draft["status"] == "sent":
        return {"success": False, "message": "该邮件已发送过"}

    smtp_cfg = _get_smtp_config()
    if not smtp_cfg.get("username") or smtp_cfg["username"] == "your-email@gmail.com":
        return {"success": False, "message": "请先在 config.yaml 中配置 SMTP 发件信息"}

    to_email = draft["professor_email"]
    from_email = smtp_cfg["username"]
    cc_emails = _parse_recipients(smtp_cfg.get("cc", "")) if include_cc else []
    if include_cc and not cc_emails:
        return {"success": False, "message": "已选择抄送，但尚未配置有效的抄送地址"}

    # 构建邮件（mixed 类型以支持附件）
    msg = MIMEMultipart("mixed")
    msg["Subject"] = draft["subject"]
    from_name = smtp_cfg.get("from_name", "").strip()
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.rpartition("@")[2] or None)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    msg.attach(MIMEText(draft["body"], "plain", "utf-8"))

    # 附件：简历 + 成绩单（按导师所在地区选中/英）+ 论文（papers/ 全部）
    lang = draft.get("language", "en")
    cv_path = _get_cv_path(lang)
    if cv_path:
        _attach_pdf(msg, cv_path)
    transcript_path = _get_transcript_path(lang)
    if transcript_path:
        _attach_pdf(msg, transcript_path)
    for paper_path in _get_papers():
        _attach_pdf(msg, paper_path)

    try:
        refused = await asyncio.to_thread(
            _deliver_message,
            smtp_cfg,
            from_email,
            [to_email, *cc_emails],
            msg.as_string(),
        )

        refused_by_address = {address.lower(): reason for address, reason in refused.items()}
        if to_email.lower() in refused_by_address:
            code, detail = refused_by_address[to_email.lower()]
            return {
                "success": False,
                "message": f"导师邮箱被服务器拒收: ({code}) {detail!r}",
            }

        # 更新草稿状态
        await db.update_draft(draft_id, {
            "status": "sent",
            "sent_at": datetime.utcnow().isoformat(),
        })

        refused_cc = [address for address in cc_emails if address.lower() in refused_by_address]
        if refused_cc:
            return {
                "success": True,
                "message": f"邮件已发送至导师，但抄送地址被拒收: {', '.join(refused_cc)}",
            }
        return {"success": True, "message": f"邮件已成功发送至 {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP 认证失败，请检查邮箱密码/授权码"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP 发送错误: {e}"}
    except OSError as e:
        return {"success": False, "message": describe_smtp_connection_error(e, smtp_cfg)}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {e}"}


async def send_batch(draft_ids: list[int], include_cc: bool = False) -> list[dict]:
    """批量发送邮件"""
    results = []
    for did in draft_ids:
        result = await send_email(did, include_cc=include_cc)
        result["draft_id"] = did
        results.append(result)
    return results
