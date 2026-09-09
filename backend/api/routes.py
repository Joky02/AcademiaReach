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
from backend.core.attachments import (
    PAPERS_DIR,
    attachment_path,
    get_attachment_path,
    migrate_legacy_attachments,
    remove_legacy_attachment,
)
from backend.core.models import (
    ProfessorCreate, DraftUpdate, SearchRequest,
)
from backend.core.codex_client import get_codex_worker_status
from backend.core.pi_client import get_pi_worker_status
from backend.core.agent_llm import agent_invoke_options
from backend.agents.search_agent import (
    enrich_professor,
    recommend_papers_for_professor,
    search_professors,
)
from backend.agents.compose_agent import compose_emails
from backend.services.send_service import send_email, send_batch
from backend.services.draft_review import rank_drafts
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
    if not data.get("email"):
        data["email"] = f"unknown-{data['name'].lower().replace(' ', '.')}@tbd"
    result = await db.create_professor(data)
    enrichment = await start_enrich_prof(int(result["id"]))
    return {
        **result,
        "enrich_started": bool(enrichment.get("started")),
    }


@router.post("/professors/dedupe")
async def dedupe_professors():
    """合并已有重复导师。任一有效邮箱、Google Scholar 或非通用主页一致即视为同一导师。"""
    merges = await db.dedupe_professors()
    return {"merged": len(merges), "items": merges}


@router.get("/professors/{prof_id}")
async def get_professor(prof_id: int):
    p = await db.get_professor(prof_id)
    if not p:
        raise HTTPException(status_code=404, detail="导师不存在")
    return p


@router.delete("/professors/{prof_id}")
async def delete_professor(prof_id: int, blacklist: bool = True):
    """删除导师；默认同时加入黑名单（后续搜索不再推荐）。
    传 ?blacklist=false 可仅删除不拉黑。"""
    prof = await db.get_professor(prof_id)
    if not prof:
        raise HTTPException(status_code=404, detail="导师不存在")
    if blacklist:
        await db.add_to_blacklist(prof["name"], prof["university"], reason="用户从列表删除")
    await db.delete_professor(prof_id)
    return {"message": "已删除", "blacklisted": blacklist}


# ── 黑名单 ────────────────────────────────────────────


@router.get("/blacklist")
async def list_blacklist():
    return await db.get_blacklist()


@router.delete("/blacklist/{entry_id}")
async def delete_blacklist_entry(entry_id: int):
    await db.remove_from_blacklist(entry_id)
    return {"message": "已移出黑名单"}


class ProfessorUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    university: Optional[str] = None
    department: Optional[str] = None
    homepage: Optional[str] = None
    google_scholar: Optional[str] = None
    research_summary: Optional[str] = None
    recent_papers: Optional[str] = None
    recommended_papers: Optional[str] = None
    region: Optional[str] = None


@router.put("/professors/{prof_id}")
async def update_professor(prof_id: int, body: ProfessorUpdate):
    """手动编辑导师信息"""
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")
    await db.update_professor_info(prof_id, data)
    prof = await db.get_professor(prof_id)
    return prof


@router.put("/professors/{prof_id}/star")
async def toggle_star(prof_id: int):
    """切换导师收藏状态"""
    starred = await db.toggle_star_professor(prof_id)
    return {"is_starred": starred}


class TagsUpdate(BaseModel):
    tags: list[str]


@router.put("/professors/{prof_id}/tags")
async def update_tags(prof_id: int, body: TagsUpdate):
    """更新导师标签"""
    tags = await db.update_professor_tags(prof_id, body.tags)
    return {"tags": tags}


@router.post("/professors/{prof_id}/enrich")
async def enrich_prof(prof_id: int):
    """搜索并补全导师信息（邮箱、主页、研究方向、标签等）"""
    result = await enrich_professor(prof_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "补全失败"))
    return result


_enrich_tasks: dict[int, asyncio.Task] = {}


def _active_enrich_ids() -> list[int]:
    done_ids = [prof_id for prof_id, task in _enrich_tasks.items() if task.done()]
    for prof_id in done_ids:
        _enrich_tasks.pop(prof_id, None)
    return sorted(_enrich_tasks)


