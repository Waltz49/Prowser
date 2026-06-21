#!/usr/bin/env python3
"""
Persist the seed actually used after a run so the user can reproduce (uncheck random seed).

When ``random_seed`` is enabled, workers should return the resolved seed in their final
JSON result (or the controller may set it before spawn). After a successful run, we store
that value in per-dialog settings so the next dialog open shows it in the seed field.

Future pipelines may return the seed under different keys, only in stderr, or resolve it
in the parent; extend ``extract_used_seed_from_worker_result`` per ``pipeline_id`` rather
than assuming a single worker JSON shape.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from imagegen_plugins.image_gen_persistence import (
    load_plugin_dialog_settings,
    save_plugin_dialog_settings,
)


def parse_worker_stdout(stdout: str) -> Optional[Dict[str, Any]]:
    """Last non-progress JSON object from worker stdout (typically the final result line)."""
    result: Optional[Dict[str, Any]] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "progress":
            continue
        if obj.get("error"):
            continue
        if "output_path" in obj or "seed" in obj:
            result = obj
    return result


def extract_used_seed_from_worker_result(
    pipeline_id: str, worker_result: Optional[Dict[str, Any]]
) -> Optional[int]:
    """
    Return the seed that was actually used for this pipeline's last run.

    Override/extend per ``pipeline_id`` when a mode reports seed differently.
    """
    if not worker_result:
        return None

    if pipeline_id == "flux_schnell_mflux_play":
        raw = worker_result.get("seed")
        if raw is not None:
            try:
                return int(raw) % (2**31)
            except (TypeError, ValueError):
                return None

    if pipeline_id == "mflux_fill_expand":
        raw = worker_result.get("seed")
        if raw is not None:
            try:
                return int(raw) % (2**31)
            except (TypeError, ValueError):
                return None

    # Future modes: e.g. return worker_result.get("resolved_seed"), parse stderr, etc.
    raw = worker_result.get("seed")
    if raw is not None:
        try:
            return int(raw) % (2**31)
        except (TypeError, ValueError):
            return None
    return None


def persist_used_seed_if_random(
    function: str,
    pipeline_id: str,
    run_values: Dict[str, Any],
    worker_result: Optional[Dict[str, Any]],
    *,
    fallback_plugin_id: Optional[str] = None,
) -> None:
    """
    If the run used random seed and we know the seed used, save it for reproduction.

    Leaves ``random_seed`` unchanged; user unchecks it later to reuse ``seed``.
    """
    if not run_values.get("random_seed"):
        return
    used = extract_used_seed_from_worker_result(pipeline_id, worker_result)
    if used is None:
        return
    if not fallback_plugin_id:
        return
    saved = load_plugin_dialog_settings(function, fallback_plugin_id)
    saved["seed"] = used
    save_plugin_dialog_settings(function, fallback_plugin_id, saved)
