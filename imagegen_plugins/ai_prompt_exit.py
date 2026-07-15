#!/usr/bin/env python3
"""Undocumented env-configured hooks to transform prompts before AI model calls."""

from __future__ import annotations

import os
import subprocess
import sys

from config import get_config

ENV_TEXT_AI_EXIT = "PROWSER_TEXT_AI_EXIT"
ENV_IMAGE_AI_EXIT = "PROWSER_IMAGE_AI_EXIT"

_EXIT_TIMEOUT_SEC = 30
_AI_EXIT_ENV_VARS = (ENV_TEXT_AI_EXIT, ENV_IMAGE_AI_EXIT)
_ANSI_RESET = "\033[0m"
_ANSI_ORANGE = "\033[38;5;208m"


def _stdout_supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "")
    return bool(term) and term.lower() != "dumb"


def _status_suffix(label: str) -> str:
    if _stdout_supports_color():
        return f"[{_ANSI_ORANGE}{label}{_ANSI_RESET}]"
    return f"[{label}]"


def apply_text_ai_exit(text: str) -> str:
    """Run PROWSER_TEXT_AI_EXIT on text before LMStudio calls."""
    return _invoke_exit_for_env(text, ENV_TEXT_AI_EXIT)


def apply_image_ai_exit(text: str) -> str:
    """Run PROWSER_IMAGE_AI_EXIT on text before image model calls."""
    from chat_plugins.chat_prefix_postfix import apply_prefix_postfix_rules

    with_rules = apply_prefix_postfix_rules(text, for_images=True)
    return _invoke_exit_for_env(with_rules, ENV_IMAGE_AI_EXIT)


def apply_image_ai_exit_to_payload(payload: dict) -> None:
    """Apply image exit to the final worker generate prompt in place."""
    raw = str(payload.get("prompt") or "")
    if raw:
        payload["prompt"] = apply_image_ai_exit(raw)


def describe_ai_exit_env(env_var: str) -> str:
    """One-line status for an exit env var (for ``main.py --env``)."""
    raw = os.environ.get(env_var)
    if raw is None or not str(raw).strip():
        return f"{env_var}: No environment variable"
    display = str(raw).strip()
    path = os.path.expanduser(display)
    if not os.path.exists(path):
        return f"{env_var}: {display} {_status_suffix('Not Found')}"
    if not os.path.isfile(path):
        return f"{env_var}: {display} {_status_suffix('Not file')}"
    issues = _exit_path_issues(path)
    if issues:
        return f"{env_var}: {display} {_status_suffix('Exists; ' + '; '.join(issues))}"
    return f"{env_var}: {display} {_status_suffix('Exists')}"


def print_ai_exit_env_report() -> None:
    """Print exit-hook env diagnostics to stdout."""
    for env_var in _AI_EXIT_ENV_VARS:
        print(describe_ai_exit_env(env_var))


def _exit_path_issues(path: str) -> list[str]:
    issues: list[str] = []
    if not os.access(path, os.R_OK):
        issues.append("not readable")
    if path.endswith(".py"):
        if not os.access(path, os.X_OK):
            issues.append("not executable (will run with python)")
    elif not os.access(path, os.X_OK):
        issues.append("not executable")
    return issues


def _exit_path_usable(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    if not os.access(path, os.R_OK):
        return False
    if path.endswith(".py"):
        return True
    return os.access(path, os.X_OK)


def _resolve_exit_script(env_var: str) -> str:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return ""
    path = os.path.expanduser(raw)
    if not _exit_path_usable(path):
        return ""
    return path


def _prompt_filter_exits_enabled() -> bool:
    return bool(get_config().load_settings().get("use_prompt_filter_exits", False))


def _invoke_exit_for_env(text: str, env_var: str) -> str:
    if not _prompt_filter_exits_enabled():
        return text
    path = _resolve_exit_script(env_var)
    if not path:
        return text
    return _invoke_exit_script(path, text)


def _invoke_exit_script(path: str, text: str) -> str:
    argv = [path, "-p", text]
    if path.endswith(".py") and not os.access(path, os.X_OK):
        argv = [sys.executable, path, "-p", text]

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