@router.get("/professors/enrich/status")
async def get_enrich_status():
    """返回当前仍在后台运行的导师补全任务。前端用它校准并发补全状态。"""
    active_ids = _active_enrich_ids()
    return {"active_ids": active_ids, "count": len(active_ids)}


@router.post("/professors/{prof_id}/enrich/start")
async def start_enrich_prof(prof_id: int):
    """后台补全单个导师信息，进度通过 WebSocket 推送。"""
    existing = _enrich_tasks.get(prof_id)
    if existing and not existing.done():
        active_ids = _active_enrich_ids()
        return {
            "message": "该导师正在补全中",
            "professor_id": prof_id,
            "started": False,
            "active_ids": active_ids,
        }

    prof = await db.get_professor(prof_id)
    if not prof:
        raise HTTPException(status_code=404, detail="导师不存在")

    async def _run():
        async def emit(message: str):
            await manager.broadcast({
                "channel": "enrich",
                "type": "progress",
                "professor_id": prof_id,
                "message": message,
            })

        try:
            await emit(f"启动补全：{prof['name']} @ {prof['university']}")
            result = await enrich_professor(prof_id, progress=emit)
            if result.get("success"):
                fields = result.get("updated_fields", [])
                await manager.broadcast({
                    "channel": "enrich",
                    "type": "done",
                    "professor_id": prof_id,
                    "updated_fields": fields,
                    "message": f"补全完成：{prof['name']}（{len(fields)} 个字段更新）",
                })
            else:
                await manager.broadcast({
                    "channel": "enrich",
                    "type": "error",
                    "professor_id": prof_id,
                    "message": result.get("message", "补全失败"),
                })
        except Exception as e:
            logger.exception("导师补全任务异常")
            await manager.broadcast({
                "channel": "enrich",
                "type": "error",
                "professor_id": prof_id,
                "message": str(e),
            })
        finally:
            _enrich_tasks.pop(prof_id, None)

    _enrich_tasks[prof_id] = asyncio.create_task(_run())
    active_ids = _active_enrich_ids()
    return {
        "message": "补全已启动",
        "professor_id": prof_id,
        "started": True,
        "active_ids": active_ids,
    }


class PaperRecommendationRequest(BaseModel):
    professor_ids: list[int]


_paper_recommendation_task: Optional[asyncio.Task] = None
_paper_recommendation_state = {
    "running": False,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "logs": [],
}


def _paper_recommendation_status() -> dict:
    return {
        **_paper_recommendation_state,
        "logs": list(_paper_recommendation_state["logs"][-200:]),
    }


@router.get("/paper-recommendations/status")
async def paper_recommendation_status():
    return _paper_recommendation_status()


@router.post("/paper-recommendations/start")
async def start_paper_recommendations(req: PaperRecommendationRequest):
    """Refresh recommendations only; professor identity and metadata remain untouched."""
    global _paper_recommendation_task
    if _paper_recommendation_task and not _paper_recommendation_task.done():
        return {"message": "论文推荐任务正在运行", **_paper_recommendation_status()}

    professor_ids = list(dict.fromkeys(int(value) for value in req.professor_ids))
    if not professor_ids:
        raise HTTPException(status_code=400, detail="请选择至少一位导师")

    _paper_recommendation_state.update({
        "running": True,
        "total": len(professor_ids),
        "completed": 0,
        "failed": 0,
        "logs": [],
    })

    async def append_log(message: str, professor_id: Optional[int] = None):
        _paper_recommendation_state["logs"].append(message)
        await manager.broadcast({
            "channel": "recommend",
            "type": "progress",
            "professor_id": professor_id,
            "message": message,
        })

    async def _run():
        semaphore = asyncio.Semaphore(4)

        async def process(professor_id: int):
            async with semaphore:
                professor = await db.get_professor(professor_id)
                if not professor:
                    _paper_recommendation_state["failed"] += 1
                    await append_log(f"导师 {professor_id} 不存在", professor_id)
                    return

                async def emit(message: str):
                    await append_log(f"{professor['name']}：{message}", professor_id)

                try:
                    result = await recommend_papers_for_professor(
                        professor_id,
                        progress=emit,
                    )
                    if result.get("success"):
                        _paper_recommendation_state["completed"] += 1
                    else:
                        _paper_recommendation_state["failed"] += 1
                        await append_log(
                            f"{professor['name']}：{result.get('message', '推荐失败')}",
                            professor_id,
                        )
                except Exception as exc:
                    logger.exception("论文推荐任务异常: %s", professor["name"])
                    _paper_recommendation_state["failed"] += 1
                    await append_log(f"{professor['name']}：{exc}", professor_id)

        try:
            await asyncio.gather(*(process(professor_id) for professor_id in professor_ids))
        finally:
            _paper_recommendation_state["running"] = False
            await manager.broadcast({
                "channel": "recommend",
                "type": "done",
                "message": (
                    f"论文推荐完成：{_paper_recommendation_state['completed']} 成功，"
                    f"{_paper_recommendation_state['failed']} 失败"
                ),
            })

    _paper_recommendation_task = asyncio.create_task(_run())
    return {"message": "论文推荐任务已启动", **_paper_recommendation_status()}


