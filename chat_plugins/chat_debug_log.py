#!/usr/bin/env python3
"""Debug-mode chat LLM request/response logging to Tools > Debug > View log."""

from __future__ import annotations

from model_debug_log import log_model_input, log_model_output

_LOG_TAG = "chat_plugins.chat_lmstudio"


def log_chat_llm_input(
    messages: list[dict],
    *,
    system_prompt: str,
    temperature: float,
) -> None:
    log_model_input(
        _LOG_TAG,
        {
            "system_prompt": system_prompt,
            "messages": messages,
            "config": {"temperature": temperature},
        },
    )


def log_chat_llm_output(text: str) -> None:
    log_model_output(_LOG_TAG, text)
