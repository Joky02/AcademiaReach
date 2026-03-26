"""邮件发送服务 — SMTP 发送 + 发送记录"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from backend.core.llm import load_yaml_config
from backend.core import database as db


CV_DIR = Path(__file__).parent.parent / "config"


def _get_smtp_config() -> dict:
    cfg = load_yaml_config()
    return cfg.get("smtp", {})


def _get_cv_path(language: str) -> Optional[Path]:
    """根据语言返回对应的简历文件路径"""
    filename = "cv_cn.pdf" if language == "cn" else "cv_en.pdf"
    path = CV_DIR / filename
    return path if path.exists() else None


async def send_email(draft_id: int) -> dict:
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

    # 构建邮件（mixed 类型以支持附件）
    msg = MIMEMultipart("mixed")
    msg["Subject"] = draft["subject"]
    msg["From"] = f"{smtp_cfg.get('from_name', '')} <{from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(draft["body"], "plain", "utf-8"))

    # 附加简历
    lang = draft.get("language", "en")
    cv_path = _get_cv_path(lang)
    if cv_path:
        with open(cv_path, "rb") as f:
            cv_attach = MIMEApplication(f.read(), _subtype="pdf")
            cv_attach.add_header(
                "Content-Disposition", "attachment",
                filename=cv_path.name,
            )
            msg.attach(cv_attach)

    try:
        if smtp_cfg.get("use_tls", True):
            server = smtplib.SMTP(smtp_cfg["host"], smtp_cfg.get("port", 587))
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_cfg["host"], smtp_cfg.get("port", 465))

        server.login(from_email, smtp_cfg["password"])
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()

        # 更新草稿状态
        await db.update_draft(draft_id, {
            "status": "sent",
            "sent_at": datetime.utcnow().isoformat(),
        })

        return {"success": True, "message": f"邮件已成功发送至 {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP 认证失败，请检查邮箱密码/授权码"}
    except smtplib.SMTPException as e:
        return {"success": False, "message": f"SMTP 发送错误: {e}"}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {e}"}


async def send_batch(draft_ids: list[int]) -> list[dict]:
    """批量发送邮件"""
    results = []
    for did in draft_ids:
        result = await send_email(did)
        result["draft_id"] = did
        results.append(result)
    return results