# ── 搜索导师 ──────────────────────────────────────────

_search_task: Optional[asyncio.Task] = None
_SEARCH_LOG_LIMIT = 200
_search_state: dict = {
    "running": False,
    "logs": [],
    "last_error": None,
}


def _record_search_message(message: dict) -> None:
    text = str(message.get("message") or "").strip()
    message_type = message.get("type")
    if message_type == "done" and not text:
        total = message.get("total")
        text = f"搜索完成，导师库当前共 {total} 人" if total is not None else "搜索完成"
    if text:
        _search_state["logs"] = [*_search_state["logs"], text][-_SEARCH_LOG_LIMIT:]
    if message_type == "error":
        _search_state["last_error"] = text or "搜索失败"


def _search_status() -> dict:
    running = bool(_search_task and not _search_task.done())
    _search_state["running"] = running
    return {
        "running": running,
        "logs": list(_search_state["logs"]),
        "last_error": _search_state["last_error"],
    }


@router.get("/search/status")
async def get_search_status():
    """返回搜索任务真实状态和最近日志，供前端刷新后恢复。"""
    return _search_status()


@router.post("/search/start")
async def start_search(req: SearchRequest):
    """启动导师搜索（后台任务，进度通过 WebSocket 推送）"""
    global _search_task
    if _search_task and not _search_task.done():
        return {
            "started": False,
            "message": "搜索正在进行中",
            **_search_status(),
        }

    _search_state.update({
        "running": True,
        "logs": ["搜索任务已提交，正在启动 Agent"],
        "last_error": None,
    })

    async def _run():
        global _search_task
        current_task = asyncio.current_task()
        try:
            async for msg in search_professors(
                keywords=req.keywords,
                regions=req.regions,
                max_results=req.max_results,
            ):
                _record_search_message(msg)
                await manager.broadcast({"channel": "search", **msg})
        except asyncio.CancelledError:
            message = {"type": "error", "message": "搜索已被用户终止"}
            _record_search_message(message)
            await manager.broadcast({"channel": "search", **message})
        except Exception as e:
            logger.exception("搜索任务异常")
            message = {"type": "error", "message": str(e)}
            _record_search_message(message)
            await manager.broadcast({"channel": "search", **message})
        finally:
            _search_state["running"] = False
            if _search_task is current_task:
                _search_task = None

    _search_task = asyncio.create_task(_run())
    return {
        "started": True,
        "message": "搜索已启动",
        **_search_status(),
    }


@router.post("/search/stop")
async def stop_search():
    """终止正在进行的搜索"""
    global _search_task
    if _search_task and not _search_task.done():
        task = _search_task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return {"message": "搜索已终止", **_search_status()}
    return {"message": "当前没有正在进行的搜索", **_search_status()}


# ── 邮件草稿 ──────────────────────────────────────────

@router.get("/drafts")
async def list_drafts(status: Optional[str] = None):
    return await db.get_drafts(status=status)


@router.get("/drafts/summary")
async def list_draft_summaries():
    return await db.get_draft_summaries()


