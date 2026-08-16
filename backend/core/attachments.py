"""Attachment file naming helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

AttachmentKind = Literal["cv", "transcript"]
AttachmentLang = Literal["cn", "en"]

CONFIG_DIR = Path(__file__).parent.parent / "config"
PAPERS_DIR = CONFIG_DIR / "papers"

ATTACHMENT_FILENAMES: dict[tuple[AttachmentKind, AttachmentLang], str] = {
    ("cv", "cn"): "个人简历.pdf",
    ("cv", "en"): "CV.pdf",
    ("transcript", "cn"): "成绩单.pdf",
    ("transcript", "en"): "Transcript.pdf",
}

LEGACY_ATTACHMENT_FILENAMES: dict[tuple[AttachmentKind, AttachmentLang], str] = {
    (kind, lang): f"{kind}_{lang}.pdf"
    for kind in ("cv", "transcript")
    for lang in ("cn", "en")
}


def attachment_path(kind: AttachmentKind, lang: AttachmentLang) -> Path:
    return CONFIG_DIR / ATTACHMENT_FILENAMES[(kind, lang)]


def legacy_attachment_path(kind: AttachmentKind, lang: AttachmentLang) -> Path:
    return CONFIG_DIR / LEGACY_ATTACHMENT_FILENAMES[(kind, lang)]


def get_attachment_path(kind: AttachmentKind, lang: AttachmentLang, *, include_legacy: bool = True) -> Path | None:
    path = attachment_path(kind, lang)
    if path.exists():
        return path
    if include_legacy:
        legacy = legacy_attachment_path(kind, lang)
        if legacy.exists():
            return legacy
    return None


def migrate_legacy_attachments() -> list[tuple[str, str]]:
    """Rename old attachment filenames to user-facing filenames when possible."""
    renamed: list[tuple[str, str]] = []
    for kind, lang in ATTACHMENT_FILENAMES:
        legacy = legacy_attachment_path(kind, lang)
        target = attachment_path(kind, lang)
        if legacy.exists() and not target.exists():
            legacy.rename(target)
            renamed.append((legacy.name, target.name))
    return renamed


def remove_legacy_attachment(kind: AttachmentKind, lang: AttachmentLang) -> None:
    legacy = legacy_attachment_path(kind, lang)
    target = attachment_path(kind, lang)
    if legacy.exists() and legacy != target:
        legacy.unlink()
