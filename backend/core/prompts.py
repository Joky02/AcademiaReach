"""Prompt 模板加载/保存 — 每次从磁盘读，编辑后无需重启服务"""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
LOCAL_PROMPT_DIR = Path(__file__).parent.parent / "config" / "prompts"

# 模板名 -> 用途说明（前端展示用）
PROMPT_DESCRIPTIONS: dict[str, str] = {
    "compose_cn": "中文套磁邮件正文撰写（system prompt）",
    "compose_en": "English cold-email body composition (system prompt)",
    "research_analyze": "Deep Research：从搜索结果提炼导师论文画像",
    "enrich_professor": "导师信息补全：根据搜索结果填邮箱/主页/标签",
    "search_system": "搜索 Agent 系统 prompt（含 {extra} 占位符注入用户关键词/地区/偏好）",
    "profile_generator": "AI 生成 Profile：从 CV + 用户补充说明生成 my_profile.md",
}


def list_prompts() -> list[dict]:
    """列出所有可用 prompt 模板的元信息"""
    return [
        {"name": name, "description": desc}
        for name, desc in PROMPT_DESCRIPTIONS.items()
    ]


def load_prompt(name: str) -> str:
    """加载 prompt；优先使用本地私有覆盖文件，其次使用仓库 example。"""
    if name not in PROMPT_DESCRIPTIONS:
        raise KeyError(f"Unknown prompt template: {name}")
    local_path = LOCAL_PROMPT_DIR / f"{name}.md"
    path = local_path if local_path.exists() else PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def save_prompt(name: str, content: str) -> None:
    """保存到本地私有覆盖文件，避免把个人 prompt 误提交到 Git。"""
    if name not in PROMPT_DESCRIPTIONS:
        raise KeyError(f"Unknown prompt template: {name}")
    LOCAL_PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_PROMPT_DIR / f"{name}.md"
    path.write_text(content, encoding="utf-8")
