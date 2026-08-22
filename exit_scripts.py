#!/usr/bin/env python3
"""Settings-backed external exit scripts for prompt filters and speech."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from typing import NamedTuple

from config import get_config

# Expand this tuple to allow additional interpreter prefixes at field entry.
EXIT_SCRIPT_PREFIXES: tuple[str, ...] = ("python", "python3", "pypy")

SETTING_TEXT_AI_EXIT = "text_ai_exit"
SETTING_IMAGE_AI_EXIT = "image_ai_exit"
SETTING_SAY_EXIT = "say_exit"

_LEGACY_ENV_BY_SETTING = {
    SETTING_TEXT_AI_EXIT: "PROWSER_TEXT_AI_EXIT",
    SETTING_IMAGE_AI_EXIT: "PROWSER_IMAGE_AI_EXIT",
    SETTING_SAY_EXIT: "PROWSER_SAY_EXIT",
}


class ParsedExitScript(NamedTuple):
    prefix: str
    path: str
    raw: str


def _prefix_token(token: str) -> str | None:
    lowered = token.lower()
    for prefix in sorted(EXIT_SCRIPT_PREFIXES, key=len, reverse=True):
        if lowered == prefix:
            return prefix
    return None


def parse_exit_script_command(raw: str) -> ParsedExitScript:
    """Split a stored command into optional interpreter prefix and script path."""
    text = (raw or "").strip()
    if not text:
        return ParsedExitScript("", "", "")
    try:
        parts = shlex.split(text)
    except ValueError:
        return ParsedExitScript("", "", text)
    if not parts:
        return ParsedExitScript("", "", text)
    matched = _prefix_token(parts[0])
    if matched is not None:
        path = parts[1] if len(parts) > 1 else ""
        return ParsedExitScript(matched, path, text)
    return ParsedExitScript("", parts[0], text)


def format_exit_script_command(prefix: str, path: str) -> str:
    """Build the stored command string from prefix and path."""
    script_path = (path or "").strip()
    if not script_path:
        return ""
    interpreter = (prefix or "").strip()
    if interpreter:
        return f"{interpreter} {script_path}"
    return script_path


def normalize_exit_script_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser((path or "").strip()))


def exit_script_path_issues(path: str) -> list[str]:
    issues: list[str] = []
    if not os.access(path, os.R_OK):
        issues.append("not readable")
    if path.endswith(".py"):
        if not os.access(path, os.X_OK):
            issues.append("not executable (will run with python)")
    elif not os.access(path, os.X_OK):
        issues.append("not executable")
    return issues


def exit_script_path_usable(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    if not os.access(path, os.R_OK):
        return False
    if path.endswith(".py"):
        return True
    return os.access(path, os.X_OK)


def validate_exit_script_command(raw: str) -> tuple[bool, str]:
    """Return (is_valid, tooltip) for UI validation indicators."""
    text = (raw or "").strip()
    if not text:
        return True, ""
    parsed = parse_exit_script_command(text)
    if not parsed.path:
        return False, "Missing script path"
    full_path = normalize_exit_script_path(parsed.path)
    if os.path.isdir(full_path):
        return False, f"Path is a directory, not a file:\n{full_path}"
    if not os.path.isfile(full_path):
        return False, f"File does not exist:\n{full_path}"
    if exit_script_path_usable(full_path):
        issues = exit_script_path_issues(full_path)
        if issues:
            return True, (
                f"Valid script file ({'; '.join(issues)}):\n{full_path}"
            )
        return True, f"Valid script file:\n{full_path}"
    issues = exit_script_path_issues(full_path)
    detail = f" ({'; '.join(issues)})" if issues else ""
    return False, f"File is not usable{detail}:\n{full_path}"


def _shlex_parts(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return []


def resolve_exit_script_argv(raw: str) -> list[str]:
    """Return argv for the configured script (without ``-p`` prompt text)."""
    parts = _shlex_parts(raw)
    if not parts:
        return []

    matched = _prefix_token(parts[0])
    if matched is not None:
        if len(parts) < 2:
            return []
        script_path = normalize_exit_script_path(parts[1])
        if not exit_script_path_usable(script_path):
            return []
        # Use the running app's interpreter for python/python3 so GUI launches
        # do not depend on shell pyenv shims from shutil.which("python").
        if matched in ("python", "python3"):
            interpreter = sys.executable
        else:
            interpreter = shutil.which(matched) or matched
        return [interpreter, script_path, *parts[2:]]

    script_path = normalize_exit_script_path(parts[0])
    if os.path.isfile(script_path):
        if not exit_script_path_usable(script_path):
            return []
        if script_path.endswith(".py") and not os.access(script_path, os.X_OK):
            return [sys.executable, script_path, *parts[1:]]
        return [script_path, *parts[1:]]

    if shutil.which(parts[0]):
        return parts
    return []


def build_exit_script_argv(raw: str, text: str) -> list[str]:
    """Return argv to run the configured script with ``-p`` prompt text."""
    argv = list(resolve_exit_script_argv(raw))
    if not argv:
        return []
    argv.extend(["-p", text])
    return argv


def get_exit_script_setting(key: str) -> str:
    value = str(get_config().load_settings().get(key, "") or "").strip()
    if value:
        return value
    env_key = _LEGACY_ENV_BY_SETTING.get(key)
    if env_key:
        legacy = os.environ.get(env_key, "").strip()
        if legacy:
            return legacy
    return ""


def any_prompt_filter_exit_configured() -> bool:
    """True when a text or image prompt exit script is configured."""
    return bool(
        get_exit_script_setting(SETTING_TEXT_AI_EXIT)
        or get_exit_script_setting(SETTING_IMAGE_AI_EXIT)
    )