@router.get("/drafts/review")
async def list_draft_review_queue(status: Optional[str] = "pending"):
    from backend.core.llm import load_profile

    normalized_status = status if status in {"pending", "approved", "skipped", "sent"} else None
    rows = await db.get_draft_review_rows(status=normalized_status)
    return rank_drafts(rows, applicant_profile=load_profile())


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


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: int):
    await db.delete_draft(draft_id)
    return {"message": "已删除"}


class ComposeRequest(BaseModel):
    professor_ids: Optional[list[int]] = None
    replace_existing: bool = False
    run_deep_research: bool = True
    parallelism: int = 1


_compose_task: Optional[asyncio.Task] = None
_compose_state = {
    "running": False,
    "total": 0,
    "completed": 0,
    "failed": 0,
    "logs": [],
}


def _compose_status() -> dict:
    return {
        **_compose_state,
        "logs": list(_compose_state["logs"][-200:]),
    }


@router.get("/compose/status")
async def compose_status():
    return _compose_status()


@router.post("/compose/start")
async def start_compose(req: ComposeRequest):
    """启动邮件生成（后台任务，进度通过 WebSocket 推送）"""
    global _compose_task
    if _compose_task and not _compose_task.done():
        return {"message": "邮件生成任务正在运行", **_compose_status()}

    professor_ids = (
        list(dict.fromkeys(int(value) for value in req.professor_ids))
        if req.professor_ids
        else None
    )
    parallelism = max(1, min(int(req.parallelism), 4))
    _compose_state.update({
        "running": True,
        "total": len(professor_ids) if professor_ids else 0,
        "completed": 0,
        "failed": 0,
        "logs": [],
    })

    async def publish(msg: dict, include_terminal: bool = True):
        message = str(msg.get("message") or "").strip()
        if message:
            _compose_state["logs"].append(message)
        if msg.get("type") == "draft":
            _compose_state["completed"] += 1
        if msg.get("type") == "error" or "生成出错" in message or "解析失败" in message:
            _compose_state["failed"] += 1
        if include_terminal or msg.get("type") not in {"done", "error"}:
            await manager.broadcast({"channel": "compose", **msg})

    async def _run():
        try:
            if professor_ids and parallelism > 1:
                semaphore = asyncio.Semaphore(parallelism)

                async def process(professor_id: int):
                    async with semaphore:
                        async for msg in compose_emails(
                            professor_ids=[professor_id],
                            replace_existing=req.replace_existing,
                            run_deep_research=req.run_deep_research,
                        ):
                            await publish(msg, include_terminal=False)

                await asyncio.gather(*(process(professor_id) for professor_id in professor_ids))
                await manager.broadcast({
                    "channel": "compose",
                    "type": "done",
                    "total": _compose_state["completed"],
                    "message": (
                        f"邮件处理完成：{_compose_state['completed']} 成功，"
                        f"{_compose_state['failed']} 失败"
                    ),
                })
            else:
                async for msg in compose_emails(
                    professor_ids=professor_ids,
                    replace_existing=req.replace_existing,
                    run_deep_research=req.run_deep_research,
                ):
                    await publish(msg)
        except Exception as e:
            logger.exception("邮件生成任务异常")
            _compose_state["failed"] += 1
            await manager.broadcast({"channel": "compose", "type": "error", "message": str(e)})
        finally:
            _compose_state["running"] = False

    _compose_task = asyncio.create_task(_run())
    return {"message": "邮件生成已启动，请通过 WebSocket 查看进度", **_compose_status()}


# ── 邮件发送 ──────────────────────────────────────────

class SendRequest(BaseModel):
    include_cc: bool = False


@router.post("/send/{draft_id}")
async def send_single(draft_id: int, req: Optional[SendRequest] = None):
    result = await send_email(draft_id, include_cc=req.include_cc if req else False)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


class BatchSendRequest(BaseModel):
    draft_ids: list[int]
    include_cc: bool = False


@router.post("/send/batch")
async def send_batch_endpoint(req: BatchSendRequest):
    results = await send_batch(req.draft_ids, include_cc=req.include_cc)
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


class ProfileGenerateRequest(BaseModel):
    pitch: Optional[str] = None  # 用户补充说明（PhD 方向、负面清单、地区等）


