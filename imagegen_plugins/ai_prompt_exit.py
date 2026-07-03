#!/usr/bin/env python3
"""Undocumented env-configured hooks to transform prompts before AI model calls."""

from __future__ import annotations

import os
import subprocess
import sys

ENV_TEXT_AI_EXIT = "PROWSER_TEXT_AI_EXIT"
ENV_IMAGE_AI_EXIT = "PROWSER_IMAGE_AI_EXIT"

_EXIT_TIMEOUT_SEC = 30


def apply_text_ai_exit(text: str) -> str:
    """Run PROWSER_TEXT_AI_EXIT on text before LMStudio calls."""
    return _invoke_exit(ENV_TEXT_AI_EXIT, text)


def apply_image_ai_exit(text: str) -> str:
    """Run PROWSER_IMAGE_AI_EXIT on text before image model calls."""
    return _invoke_exit(ENV_IMAGE_AI_EXIT, text)


def _invoke_exit(env_var: str, text: str) -> str:
    path = os.environ.get(env_var, "").strip()
    if not path:
        return text

    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return text

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
