#!/usr/bin/env python3
"""Freeze dialog-controlled job inputs at submit time for queued generation."""

from __future__ import annotations

from typing import Any, Dict, List

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

JOB_VALUES_SNAPSHOTTED_KEY = "_job_values_snapshotted"
LORA_SCALES_BY_ID_KEY = "mflux_lora_scales_by_id"
LORA_TRIGGER_WORDS_KEY = "mflux_lora_trigger_words"


def job_values_snapshotted(values: Dict[str, Any] | None) -> bool:
    return bool(isinstance(values, dict) and values.get(JOB_VALUES_SNAPSHOTTED_KEY))


def _lora_scale_for_preset(values: Dict[str, Any], preset_id: str) -> float:
    scales_by_id = values.get(LORA_SCALES_BY_ID_KEY)
    if isinstance(scales_by_id, dict) and preset_id in scales_by_id:
        try:
            return float(scales_by_id[preset_id])
        except (TypeError, ValueError):
            pass
    from imagegen_plugins.lora_catalog import get_lora_entry

    entry = get_lora_entry(preset_id)
    if entry is not None:
        return float(entry.scale)
    return 1.0


def _snapshot_lora_for_job(values: Dict[str, Any], pipeline_id: str) -> None:
    from imagegen_plugins.lora_catalog import get_lora_entry
    from imagegen_plugins.lora_host_registry import HOST_SD15, HOST_SDXL, lora_host_for_pipeline
    from imagegen_plugins.mflux_lora_presets import (
        effective_lora_ids_from_values,
        resolve_lora_path,
    )

    host = lora_host_for_pipeline(pipeline_id)
    stack = effective_lora_ids_from_values(
        values, pipeline_id=pipeline_id, pop=False
    )
    if not stack:
        values.pop("mflux_lora_paths", None)
        values.pop("mflux_lora_scales", None)
        values.pop("sd15_lora_paths", None)
        values.pop("sd15_lora_scales", None)
        values.pop("sdxl_lora_paths", None)
        values.pop("sdxl_lora_scales", None)
        values.pop(LORA_TRIGGER_WORDS_KEY, None)
        return

    paths: List[str] = []
    scales: List[float] = []
    trigger_words: List[str] = []
    for preset_id in stack:
        entry = get_lora_entry(preset_id)
        if entry is None:
            raise ValueError(f"Unknown LoRA preset: {preset_id}")
        paths.append(resolve_lora_path(preset_id))
        scales.append(_lora_scale_for_preset(values, preset_id))
        trigger = (entry.trigger_word or "").strip()
        if trigger:
            trigger_words.append(trigger)

    values[LORA_TRIGGER_WORDS_KEY] = trigger_words
    if host == HOST_SD15:
        values["sd15_lora_paths"] = paths
        values["sd15_lora_scales"] = scales
        values.pop("mflux_lora_paths", None)
        values.pop("mflux_lora_scales", None)
        values.pop("sdxl_lora_paths", None)
        values.pop("sdxl_lora_scales", None)
    elif host == HOST_SDXL:
        values["sdxl_lora_paths"] = paths
        values["sdxl_lora_scales"] = scales
        values.pop("mflux_lora_paths", None)
        values.pop("mflux_lora_scales", None)
        values.pop("sd15_lora_paths", None)
        values.pop("sd15_lora_scales", None)
    else:
        values["mflux_lora_paths"] = paths
        values["mflux_lora_scales"] = scales
        values.pop("sd15_lora_paths", None)
        values.pop("sd15_lora_scales", None)
        values.pop("sdxl_lora_paths", None)
        values.pop("sdxl_lora_scales", None)


def snapshot_job_values_at_submit(
    plugin: ImageGenModelPlugin, values: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a copy of job values frozen for execution at submit time."""
    from config import get_config
    from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin
    from imagegen_plugins.image_gen_pipeline_modes import get_pipeline

    out = dict(values)
    pipeline_id = plugin.pipeline_id
    out["pipeline_id"] = pipeline_id
    _snapshot_lora_for_job(out, pipeline_id)

    mode = get_pipeline(pipeline_id)
    if mode.supports_progressive_images:
        from imagegen_plugins.image_gen_persistence import load_show_progressive_images

        out["show_progressive_images"] = load_show_progressive_images()

    out["debug_mode"] = bool(
        get_config().load_settings().get("debug_mode", False)
    )
    out["max_generation_dimension"] = effective_max_for_plugin(plugin)
    out[JOB_VALUES_SNAPSHOTTED_KEY] = True
    return out


__all__ = [
    "JOB_VALUES_SNAPSHOTTED_KEY",
    "LORA_SCALES_BY_ID_KEY",
    "LORA_TRIGGER_WORDS_KEY",
    "job_values_snapshotted",
    "snapshot_job_values_at_submit",
]