@router.post("/config/profile/generate")
async def generate_profile_from_cv(req: ProfileGenerateRequest):
    """从已上传的 CV（优先个人简历.pdf）+ 用户补充说明，AI 生成 profile.md 草稿。
    不直接覆盖 my_profile.md，只返回生成的文本供前端预览编辑后再保存。"""
    from backend.core.llm import get_llm, load_profile
    from backend.core.prompts import load_prompt
    from langchain_core.messages import HumanMessage, SystemMessage

    migrate_legacy_attachments()
    cv_path = get_attachment_path("cv", "cn") or get_attachment_path("cv", "en")
    if cv_path is None:
        raise HTTPException(status_code=400, detail="请先上传 CV（中文或英文），AI 才能基于 CV 生成 Profile")

    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=500, detail="后端缺少 pdfplumber 依赖，请运行 pip install pdfplumber")

    try:
        with pdfplumber.open(cv_path) as pdf:
            pages_text = [(p.extract_text() or "") for p in pdf.pages]
        cv_text = "\n\n".join(pages_text).strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法读取 CV PDF（可能文件损坏）: {e}")
    if not cv_text:
        raise HTTPException(status_code=400, detail="CV 提取出的文本为空，无法生成（PDF 可能是扫描件）")

    current_profile = load_profile().strip()
    if current_profile.startswith("# 个人简介\n\n请在此填写"):
        current_profile = ""
    current_profile_section = current_profile or "（当前没有已保存 Profile，或 Profile 为空）"
    pitch_section = (req.pitch or "").strip() or "（用户未提供额外说明，请仅从 CV 推断）"

    try:
        llm = get_llm()
        resp = await llm.ainvoke([
            SystemMessage(content=load_prompt("profile_generator")),
            HumanMessage(content=f"【CV 原文】\n{cv_text}\n\n【当前已保存 Profile】\n{current_profile_section}\n\n【用户补充说明】\n{pitch_section}"),
        ], **agent_invoke_options(llm, "profile"))
        content = (resp.content or "").strip()
    except Exception as e:
        logger.exception("Profile 生成失败")
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    # 去掉万一外层的 ```markdown 包裹
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0].rstrip()

    return {"content": content, "cv_source": cv_path.name, "cv_chars": len(cv_text)}


