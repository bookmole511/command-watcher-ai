"""LLM factory helpers."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from langchain_ollama import ChatOllama

from src.config import (
    LLM_MODEL,
    LLM_NUM_CTX,
    LLM_NUM_PREDICT,
    LLM_NUM_THREAD,
    LLM_TEMPERATURE,
)


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def get_ollama_base_url() -> str:
    """Return a client-safe Ollama base URL.

    OLLAMA_HOST is often set to 0.0.0.0:11434 when starting the Ollama
    server. That is a bind address, not a valid Windows client destination.
    """

    raw_url = (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_CLIENT_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or DEFAULT_OLLAMA_BASE_URL
    ).strip()

    if not raw_url:
        return DEFAULT_OLLAMA_BASE_URL

    if "://" not in raw_url:
        raw_url = f"http://{raw_url}"

    parsed = urlparse(raw_url)
    if parsed.hostname in {"0.0.0.0", "::", "[::]"}:
        netloc = "127.0.0.1"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()

    return raw_url


def create_chat_ollama(**kwargs) -> ChatOllama:
    kwargs.setdefault("model", LLM_MODEL)
    kwargs.setdefault("temperature", LLM_TEMPERATURE)
    kwargs.setdefault("num_ctx", LLM_NUM_CTX)
    kwargs.setdefault("num_thread", LLM_NUM_THREAD)
    kwargs.setdefault("num_predict", LLM_NUM_PREDICT)
    kwargs.setdefault("base_url", get_ollama_base_url())
    kwargs.setdefault("reasoning", False)
    return ChatOllama(**kwargs)
