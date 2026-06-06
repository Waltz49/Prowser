#!/usr/bin/env python3
"""How to spawn the unified model-tasks worker (dev vs PyInstaller bundle)."""

from __future__ import annotations

import os
import sys

MODEL_TASKS_WORKER_FLAG = "--model-tasks-worker"
BACKGROUND_ARG = "--background"

_BACKGROUND_MODE = "default"


def set_background_mode(mode: str) -> None:
    """Override thread vs process for model-tasks worker (testing)."""
    global _BACKGROUND_MODE
    if mode not in ("default", "thread", "process"):
        raise ValueError(f"invalid background mode: {mode!r}")
    _BACKGROUND_MODE = mode


def _omit_testing_argv_flags(argv: list[str]) -> list[str]:
    """Drop main-app-only flags that must not be forwarded to worker subprocesses."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == BACKGROUND_ARG:
            i += 2 if i + 1 < len(argv) else 1
            continue
        if arg.startswith(f"{BACKGROUND_ARG}="):
            i += 1
            continue
        out.append(arg)
        i += 1
    return out


def model_tasks_worker_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_tasks_worker.py")


def model_tasks_worker_program_and_args() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        args = [MODEL_TASKS_WORKER_FLAG]
    else:
        args = ["-u", model_tasks_worker_script_path()]
    return sys.executable, _omit_testing_argv_flags(args)


def use_inline_model_tasks_worker() -> bool:
    """Bundled macOS: run worker in-process (avoid QProcess re-exec → Space/focus steal)."""
    if _BACKGROUND_MODE == "thread":
        return True
    if _BACKGROUND_MODE == "process":
        return False
    return getattr(sys, "frozen", False) and sys.platform == "darwin"


def effective_background_job_mode() -> str:
    """Resolved background job mode for display: ``thread`` or ``process``."""
    return "thread" if use_inline_model_tasks_worker() else "process"
