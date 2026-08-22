#!/usr/bin/env python3
"""Settings-backed hook for text-to-speech (speak buttons)."""

from __future__ import annotations

import os

from exit_scripts import (
    SETTING_SAY_EXIT,
    get_exit_script_setting,
    resolve_exit_script_argv,
)

ENV_SAY_VOICE = "PROWSER_SAY_VOICE"


def parse_say_exit_command() -> list[str]:
    """Return configured say-exit argv (command minus ``-p`` prompt)."""
    return list(resolve_exit_script_argv(get_exit_script_setting(SETTING_SAY_EXIT)))


def resolve_say_exit_command() -> list[str]:
    """Return configured command argv, or empty when missing/invalid."""
    return parse_say_exit_command()


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