@router.get("/config/settings")
async def get_settings():
    from backend.core.llm import (
        load_yaml_config,
        resolve_agent_backend,
        resolve_model_provider,
    )
    cfg = load_yaml_config()
    # 隐藏敏感信息
    llm_cfg = cfg.get("llm", {})
    def _llm_sub(name: str, default_base: str = "") -> dict:
        sub = llm_cfg.get(name, {}) or {}
        return {
            "model": sub.get("model", ""),
            "base_url": sub.get("base_url", default_base),
            "api_key_set": bool(sub.get("api_key", "")),
        }
    codex_status, pi_status = await asyncio.gather(
        get_codex_worker_status(),
        get_pi_worker_status(),
    )
    agent_backend = resolve_agent_backend(llm_cfg)
    model_provider = resolve_model_provider(llm_cfg)
    search_cfg = cfg.get("search", {}) or {}
    safe_cfg = {
        "llm": {
            "agent_backend": agent_backend,
            "provider": model_provider,
            "codex": {
                "model": (llm_cfg.get("codex", {}) or {}).get("model", ""),
                "timeout_seconds": (
                    llm_cfg.get("codex", {}) or {}
                ).get("timeout_seconds", 600),
                "available": bool(codex_status.get("available")),
            },
            "pi": {
                "timeout_seconds": (
                    llm_cfg.get("pi", {}) or {}
                ).get("timeout_seconds", 600),
                "available": bool(pi_status.get("available")),
                "version": pi_status.get("version", ""),
            },
            "openai": _llm_sub("openai", "https://api.openai.com/v1"),
            "deepseek": _llm_sub("deepseek", "https://api.deepseek.com/v1"),
            "ollama": {
                "model": (llm_cfg.get("ollama", {}) or {}).get("model", ""),
                "base_url": (llm_cfg.get("ollama", {}) or {}).get("base_url", "http://localhost:11434"),
            },
        },
        "search": {
            "agent_backend": agent_backend,
            "keywords": search_cfg.get("keywords", []),
            "regions": search_cfg.get("regions", []),
            "max_professors": search_cfg.get("max_professors", 20),
            "codex": codex_status,
            "pi": pi_status,
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


@router.get("/codex/status")
async def codex_status():
    """Check the host-side Codex worker without exposing auth or config."""
    return await get_codex_worker_status()


@router.get("/pi/status")
async def pi_status():
    """Check the Pi SDK worker without exposing model credentials."""
    return await get_pi_worker_status()


# ── Prompt 模板编辑（backend/prompts/*.md）──────────


@router.get("/config/prompt-templates")
async def list_prompt_templates():
    """列出所有 prompt 模板（含描述和当前内容）"""
    from backend.core.prompts import list_prompts, load_prompt
    items = []
    for p in list_prompts():
        try:
            content = load_prompt(p["name"])
        except FileNotFoundError:
            content = ""
        items.append({**p, "content": content})
    return items


class PromptTemplateUpdate(BaseModel):
    content: str


@router.put("/config/prompt-templates/{name}")
async def update_prompt_template(name: str, body: PromptTemplateUpdate):
    """覆盖写入指定 prompt 模板"""
    from backend.core.prompts import save_prompt
    try:
        save_prompt(name, body.content)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"未知模板: {name}")
    return {"message": f"模板 {name} 已更新"}


# ── LLM 后端配置 ──────────────────────────────────


class LlmProviderSub(BaseModel):
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # 空字符串表示"不修改"，避免前端没回显时误清空
    timeout_seconds: Optional[int] = None


class LlmConfigUpdate(BaseModel):
    agent_backend: Optional[str] = None
    provider: str
    codex: Optional[LlmProviderSub] = None
    pi: Optional[LlmProviderSub] = None
    openai: Optional[LlmProviderSub] = None
    deepseek: Optional[LlmProviderSub] = None
    ollama: Optional[LlmProviderSub] = None


@router.put("/config/llm")
async def update_llm_config(data: LlmConfigUpdate):
    """Update the harness backend independently from the model API."""
    legacy_codex = data.provider == "codex"
    if data.provider not in ("codex", "openai", "deepseek", "ollama"):
        raise HTTPException(
            status_code=400,
            detail="provider 必须是 openai/deepseek/ollama",
        )

    from backend.core.llm import (
        CONFIG_PATH,
        load_yaml_config,
        resolve_model_provider,
    )
    cfg = load_yaml_config()
    if "llm" not in cfg:
        cfg["llm"] = {}
    agent_backend = data.agent_backend or ("codex" if legacy_codex else "direct")
    if agent_backend not in ("direct", "codex", "pi"):
        raise HTTPException(
            status_code=400,
            detail="agent_backend 必须是 direct/codex/pi",
        )
    model_provider = (
        resolve_model_provider(cfg["llm"])
        if legacy_codex
        else data.provider
    )
    cfg["llm"]["agent_backend"] = agent_backend
    cfg["llm"]["provider"] = model_provider

    for name in ("codex", "pi", "openai", "deepseek", "ollama"):
        sub: Optional[LlmProviderSub] = getattr(data, name)
        if sub is None:
            continue
        existing = cfg["llm"].get(name, {}) or {}
        if sub.model is not None:
            existing["model"] = sub.model
        if sub.base_url is not None:
            existing["base_url"] = sub.base_url
        if sub.timeout_seconds is not None:
            existing["timeout_seconds"] = max(
                30,
                min(1800, sub.timeout_seconds),
            )
        # api_key: 空字符串视为不修改（避免前端表单提交时清空已保存的 key）
        if sub.api_key:
            existing["api_key"] = sub.api_key
        cfg["llm"][name] = existing

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {
        "message": "LLM 配置已更新",
        "agent_backend": agent_backend,
        "provider": model_provider,
    }


# ── 简历管理 ──────────────────────────────────────


def _file_status(path: Path | None, display_path: Path) -> dict:
    return {
        "uploaded": bool(path and path.exists()),
        "size": path.stat().st_size if path and path.exists() else 0,
        "name": path.name if path and path.exists() else display_path.name,
    }


@router.get("/config/cv")
async def get_cv_status():
    """获取所有附件状态：简历 + 成绩单（中/英）+ 论文列表"""
    migrate_legacy_attachments()
    papers = []
    if PAPERS_DIR.exists():
        for p in sorted(PAPERS_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() == ".pdf":
                papers.append({"name": p.name, "size": p.stat().st_size})
    return {
        "cv": {
            "cn": _file_status(get_attachment_path("cv", "cn"), attachment_path("cv", "cn")),
            "en": _file_status(get_attachment_path("cv", "en"), attachment_path("cv", "en")),
        },
        "transcript": {
            "cn": _file_status(get_attachment_path("transcript", "cn"), attachment_path("transcript", "cn")),
            "en": _file_status(get_attachment_path("transcript", "en"), attachment_path("transcript", "en")),
        },
        "papers": papers,
    }


@router.post("/config/cv/{lang}")
async def upload_cv(lang: str, file: UploadFile = File(...)):
    """上传简历 (lang: cn 或 en)"""
    if lang not in ("cn", "en"):
        raise HTTPException(status_code=400, detail="lang 必须为 cn 或 en")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 格式")

    target = attachment_path("cv", lang)
    content = await file.read()
    target.write_bytes(content)
    remove_legacy_attachment("cv", lang)
    return {"message": f"{'中文' if lang == 'cn' else '英文'}简历已上传", "size": len(content)}


@router.post("/config/transcript/{lang}")
async def upload_transcript(lang: str, file: UploadFile = File(...)):
    """上传成绩单 (lang: cn 或 en)"""
    if lang not in ("cn", "en"):
        raise HTTPException(status_code=400, detail="lang 必须为 cn 或 en")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 格式")
    target = attachment_path("transcript", lang)
    content = await file.read()
    target.write_bytes(content)
    remove_legacy_attachment("transcript", lang)
    return {"message": f"{'中文' if lang == 'cn' else '英文'}成绩单已上传", "size": len(content)}


def _safe_paper_name(filename: str) -> str:
    """从用户上传的 filename 提取安全的文件名（防止路径穿越）"""
    name = Path(filename).name  # 去掉任何路径
    if not name or not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="文件名非法或非 PDF")
    return name


@router.post("/config/papers")
async def upload_paper(file: UploadFile = File(...)):
    """上传一篇论文到 papers/（按原文件名保存；同名覆盖）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    name = _safe_paper_name(file.filename)
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    target = PAPERS_DIR / name
    content = await file.read()
    target.write_bytes(content)
    return {"message": f"论文 {name} 已上传", "name": name, "size": len(content)}


@router.delete("/config/papers/{name}")
async def delete_paper(name: str):
    """删除 papers/ 下一篇论文"""
    safe = _safe_paper_name(name)
    target = PAPERS_DIR / safe
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"message": f"论文 {safe} 已删除"}


# ── 自定义 Prompt 管理 ─────────────────────────────

DEFAULT_PRPiTS = {
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
    result = {**DEFAULT_PRPiTS, **saved}
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
    return {"message": "自定义 Prompt 已更新", **{**DEFAULT_PRPiTS, **cfg["prompts"]}}


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
    return {
        "message": "搜索配置已更新",
        "keywords": data.keywords,
        "regions": cfg["search"].get("regions", []),
    }


# ── 邮箱验证 ──────────────────────────────────────

class EmailConfig(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool = True
    smtp_from_name: str = ""
    smtp_cc: str = ""
    smtp_proxy_enabled: bool = False
    smtp_proxy_host: str = "host.docker.internal"
    smtp_proxy_port: int = 10809
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    imap_use_ssl: bool = True
    imap_proxy_enabled: bool = False
    imap_proxy_host: str = "host.docker.internal"
    imap_proxy_port: int = 10809
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
            "from_name": smtp.get("from_name", ""),
            "cc": smtp.get("cc", ""),
            "proxy_enabled": smtp.get("proxy_enabled", False),
            "proxy_host": smtp.get("proxy_host", "host.docker.internal"),
            "proxy_port": smtp.get("proxy_port", 10809),
        },
        "imap": {
            "host": imap.get("host", ""),
            "port": imap.get("port", 993),
            "username": imap.get("username", ""),
            "password_set": bool(imap.get("password", "")),
            "use_ssl": imap.get("use_ssl", True),
            "proxy_enabled": imap.get("proxy_enabled", smtp.get("proxy_enabled", False)),
            "proxy_host": imap.get("proxy_host", smtp.get("proxy_host", "host.docker.internal")),
            "proxy_port": imap.get("proxy_port", smtp.get("proxy_port", 10809)),
        },
    }


@router.post("/config/email/verify")
async def verify_email(data: EmailConfig):
    """验证 SMTP 和 IMAP 连接"""
    from backend.services.imap_client import create_imap_client
    from backend.services.smtp_client import create_smtp_client

    results = {"smtp": {"ok": False, "message": ""}, "imap": {"ok": False, "message": ""}}

    from backend.core.llm import load_yaml_config
    current_cfg = load_yaml_config()
    current_smtp = current_cfg.get("smtp", {})
    current_imap = current_cfg.get("imap", {})
    smtp_password = data.smtp_password or (
        current_smtp.get("password", "")
        if data.smtp_username == current_smtp.get("username") else ""
    )
    imap_password = data.imap_password or (
        current_imap.get("password", "")
        if data.imap_username == current_imap.get("username") else ""
    )

    # 验证 SMTP
    try:
        smtp_config = {
            "host": data.smtp_host,
            "port": data.smtp_port,
            "use_tls": data.smtp_use_tls,
            "proxy_enabled": data.smtp_proxy_enabled,
            "proxy_host": data.smtp_proxy_host,
            "proxy_port": data.smtp_proxy_port,
        }

        def verify_smtp_connection() -> None:
            server = create_smtp_client(smtp_config, timeout=10)
            try:
                server.login(data.smtp_username, smtp_password)
            finally:
                try:
                    server.quit()
                except Exception:
                    server.close()

        await asyncio.to_thread(verify_smtp_connection)
        results["smtp"] = {"ok": True, "message": "SMTP 连接成功"}
    except Exception as e:
        results["smtp"] = {"ok": False, "message": f"SMTP 失败: {e}"}

    # IMAP 是可选能力；未配置时不阻止 SMTP 设置保存。
    if not data.imap_host.strip() or not data.imap_username.strip():
        results["imap"] = {"ok": True, "message": "IMAP 未配置，已跳过回复跟踪验证"}
    else:
        try:
            def verify_imap_connection() -> None:
                mail = create_imap_client({
                    "host": data.imap_host,
                    "port": data.imap_port,
                    "use_ssl": data.imap_use_ssl,
                    "proxy_enabled": data.imap_proxy_enabled,
                    "proxy_host": data.imap_proxy_host,
                    "proxy_port": data.imap_proxy_port,
                }, timeout=10)
                try:
                    mail.login(data.imap_username, imap_password)
                finally:
                    try:
                        mail.logout()
                    except Exception:
                        mail.shutdown()

            await asyncio.to_thread(verify_imap_connection)
            results["imap"] = {"ok": True, "message": "IMAP 连接成功"}
        except Exception as e:
            results["imap"] = {"ok": False, "message": f"IMAP 失败: {e}"}

    # 如果验证通过且要求保存
    if data.save and results["smtp"]["ok"] and results["imap"]["ok"]:
        from backend.core.llm import CONFIG_PATH, load_yaml_config
        cfg = load_yaml_config()
        cfg["smtp"] = {
            "host": data.smtp_host, "port": data.smtp_port,
            "username": data.smtp_username, "password": smtp_password,
            "use_tls": data.smtp_use_tls,
            "from_name": data.smtp_from_name.strip(),
            "cc": data.smtp_cc.strip(),
            "proxy_enabled": data.smtp_proxy_enabled,
            "proxy_host": data.smtp_proxy_host.strip(),
            "proxy_port": data.smtp_proxy_port,
        }
        cfg["imap"] = {
            "host": data.imap_host, "port": data.imap_port,
            "username": data.imap_username, "password": imap_password,
            "use_ssl": data.imap_use_ssl,
            "proxy_enabled": data.imap_proxy_enabled,
            "proxy_host": data.imap_proxy_host.strip(),
            "proxy_port": data.imap_proxy_port,
            "poll_interval": current_imap.get("poll_interval", 300),
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
