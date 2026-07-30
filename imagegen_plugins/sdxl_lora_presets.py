#!/usr/bin/env python3
"""SDXL LoRA resolution for diffusers StableDiffusionXLPipeline."""

from __future__ import annotations

from typing import Any, Dict, List

from imagegen_plugins.job_values_snapshot import LORA_SCALES_BY_ID_KEY
from imagegen_plugins.lora_catalog import (
    get_lora_entry,
    lora_model_key_from_values,
    lora_probe_passed_for_model,
)
from imagegen_plugins.lora_host_registry import HOST_SDXL
from imagegen_plugins.mflux_lora_presets import (
    effective_lora_ids_from_values,
    effective_steps_for_lora_stack,
    resolve_lora_path,
    strip_lora_payload_keys_for_host,
)


def _lora_scale_for_preset(values: Dict[str, Any], preset_id: str, entry_scale: float) -> float:
    scales_by_id = values.get(LORA_SCALES_BY_ID_KEY)
    if isinstance(scales_by_id, dict) and preset_id in scales_by_id:
        try:
            return float(scales_by_id[preset_id])
        except (TypeError, ValueError):
            pass
    return float(entry_scale)


def apply_lora_to_sdxl_payload(merged: Dict[str, object]) -> None:
    """Set sdxl_lora_paths/scales when one or more catalog LoRAs are selected."""
    from imagegen_plugins.job_values_snapshot import job_values_snapshotted

    pipeline_id = str(merged.get("pipeline_id") or "").strip() or None
    if job_values_snapshotted(dict(merged)):
        snap_paths = merged.get("sdxl_lora_paths")
        snap_scales = merged.get("sdxl_lora_scales")
        if isinstance(snap_paths, list) and isinstance(snap_scales, list):
            saved_paths = list(snap_paths)
            saved_scales = list(snap_scales)
            stack = effective_lora_ids_from_values(
                merged,
                pipeline_id=pipeline_id,
                pop=True,
            )
            merged.pop("mflux_lora_stack", None)
            strip_lora_payload_keys_for_host(merged, host_id=HOST_SDXL, pop=True)
            if not stack:
                merged.pop("sdxl_lora_paths", None)
                merged.pop("sdxl_lora_scales", None)
                return
            if len(saved_paths) == len(saved_scales) == len(stack):
                merged["sdxl_lora_paths"] = saved_paths
                merged["sdxl_lora_scales"] = saved_scales
                merged["steps"] = effective_steps_for_lora_stack(
                    int(merged.get("steps") or 0),
                    stack,
                    for_fill=False,
                )
                return

    stack = effective_lora_ids_from_values(
        merged,
        pipeline_id=pipeline_id,
        pop=True,
    )
    merged.pop("mflux_lora_stack", None)
    strip_lora_payload_keys_for_host(merged, host_id=HOST_SDXL, pop=True)
    if not stack:
        merged.pop("sdxl_lora_paths", None)
        merged.pop("sdxl_lora_scales", None)
        return

    from config import get_config
    from imagegen_plugins.hf_model_ids import SDXL_BASE_1_0, SDXL_LORA_MODEL_KEYS

    model_key = lora_model_key_from_values(dict(merged)) or (
        SDXL_LORA_MODEL_KEYS[0] if SDXL_LORA_MODEL_KEYS else SDXL_BASE_1_0
    )
    settings = get_config().load_settings()
    paths: List[str] = []
    scales: List[float] = []

    for preset_id in stack:
        entry = get_lora_entry(preset_id)
        if entry is None:
            raise ValueError(f"Unknown SDXL LoRA preset: {preset_id}")
        if entry.host_id != HOST_SDXL:
            raise ValueError(f"LoRA «{entry.display_name}» is not for SDXL.")
        if not lora_probe_passed_for_model(preset_id, model_key, settings):
            raise ValueError(
                f"LoRA «{entry.display_name}» is not enabled for this base model. "
                "Enable it in Settings → LoRA."
            )
        paths.append(resolve_lora_path(preset_id))
        scales.append(_lora_scale_for_preset(dict(merged), preset_id, entry.scale))

    merged["sdxl_lora_paths"] = paths
    merged["sdxl_lora_scales"] = scales
    merged["steps"] = effective_steps_for_lora_stack(
        int(merged.get("steps") or 0),
        stack,
        for_fill=False,
    )
