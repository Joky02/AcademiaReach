"""LLM 统一接口 — 支持 OpenAI / DeepSeek / Ollama 多后端切换"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama
from langchain_core.language_models import BaseChatModel

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"


def load_yaml_config() -> dict:
    """加载 config.yaml 原始配置"""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_llm(provider: Optional[str] = None) -> BaseChatModel:
    """根据 provider 返回对应 LLM 实例"""
    cfg = load_yaml_config()
    llm_cfg = cfg.get("llm", {})
    provider = provider or llm_cfg.get("provider", "openai")

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
