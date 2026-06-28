#!/usr/bin/env python3
"""Shared MFLUX stepwise PNG watching and progress JSON for model_tasks_worker."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading

from prowser_temp_files import prowser_mkdtemp, prowser_mkstemp_path
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

_MFLUX_STEPWISE_RE = re.compile(r"^seed_(\d+)_step(\d+)of(\d+)\.png$", re.IGNORECASE)


def emit_mflux_progress(
    output_path: str | None = None,
    *,
    step: int | None = None,
    step_total: int | None = None,
) -> None:
    msg: Dict[str, Any] = {"type": "progress"}
    if output_path:
        msg["path"] = output_path
    if step is not None:
        msg["step"] = int(step)
    if step_total is not None:
        msg["step_total"] = int(step_total)
    from workers.model_tasks_worker import emit_worker_message

    emit_worker_message(msg)


def atomic_copy2(src: str, dst: str) -> None:
    """Copy src to dst using a temp file under the configured Prowser temp directory."""
    tmp_path = prowser_mkstemp_path(prefix="imagegen-progress-", suffix=".png")
    try:
        shutil.copy2(src, tmp_path)
        shutil.copy2(tmp_path, dst)
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def _parse_stepwise_name(name: str) -> Optional[Tuple[int, int, int]]:
    m = _MFLUX_STEPWISE_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def watch_stepwise_to_output(
    stepwise_dir: str,
    output_path: str | None,
    seed: int,
    stop_event: threading.Event,
    poll_interval: float = 0.25,
) -> None:
    """Watch MFLUX step PNGs; optionally copy to output_path and emit step progress."""
    seen: Set[str] = set()
    while not stop_event.is_set():
        try:
            names = os.listdir(stepwise_dir)
        except OSError:
            time.sleep(poll_interval)
            continue
        for name in sorted(names):
            if name in seen or "composite" in name.lower():
                continue
            parsed = _parse_stepwise_name(name)
            if parsed is None:
                continue
            file_seed, step_num, total = parsed
            if file_seed != seed or step_num >= total:
                continue
            full = os.path.join(stepwise_dir, name)
            if not os.path.isfile(full) or os.path.getsize(full) < 64:
                continue
            seen.add(name)
            try:
                if output_path:
                    atomic_copy2(full, output_path)
                emit_mflux_progress(
                    output_path if output_path else None,
                    step=step_num,
                    step_total=total,
                )
            except OSError:
                pass
        time.sleep(poll_interval)


def stepwise_dirs_for_run(steps: int, output_path: str) -> tuple[str | None, str | None]:
    """Return (stepwise_dir, progressive_output_path) when steps > 1."""
    if steps > 1:
        return prowser_mkdtemp(prefix="imagegen-mflux-stepwise-"), output_path
    return None, None


def run_with_stepwise_watcher(
    *,
    seed: int,
    stepwise_dir: str | None,
    progressive_output_path: str | None,
    run: Callable[[], None],
) -> None:
    stop_watcher = threading.Event()
    watcher: threading.Thread | None = None
    if stepwise_dir:
        watcher = threading.Thread(
            target=watch_stepwise_to_output,
            args=(
                stepwise_dir,
                progressive_output_path,
                seed,
                stop_watcher,
            ),
            daemon=True,
        )
        watcher.start()
    try:
        run()
    finally:
        if watcher is not None:
            stop_watcher.set()
            watcher.join(timeout=60)


def finalize_stepwise_progress(output_path: str, steps: int) -> None:
    if steps > 1:
        emit_mflux_progress(output_path, step=steps, step_total=steps)


def cleanup_stepwise_dir(stepwise_dir: str | None) -> None:
    if stepwise_dir:
        shutil.rmtree(stepwise_dir, ignore_errors=True)
