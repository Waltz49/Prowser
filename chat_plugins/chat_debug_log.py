#!/usr/bin/env python3
"""Debug-mode chat LLM request/response logging to Tools > Debug > View log."""

from __future__ import annotations

import json

from config import get_config
from debug_log import debug_timestamp
from print_call_decorator import relax_json_for_log

_LOG_TAG = "chat_plugins.chat_lmstudio"


def _debug_enabled() -> bool:
    return bool(get_config().load_settings().get("debug_mode", False))


def _write_json_log(kind: str, payload: dict) -> None:
    body = relax_json_for_log(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    print(f"{debug_timestamp()} {_LOG_TAG} {kind}\n{body}\n", flush=True)


def log_chat_llm_input(
    messages: list[dict],
    *,
    system_prompt: str,
    temperature: float,
) -> None:
    if not _debug_enabled():
        return
    _write_json_log(
        "input",
        {
            "system_prompt": system_prompt,
            "messages": messages,
            "config": {"temperature": temperature},
        },
    )


def log_chat_llm_output(text: str) -> None:
    if not _debug_enabled():
        return
    _write_json_log("output", {"text": text})
