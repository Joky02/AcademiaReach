"""LLM interface with independent agent-harness and model-API selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama
from langchain_core.language_models import BaseChatModel
from backend.core.codex_llm import CodexChatModel
from backend.core.pi_llm import PiChatModel

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


def load_yaml_config() -> dict:
    """加载 config.yaml 原始配置"""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


AGENT_BACKENDS = {"direct", "codex", "pi"}
MODEL_PROVIDERS = {"openai", "deepseek", "ollama"}


def resolve_agent_backend(llm_cfg: dict) -> str:
    """Resolve new config while preserving legacy `provider: codex` installs."""
    configured = str(llm_cfg.get("agent_backend") or "").strip().lower()
    if configured in AGENT_BACKENDS:
        return configured
    return "codex" if llm_cfg.get("provider") == "codex" else "direct"


def resolve_model_provider(llm_cfg: dict) -> str:
    provider = str(llm_cfg.get("provider") or "openai").strip().lower()
    if provider == "codex":
        provider = str(llm_cfg.get("api_provider") or "openai").strip().lower()
    return provider if provider in MODEL_PROVIDERS else "openai"


def get_model_api_config(
    cfg: dict | None = None,
    provider: str | None = None,
) -> dict:
    cfg = cfg or load_yaml_config()
    llm_cfg = cfg.get("llm", {}) or {}
    provider = provider or resolve_model_provider(llm_cfg)
    sub = llm_cfg.get(provider, {}) or {}
    defaults = {
        "openai": ("gpt-4o", "https://api.openai.com/v1"),
        "deepseek": ("deepseek-chat", "https://api.deepseek.com/v1"),
        "ollama": ("llama3", "http://localhost:11434"),
    }
    default_model, default_base = defaults[provider]
    return {
        "provider": provider,
        "model": str(sub.get("model") or default_model),
        "base_url": str(sub.get("base_url") or default_base),
        "api_key": str(sub.get("api_key") or ""),
        "context_window": int(sub.get("context_window") or 128000),
        "max_tokens": int(sub.get("max_tokens") or 16384),
    }


def get_llm(provider: Optional[str] = None) -> BaseChatModel:
    """Return the selected API directly or through a named harness backend."""
    cfg = load_yaml_config()
    llm_cfg = cfg.get("llm", {})
    backend = resolve_agent_backend(llm_cfg)
    provider = provider or resolve_model_provider(llm_cfg)

    if backend == "codex":
        sub = llm_cfg.get("codex", {}) or {}
        return CodexChatModel(
            model_name=str(sub.get("model", "") or ""),
            timeout_seconds=max(
                30,
                min(1800, int(sub.get("timeout_seconds", 600))),
            ),
        )
    if backend == "pi":
        sub = llm_cfg.get("pi", {}) or {}
        model_cfg = get_model_api_config(cfg, provider)
        return PiChatModel(
            provider_name=model_cfg["provider"],
            model_name=model_cfg["model"],
            base_url=model_cfg["base_url"],
            api_key=model_cfg["api_key"],
            timeout_seconds=max(
                30,
                min(1800, int(sub.get("timeout_seconds", 600))),
            ),
            context_window=model_cfg["context_window"],
            max_tokens=model_cfg["max_tokens"],
        )
    if provider == "openai":
        sub = llm_cfg.get("openai", {})
        return ChatOpenAI(
            model=sub.get("model", "gpt-4o"),
            api_key=sub.get("api_key", ""),
            base_url=sub.get("base_url", "https://api.openai.com/v1"),
            temperature=0.7,
            request_timeout=300,
        )
    elif provider == "deepseek":
        sub = llm_cfg.get("deepseek", {})
        return ChatOpenAI(
            model=sub.get("model", "deepseek-chat"),
            api_key=sub.get("api_key", ""),
            base_url=sub.get("base_url", "https://api.deepseek.com/v1"),
            temperature=0.7,
            request_timeout=300,
        )
    elif provider == "ollama":
        sub = llm_cfg.get("ollama", {})
        return ChatOllama(
            model=sub.get("model", "llama3"),
            base_url=sub.get("base_url", "http://localhost:11434"),
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def load_profile() -> str:
    """读取用户 Profile 文件内容"""
    profile_path = Path(__file__).parent.parent / "config" / "my_profile.md"
    if profile_path.exists():
        return profile_path.read_text(encoding="utf-8")
    return ""
