#!/usr/bin/env python3
"""SD 1.5 LoRA resolution for diffusers StableDiffusionPipeline."""

from __future__ import annotations

from typing import Any, Dict

from imagegen_plugins.lora_catalog import get_lora_entry, lora_model_key_from_values, lora_probe_passed_for_model
from imagegen_plugins.lora_host_registry import HOST_SD15
from imagegen_plugins.mflux_lora_presets import _normalize_preset_id, resolve_lora_path


def apply_lora_to_sd15_payload(merged: Dict[str, object]) -> None:
    """Set sd15_lora_paths/scales when a catalog LoRA is selected."""
    merged.pop("mflux_lora_stack", None)
    preset_id = _normalize_preset_id(merged.pop("mflux_lora", "none") or "none")
    if preset_id == "none":
        merged.pop("sd15_lora_paths", None)
        merged.pop("sd15_lora_scales", None)
        return

    entry = get_lora_entry(preset_id)
    if entry is None:
        raise ValueError(f"Unknown SD 1.5 LoRA preset: {preset_id}")
    if entry.host_id != HOST_SD15:
        raise ValueError(f"LoRA «{entry.display_name}» is not for SD 1.5.")

    from config import get_config
    from imagegen_plugins.hf_model_ids import ANYTHING_FURRY, SD15_LORA_MODEL_KEYS

    model_key = lora_model_key_from_values(dict(merged)) or (
        SD15_LORA_MODEL_KEYS[0] if SD15_LORA_MODEL_KEYS else ANYTHING_FURRY
    )
    settings = get_config().load_settings()
    if not lora_probe_passed_for_model(preset_id, model_key, settings):
        raise ValueError(
            f"LoRA «{entry.display_name}» is not enabled for this base model. "
            "Enable it in Settings → LoRA."
        )

    path = resolve_lora_path(preset_id)
    merged["sd15_lora_paths"] = [path]
    merged["sd15_lora_scales"] = [entry.scale]
