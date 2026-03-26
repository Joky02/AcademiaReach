"""FastAPI API 路由 — RESTful 端点"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.core import database as db
from backend.core.models import (
    ProfessorCreate, DraftUpdate, SearchRequest,
)
from backend.agents.search_agent import search_professors
from backend.agents.compose_agent import compose_emails
from backend.services.send_service import send_email, send_batch
from backend.services.reply_tracker import check_replies
from backend.api.websocket import manager

router = APIRouter(prefix="/api")


# ── 统计 ──────────────────────────────────────────────

@router.get("/stats")
async def get_stats():
    return await db.get_stats()


# ── 导师 CRUD ─────────────────────────────────────────

@router.get("/professors")
async def list_professors():
    return await db.get_professors()


@router.post("/professors")
async def add_professor(prof: ProfessorCreate):
    data = prof.model_dump()
    result = await db.create_professor(data)
    return result


@router.get("/professors/{prof_id}")
async def get_professor(prof_id: int):
    p = await db.get_professor(prof_id)
    if not p:
        raise HTTPException(status_code=404, detail="导师不存在")
    return p


@router.delete("/professors/{prof_id}")
async def delete_professor(prof_id: int):
    await db.delete_professor(prof_id)
    return {"message": "已删除"}


# ── 搜索导师 ──────────────────────────────────────────

_search_task: Optional[asyncio.Task] = None


@router.post("/search/start")
async def start_search(req: SearchRequest):
    """启动导师搜索（后台任务，进度通过 WebSocket 推送）"""
    global _search_task
    if _search_task and not _search_task.done():
        return {"message": "搜索正在进行中，请先终止当前搜索"}

    async def _run():
        try:
            async for msg in search_professors(
                keywords=req.keywords,
                regions=req.regions,
                max_results=req.max_results,
            ):
                await manager.broadcast({"channel": "search", **msg})
        except asyncio.CancelledError:
            await manager.broadcast({"channel": "search", "type": "error", "message": "搜索已被用户终止"})
        except Exception as e:
            logger.exception("搜索任务异常")
            await manager.broadcast({"channel": "search", "type": "error", "message": str(e)})

    _search_task = asyncio.create_task(_run())
    return {"message": "搜索已启动"}


@router.post("/search/stop")
async def stop_search():
    """终止正在进行的搜索"""
    global _search_task
    if _search_task and not _search_task.done():
        _search_task.cancel()
        _search_task = None
        return {"message": "搜索已终止"}
    return {"message": "当前没有正在进行的搜索"}


# ── 邮件草稿 ──────────────────────────────────────────

@router.get("/drafts")
async def list_drafts(status: Optional[str] = None):
    return await db.get_drafts(status=status)


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: int):
    d = await db.get_draft(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return d


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: int, data: DraftUpdate):
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    await db.update_draft(draft_id, update_data)
    return await db.get_draft(draft_id)


class ComposeRequest(BaseModel):
    professor_ids: Optional[list[int]] = None


@router.post("/compose/start")
async def start_compose(req: ComposeRequest):
    """启动邮件生成（后台任务，进度通过 WebSocket 推送）"""

    async def _run():
        try:
            async for msg in compose_emails(professor_ids=req.professor_ids):
                await manager.broadcast({"channel": "compose", **msg})
        except Exception as e:
            logger.exception("邮件生成任务异常")
            await manager.broadcast({"channel": "compose", "type": "error", "message": str(e)})

    asyncio.create_task(_run())
    return {"message": "邮件生成已启动，请通过 WebSocket 查看进度"}


# ── 邮件发送 ──────────────────────────────────────────

@router.post("/send/{draft_id}")
async def send_single(draft_id: int):
    result = await send_email(draft_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


class BatchSendRequest(BaseModel):
    draft_ids: list[int]


@router.post("/send/batch")
async def send_batch_endpoint(req: BatchSendRequest):
    results = await send_batch(req.draft_ids)
    return {"results": results}


# ── 回复跟踪 ──────────────────────────────────────────

@router.get("/replies")
async def list_replies():
    return await db.get_replies()


@router.post("/replies/check")
async def trigger_check_replies():
    """手动触发一次回复检查"""
    new_replies = await check_replies()
    return {"new_replies": len(new_replies), "data": new_replies}


@router.put("/replies/{reply_id}/read")
async def mark_read(reply_id: int):
    await db.mark_reply_read(reply_id)
    return {"message": "已标记为已读"}


# ── 配置 ──────────────────────────────────────────────

@router.get("/config/profile")
async def get_profile():
    from backend.core.llm import load_profile
    return {"content": load_profile()}


@router.put("/config/profile")
async def update_profile(data: dict):
    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "config" / "my_profile.md"
    content = data.get("content", "")
    profile_path.write_text(content, encoding="utf-8")
    return {"message": "Profile 已更新"}


@router.get("/config/settings")
async def get_settings():
    from backend.core.llm import load_yaml_config
    cfg = load_yaml_config()
    # 隐藏敏感信息
    safe_cfg = {
        "llm": {"provider": cfg.get("llm", {}).get("provider", "openai")},
        "search": {
            "keywords": cfg.get("search", {}).get("keywords", []),
            "regions": cfg.get("search", {}).get("regions", []),
            "max_professors": cfg.get("search", {}).get("max_professors", 20),
        },
        "smtp": {
            "host": cfg.get("smtp", {}).get("host", ""),
            "port": cfg.get("smtp", {}).get("port", 587),
            "username": cfg.get("smtp", {}).get("username", ""),
            "configured": bool(cfg.get("smtp", {}).get("password")),
        },
        "imap": {
            "host": cfg.get("imap", {}).get("host", ""),
            "configured": bool(cfg.get("imap", {}).get("password")),
            "poll_interval": cfg.get("imap", {}).get("poll_interval", 300),
        },
    }
    return safe_cfg


# ── 简历管理 ──────────────────────────────────────

CV_DIR = Path(__file__).parent.parent / "config"


@router.get("/config/cv")
async def get_cv_status():
    """获取中英文简历上传状态"""
    cn_path = CV_DIR / "cv_cn.pdf"
    en_path = CV_DIR / "cv_en.pdf"
    return {
        "cv_cn": {
            "uploaded": cn_path.exists(),
            "size": cn_path.stat().st_size if cn_path.exists() else 0,
        },
        "cv_en": {
            "uploaded": en_path.exists(),
            "size": en_path.stat().st_size if en_path.exists() else 0,
        },
    }


@router.post("/config/cv/{lang}")
async def upload_cv(lang: str, file: UploadFile = File(...)):
    """上传简历 (lang: cn 或 en)"""
    if lang not in ("cn", "en"):
        raise HTTPException(status_code=400, detail="lang 必须为 cn 或 en")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 格式")

    target = CV_DIR / f"cv_{lang}.pdf"
    content = await file.read()
    target.write_bytes(content)
    return {"message": f"{'中文' if lang == 'cn' else '英文'}简历已上传", "size": len(content)}


# ── 自定义 Prompt 管理 ─────────────────────────────

DEFAULT_PROMPTS = {
    "search_preference": "找与我研究方向匹配的、正在招 PhD 的教授。优先找近两年有活跃论文发表的导师。",
    "compose_style_cn": "语气自然真诚，像同行之间交流。提到我和导师研究方向的具体交集，不要泛泛而谈。",
    "compose_style_en": "Be direct and specific. Mention a concrete connection between my work and the professor's recent research.",
    "compose_extra_cn": "",
    "compose_extra_en": "",
}


@router.get("/config/prompts")
async def get_prompts():
    """获取自定义 prompt 配置"""
    from backend.core.llm import load_yaml_config
    cfg = load_yaml_config()
    saved = cfg.get("prompts", {})
    # 合并默认值和已保存值
    result = {**DEFAULT_PROMPTS, **saved}
    return result


class PromptsUpdate(BaseModel):
    search_preference: Optional[str] = None
    compose_style_cn: Optional[str] = None
    compose_style_en: Optional[str] = None
    compose_extra_cn: Optional[str] = None
    compose_extra_en: Optional[str] = None


@router.put("/config/prompts")
async def update_prompts(data: PromptsUpdate):
    """更新自定义 prompt 配置（写入 config.yaml）"""
    from backend.core.llm import CONFIG_PATH, load_yaml_config
    cfg = load_yaml_config()
    if "prompts" not in cfg:
        cfg["prompts"] = {}
    for field in ["search_preference", "compose_style_cn", "compose_style_en", "compose_extra_cn", "compose_extra_en"]:
        val = getattr(data, field)
        if val is not None:
            cfg["prompts"][field] = val
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {"message": "自定义 Prompt 已更新", **{**DEFAULT_PROMPTS, **cfg["prompts"]}}


# ── 搜索关键词管理 ────────────────────────────────

class KeywordsUpdate(BaseModel):
    keywords: list[str]
    regions: Optional[list[str]] = None


@router.put("/config/keywords")
async def update_keywords(data: KeywordsUpdate):
    """更新搜索关键词和地区（写入 config.yaml）"""
    from backend.core.llm import CONFIG_PATH, load_yaml_config
    cfg = load_yaml_config()
    if "search" not in cfg:
        cfg["search"] = {}
    cfg["search"]["keywords"] = data.keywords
    if data.regions is not None:
        cfg["search"]["regions"] = data.regions
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {"message": "搜索关键词已更新", "keywords": data.keywords, "regions": cfg["search"].get("regions", [])}


# ── 邮箱验证 ──────────────────────────────────────

class EmailConfig(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool = True
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    imap_use_ssl: bool = True
    save: bool = False  # 验证通过后是否保存到 config.yaml


@router.get("/config/email")
async def get_email_config():
    """获取当前邮箱配置（密码脱敏）"""
    from backend.core.llm import load_yaml_config
    cfg = load_yaml_config()
    smtp = cfg.get("smtp", {})
    imap = cfg.get("imap", {})
    return {
        "smtp": {
            "host": smtp.get("host", ""),
            "port": smtp.get("port", 587),
            "username": smtp.get("username", ""),
            "password_set": bool(smtp.get("password", "")),
            "use_tls": smtp.get("use_tls", True),
        },
        "imap": {
            "host": imap.get("host", ""),
            "port": imap.get("port", 993),
            "username": imap.get("username", ""),
            "password_set": bool(imap.get("password", "")),
            "use_ssl": imap.get("use_ssl", True),
        },
    }


@router.post("/config/email/verify")
async def verify_email(data: EmailConfig):
    """验证 SMTP 和 IMAP 连接"""
    import smtplib
    import imaplib

    results = {"smtp": {"ok": False, "message": ""}, "imap": {"ok": False, "message": ""}}

    # 验证 SMTP
    try:
        if data.smtp_use_tls:
            server = smtplib.SMTP(data.smtp_host, data.smtp_port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(data.smtp_host, data.smtp_port, timeout=10)
        server.login(data.smtp_username, data.smtp_password)
        server.quit()
        results["smtp"] = {"ok": True, "message": "SMTP 连接成功"}
    except Exception as e:
        results["smtp"] = {"ok": False, "message": f"SMTP 失败: {e}"}

    # 验证 IMAP
    try:
        if data.imap_use_ssl:
            mail = imaplib.IMAP4_SSL(data.imap_host, data.imap_port)
        else:
            mail = imaplib.IMAP4(data.imap_host, data.imap_port)
        mail.login(data.imap_username, data.imap_password)
        mail.logout()
        results["imap"] = {"ok": True, "message": "IMAP 连接成功"}
    except Exception as e:
        results["imap"] = {"ok": False, "message": f"IMAP 失败: {e}"}

    # 如果验证通过且要求保存
    if data.save and results["smtp"]["ok"] and results["imap"]["ok"]:
        from backend.core.llm import CONFIG_PATH, load_yaml_config
        cfg = load_yaml_config()
        cfg["smtp"] = {
            "host": data.smtp_host, "port": data.smtp_port,
            "username": data.smtp_username, "password": data.smtp_password,
            "use_tls": data.smtp_use_tls,
        }
        cfg["imap"] = {
            "host": data.imap_host, "port": data.imap_port,
            "username": data.imap_username, "password": data.imap_password,
            "use_ssl": data.imap_use_ssl, "poll_interval": 300,
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        results["saved"] = True

    return results


# ── WebSocket ─────────────────────────────────────

@router.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接，接收客户端心跳
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
