#!/usr/bin/env python3
"""Undocumented env-configured hook for text-to-speech (speak buttons)."""

from __future__ import annotations

import os
import shlex
import shutil
import sys

ENV_SAY_EXIT = "PROWSER_SAY_EXIT"
ENV_SAY_VOICE = "PROWSER_SAY_VOICE"

_PYTHON_INTERPRETERS = frozenset({"python", "python3", "pypy3"})

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


def parse_say_exit_command() -> list[str]:
    """Split PROWSER_SAY_EXIT into argv (command minus ``-p`` prompt)."""
    raw = os.environ.get(ENV_SAY_EXIT, "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return []


def _script_path_issues(path: str) -> list[str]:
    issues: list[str] = []
    if not os.access(path, os.R_OK):
        issues.append("not readable")
    if path.endswith(".py"):
        if not os.access(path, os.X_OK):
            issues.append("not executable (run via python in command)")
    elif not os.access(path, os.X_OK):
        issues.append("not executable")
    return issues


def _script_path_usable(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    if not os.access(path, os.R_OK):
        return False
    if path.endswith(".py"):
        return True
    return os.access(path, os.X_OK)


def _command_target(argv: list[str]) -> tuple[str, str]:
    """Return (kind, path_or_name) where kind is ``script`` or ``command``."""
    if not argv:
        return ("", "")
    first = os.path.basename(argv[0]).lower()
    if first in _PYTHON_INTERPRETERS:
        if len(argv) < 2:
            return ("", "")
        return ("script", os.path.expanduser(argv[1]))
    expanded = os.path.expanduser(argv[0])
    if os.path.isfile(expanded):
        return ("script", expanded)
    return ("command", argv[0])


def resolve_say_exit_command() -> list[str]:
    """Return configured command argv, or empty when missing/invalid."""
    argv = parse_say_exit_command()
    if not argv:
        return []
    kind, target = _command_target(argv)
    if kind == "script":
        if _script_path_usable(target):
            return argv
        return []
    if kind == "command" and shutil.which(target):
        return argv
    return []


def resolve_say_exit_script() -> str:
    """Backward-compatible: return script path when target is a file, else ``\"\"``."""
    argv = resolve_say_exit_command()
    if not argv:
        return ""
    kind, target = _command_target(argv)
    if kind == "script":
        return target
    return ""


def say_exit_argv(text: str) -> list[str]:
    """Build argv for the configured say-exit command."""
    argv = list(resolve_say_exit_command())
    if not argv:
        return []
    voice = os.environ.get(ENV_SAY_VOICE, "").strip()
    if voice and "-v" not in argv and "--voice" not in argv:
        argv.extend(["-v", voice])
    argv.extend(["-p", text])
    return argv


def describe_say_exit_env() -> str:
    """One-line status for PROWSER_SAY_EXIT (for ``main.py --env``)."""
    raw = os.environ.get(ENV_SAY_EXIT)
    if raw is None or not str(raw).strip():
        return f"{ENV_SAY_EXIT}: No environment variable"
    display = str(raw).strip()
    argv = parse_say_exit_command()
    if not argv:
        return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Invalid')}"

    first = os.path.basename(argv[0]).lower()
    if first in _PYTHON_INTERPRETERS:
        if len(argv) < 2:
            return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Missing script')}"
        script = os.path.expanduser(argv[1])
        if not os.path.isfile(script):
            return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Script not found')}"
        issues = _script_path_issues(script)
        if issues:
            return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Exists; ' + '; '.join(issues))}"
    else:
        script = os.path.expanduser(argv[0])
        if os.path.isfile(script):
            issues = _script_path_issues(script)
            if issues:
                return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Exists; ' + '; '.join(issues))}"
        elif not shutil.which(argv[0]):
            return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Not Found')}"

    voice = os.environ.get(ENV_SAY_VOICE, "").strip()
    if voice:
        return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Exists')} voice={voice}"
    return f"{ENV_SAY_EXIT}: {display} {_status_suffix('Exists')}"


def print_say_exit_env_report() -> None:
    """Print speech exit env diagnostics to stdout."""
    print(describe_say_exit_env())
