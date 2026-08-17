#!/usr/bin/env python3
"""Settings-backed hooks to transform prompts before AI model calls."""

from __future__ import annotations

import subprocess

from config import get_config
from exit_scripts import (
    SETTING_IMAGE_AI_EXIT,
    SETTING_TEXT_AI_EXIT,
    build_exit_script_argv,
    get_exit_script_setting,
)

_EXIT_TIMEOUT_SEC = 30


def apply_text_ai_exit(text: str) -> str:
    """Run the configured text AI exit script before LMStudio calls."""
    return _invoke_exit_for_setting(text, SETTING_TEXT_AI_EXIT)


def apply_image_ai_exit(text: str) -> str:
    """Run the configured image AI exit script before image model calls."""
    from chat_plugins.chat_prefix_postfix import apply_prefix_postfix_rules

    with_rules = apply_prefix_postfix_rules(text, for_images=True)
    return _invoke_exit_for_setting(with_rules, SETTING_IMAGE_AI_EXIT)


def apply_image_ai_exit_to_payload(payload: dict) -> None:
    """Apply image exit to the final worker generate prompt in place."""
    raw = str(payload.get("prompt") or "")
    if raw:
        payload["prompt"] = apply_image_ai_exit(raw)


def apply_image_ai_exit_to_prompt_values(values: dict) -> bool:
    """Apply image prompt exit to submit/job values; return True if prompt changed."""
    from imagegen_plugins.flux_prompt_job import has_flux_prompt_ai_job

    if has_flux_prompt_ai_job(values):
        return False
    raw = str(values.get("prompt") or "")
    if not raw:
        return False
    filtered = apply_image_ai_exit(raw)
    if filtered == raw:
        return False
    values["prompt"] = filtered
    return True


def imagegen_values_for_dialog_save(values: dict, panel) -> dict:
    """Persist dialog settings using the user's raw prompt text."""
    out = dict(values)
    getter = getattr(panel, "get_prompt_text", None)
    if getter is not None:
        out["prompt"] = getter()
    return out


def print_ai_exit_env_report() -> None:
    """Print configured text/image exit diagnostics to stdout."""
    from exit_scripts import describe_exit_script_setting

    print()
    print(describe_exit_script_setting(SETTING_TEXT_AI_EXIT))
    print(describe_exit_script_setting(SETTING_IMAGE_AI_EXIT))


def _prompt_filter_exits_enabled() -> bool:
    return bool(get_config().load_settings().get("use_prompt_filter_exits", False))


def _invoke_exit_for_setting(text: str, setting_key: str) -> str:
    if not _prompt_filter_exits_enabled():
        return text
    raw = get_exit_script_setting(setting_key)
    if not raw:
        return text
    return _invoke_exit_script(raw, text)


def _invoke_exit_script(raw: str, text: str) -> str:
    argv = build_exit_script_argv(raw, text)
    if not argv:
        return text

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_EXIT_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired):
        return text

    if result.returncode != 0:
        return text

    return result.stdout.rstrip("\n")
