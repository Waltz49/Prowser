#!/usr/bin/env python3
"""How to spawn the unified model-tasks worker (dev vs PyInstaller bundle)."""

from __future__ import annotations

import os
import sys

MODEL_TASKS_WORKER_FLAG = "--model-tasks-worker"


def model_tasks_worker_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_tasks_worker.py")


def model_tasks_worker_program_and_args() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, [MODEL_TASKS_WORKER_FLAG]
    return sys.executable, ["-u", model_tasks_worker_script_path()]


def use_inline_model_tasks_worker() -> bool:
    """Bundled macOS: run worker in-process (avoid QProcess re-exec → Space/focus steal)."""
    return getattr(sys, "frozen", False) and sys.platform == "darwin"
