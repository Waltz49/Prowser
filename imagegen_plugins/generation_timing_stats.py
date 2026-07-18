#!/usr/bin/env python3
"""Average generation durations keyed by model + parameter combination."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

_MAX_ENTRIES = 200
_FILE_VERSION = 1
GenerationTimingKey = Tuple[Any, ...]

_store: OrderedDict[GenerationTimingKey, "_TimingEntry"] = OrderedDict()
_loaded = False


@dataclass
class _TimingEntry:
    total_seconds: float
    run_count: int

    @property
    def average_seconds(self) -> float:
        if self.run_count <= 0:
            return 0.0
        return self.total_seconds / self.run_count


@dataclass(frozen=True)
class GenerationTimingRow:
    model_name: str
    size: str
    width: int
    height: int
    steps: int
    quant: str
    run_count: int
    total_seconds: float
    avg_seconds: float


def timing_stats_file_path() -> Path:
    from config import get_config

    return get_config().data_dir / "generation_timing_stats.json"


def _model_display_name_for_id(model_id: str) -> str:
    from imagegen_plugins import discover_plugins
    from imagegen_plugins.image_gen_model_availability import model_display_name

    mid = str(model_id or "").strip()
    if not mid:
        return ""
    for plugin in discover_plugins():
        if plugin.hf_model_id == mid or plugin.plugin_id == mid:
            return model_display_name(plugin.pipeline_id, plugin.hf_model_id or mid)
    if "/" in mid:
        return mid.split("/")[-1].replace("_", " ")
    return mid


def _key_to_record(
    key: GenerationTimingKey, entry: _TimingEntry
) -> Dict[str, Any]:
    model_id, steps, width, height, quant, lora_stack = key
    return {
        "model_id": str(model_id),
        "steps": int(steps),
        "width": int(width),
        "height": int(height),
        "quant": str(quant or ""),
        "lora_stack": list(lora_stack),
        "total_seconds": float(entry.total_seconds),
        "run_count": int(entry.run_count),
    }


def _record_to_key(record: Dict[str, Any]) -> GenerationTimingKey | None:
    try:
        model_id = str(record.get("model_id") or "").strip()
        steps = int(record.get("steps") or 0)
        width = int(record.get("width") or 0)
        height = int(record.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if not model_id or width <= 0 or height <= 0:
        return None
    quant = str(record.get("quant") or "")
    lora_raw = record.get("lora_stack")
    if isinstance(lora_raw, list):
        lora_stack = tuple(str(item) for item in lora_raw)
    else:
        lora_stack = ()
    return (model_id, steps, width, height, quant, lora_stack)


def _trim_store() -> None:
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)


def _save_store() -> None:
    path = timing_stats_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _FILE_VERSION,
        "entries": [
            _key_to_record(key, entry) for key, entry in _store.items()
        ],
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def _load_store() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    path = timing_stats_file_path()
    if not path.is_file():
        return
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return

    loaded: OrderedDict[GenerationTimingKey, _TimingEntry] = OrderedDict()
    for item in entries:
        if not isinstance(item, dict):
            continue
        key = _record_to_key(item)
        if key is None:
            continue
        try:
            total_seconds = float(item.get("total_seconds") or 0)
            run_count = int(item.get("run_count") or 0)
        except (TypeError, ValueError):
            continue
        if total_seconds <= 0 or run_count <= 0:
            continue
        loaded[key] = _TimingEntry(
            total_seconds=total_seconds,
            run_count=run_count,
        )
    _store.clear()
    _store.update(loaded)
    _trim_store()


def build_generation_timing_key(
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> GenerationTimingKey | None:
    """Hashable key for model + steps + size + quant + LoRA list, or None if size unknown."""
    from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin
    from imagegen_plugins.image_gen_pipeline_modes import generation_status_display_size
    from imagegen_plugins.mflux_lora_presets import normalize_lora_stack_from_values
    from imagegen_plugins.model_task_status_info import _generation_model_id_for_status

    effective = dict(values)
    if payload:
        effective.update(payload)

    model_id = _generation_model_id_for_status(plugin, effective)
    if not model_id:
        model_id = str(plugin.plugin_id or "").strip()
    if not model_id:
        return None

    try:
        steps = int(effective.get("steps") or 0)
    except (TypeError, ValueError):
        steps = 0

    size = generation_status_display_size(
        plugin.pipeline_id,
        values,
        payload,
        effective_max_side=effective_max_for_plugin(plugin),
    )
    if size is None:
        try:
            width = int(effective.get("width") or 0)
            height = int(effective.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        if width > 0 and height > 0:
            size = (width, height)
    if size is None:
        return None

    quant = plugin.quantize_status_value(effective) or ""
    lora_stack = tuple(normalize_lora_stack_from_values(effective, pop=False))

    return (model_id, steps, int(size[0]), int(size[1]), quant, lora_stack)


def lookup_average(key: GenerationTimingKey | None) -> float | None:
    """Return average total generation seconds for key, or None if unknown."""
    _load_store()
    if key is None:
        return None
    entry = _store.get(key)
    if entry is None or entry.run_count <= 0 or entry.total_seconds <= 0:
        return None
    _store.move_to_end(key)
    return entry.average_seconds


def record_run(key: GenerationTimingKey | None, elapsed_seconds: float) -> None:
    """Record one successful generation and update the running average."""
    _load_store()
    if key is None:
        return
    try:
        elapsed = float(elapsed_seconds)
    except (TypeError, ValueError):
        return
    if elapsed <= 0:
        return

    entry = _store.get(key)
    if entry is None:
        entry = _TimingEntry(total_seconds=elapsed, run_count=1)
        _store[key] = entry
    else:
        entry.total_seconds += elapsed
        entry.run_count += 1
        _store.move_to_end(key)

    _trim_store()
    try:
        _save_store()
    except OSError:
        pass


def list_timing_rows() -> List[GenerationTimingRow]:
    """Rows for the debug timings table (most recently used first)."""
    _load_store()
    rows: List[GenerationTimingRow] = []
    for key, entry in reversed(_store.items()):
        model_id, steps, width, height, quant, _lora_stack = key
        rows.append(
            GenerationTimingRow(
                model_name=_model_display_name_for_id(str(model_id)),
                size=f"{int(width)} x {int(height)}",
                width=int(width),
                height=int(height),
                steps=int(steps),
                quant=str(quant or ""),
                run_count=int(entry.run_count),
                total_seconds=float(entry.total_seconds),
                avg_seconds=entry.average_seconds,
            )
        )
    return rows
