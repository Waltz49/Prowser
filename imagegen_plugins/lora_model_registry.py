#!/usr/bin/env python3
"""Per-base-model LoRA settings (full Hugging Face model ids)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    LORA_PROBE_MODEL_ORDER,
    SD15_LORA_MODEL_KEYS,
    ANYTHING_FURRY,
    REALISTIC_VISION_V4_NOVAE,
)
from imagegen_plugins.lora_entry import FluxLoraEntry
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX1_FILL,
    HOST_FLUX1_T2I,
    HOST_FLUX2_KLEIN,
    HOST_SD15,
)

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

LORA_SETTINGS_MODEL_ORDER: Tuple[str, ...] = LORA_PROBE_MODEL_ORDER

# Display order for Settings → LoRA “Available in” (supports multiple functions per model).
_LORA_FUNCTION_DISPLAY_ORDER: Tuple[str, ...] = (
    "create",
    "edit",
    "expand",
    "infill",
    "infill_paint",
)


@dataclass(frozen=True)
class LoraSettingsModel:
    model_key: str
    display_name: str
    used_in: str
    available_in: Tuple[str, ...] = ()


LORA_SETTINGS_MODELS: Tuple[LoraSettingsModel, ...] = (
    LoraSettingsModel(
        FLUX1_SCHNELL,
        FLUX1_SCHNELL,
        "Create image dialog when FLUX.1 Schnell is selected",
        ("create",),
    ),
    LoraSettingsModel(
        FLUX1_DEV,
        FLUX1_DEV,
        "Create image dialog when FLUX.1 Dev is selected",
        ("create",),
    ),
    LoraSettingsModel(
        FLUX1_FILL_DEV,
        FLUX1_FILL_DEV,
        "Expand and Infill dialogs",
        ("expand", "infill"),
    ),
    LoraSettingsModel(
        FLUX2_KLEIN_4B,
        FLUX2_KLEIN_4B,
        "Create and Edit dialogs (4B model)",
        ("create", "edit"),
    ),
    LoraSettingsModel(
        FLUX2_KLEIN_9B,
        FLUX2_KLEIN_9B,
        "Create and Edit dialogs (9B model)",
        ("create", "edit"),
    ),
    LoraSettingsModel(
        FLUX2_KLEIN_9B_KV,
        FLUX2_KLEIN_9B_KV,
        "Create and Edit dialogs (9B KV model)",
        ("create", "edit"),
    ),
    LoraSettingsModel(
        REALISTIC_VISION_V4_NOVAE,
        REALISTIC_VISION_V4_NOVAE,
        "Create image dialog when Realistic Vision V4.0 is selected",
        ("create",),
    ),
    LoraSettingsModel(
        ANYTHING_FURRY,
        ANYTHING_FURRY,
        "Create image dialog when Anything Furry is selected",
        ("create",),
    ),
)


def lora_models_for_settings() -> Tuple[LoraSettingsModel, ...]:
    by_key = {m.model_key: m for m in LORA_SETTINGS_MODELS}
    return tuple(by_key[k] for k in LORA_SETTINGS_MODEL_ORDER if k in by_key)


def lora_settings_model(model_key: str) -> Optional[LoraSettingsModel]:
    mk = (model_key or "").strip()
    if not mk:
        return None
    return next((m for m in LORA_SETTINGS_MODELS if m.model_key == mk), None)


def lora_functions_for_model_key(model_key: str) -> Tuple[str, ...]:
    """
    Image-gen functions whose plugins use this base model and support LoRAs.

    Uses registered plugins when available; falls back to catalog ``available_in``.
    """
    mk = (model_key or "").strip()
    if not mk:
        return ()

    found: List[str] = []
    try:
        from imagegen_plugins import plugins_for_function

        for fn in _LORA_FUNCTION_DISPLAY_ORDER:
            for plugin in plugins_for_function(fn):
                if (getattr(plugin, "hf_model_id", None) or "").strip() != mk:
                    continue
                if not getattr(plugin, "lora_host_id", None):
                    continue
                if fn not in found:
                    found.append(fn)
                break
    except Exception:
        found = []

    if found:
        return tuple(found)

    model = lora_settings_model(mk)
    if model is not None and model.available_in:
        return model.available_in
    return ()


_FUNCTION_SHORT_LABELS = {
    "create": "Create",
    "edit": "Edit",
    "expand": "Expand",
    "infill": "Infill",
    "infill_paint": "Infill",
}


def lora_model_available_in_label(model_key: str) -> str:
    """Settings line: ``Available in: Create, Edit, …``"""
    labels: List[str] = []
    for fn in lora_functions_for_model_key(model_key):
        label = _FUNCTION_SHORT_LABELS.get(fn, fn)
        if label not in labels:
            labels.append(label)
    if not labels:
        return ""
    return "Available in: " + ", ".join(labels)


def lora_models_for_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Base model keys this LoRA is intended for (full hf_model_id)."""
    if entry.host_id == HOST_SD15:
        return SD15_LORA_MODEL_KEYS
    if entry.base_hf_model_id:
        return (entry.base_hf_model_id,)
    if entry.host_id == HOST_FLUX1_FILL:
        return (FLUX1_FILL_DEV,)
    return ()


def lora_probe_pipeline_id(model_key: str) -> Optional[str]:
    """Pipeline used to test whether base weights for Check LoRAs are on disk."""
    mk = (model_key or "").strip()
    if mk in (FLUX1_SCHNELL, FLUX1_DEV):
        return "flux_schnell_mflux_play"
    if mk == FLUX1_FILL_DEV:
        return "mflux_fill_infill"
    if mk in (FLUX2_KLEIN_4B, FLUX2_KLEIN_9B, FLUX2_KLEIN_9B_KV):
        return "mflux_flux2_klein_edit"
    if mk in SD15_LORA_MODEL_KEYS:
        return "sd15_diffusers"
    return None


def lora_probe_model_is_local(model_key: str) -> bool:
    """True when the base model is present locally (no download during Check LoRAs)."""
    from imagegen_plugins.image_gen_model_availability import pipeline_model_is_local

    pipeline_id = lora_probe_pipeline_id(model_key)
    if not pipeline_id:
        return True
    return pipeline_model_is_local(pipeline_id, model_key)


def klein_lora_model_aliases(model_key: str) -> Tuple[str, ...]:
    """Edit models that accept the same Klein LoRAs as full 9B."""
    mk = (model_key or "").strip()
    if mk == FLUX2_KLEIN_9B_KV:
        return (FLUX2_KLEIN_9B_KV, FLUX2_KLEIN_9B)
    return (mk,) if mk else ()


def entry_matches_lora_model(entry: FluxLoraEntry, model_key: str) -> bool:
    entry_models = lora_models_for_entry(entry)
    return any(m in entry_models for m in klein_lora_model_aliases(model_key))


def lora_model_key_for_plugin(plugin: "ImageGenModelPlugin") -> Optional[str]:
    hf = (getattr(plugin, "hf_model_id", None) or "").strip()
    return hf or None


def lora_model_key_from_values(values: dict) -> Optional[str]:
    hf = str(values.get("hf_model_id") or "").strip()
    return hf or None


def host_id_for_lora_model(model_key: str) -> Optional[str]:
    if model_key in (FLUX1_SCHNELL, FLUX1_DEV):
        return HOST_FLUX1_T2I
    if model_key == FLUX1_FILL_DEV:
        return HOST_FLUX1_FILL
    if model_key in (FLUX2_KLEIN_4B, FLUX2_KLEIN_9B, FLUX2_KLEIN_9B_KV):
        return HOST_FLUX2_KLEIN
    if model_key in SD15_LORA_MODEL_KEYS:
        return HOST_SD15
    return None


def legacy_host_id_to_model_key(host_id: str) -> str:
    """Map old Settings → LoRA host dropdown to a default model key."""
    if host_id == HOST_FLUX1_FILL:
        return FLUX1_FILL_DEV
    if host_id == HOST_FLUX2_KLEIN:
        return FLUX2_KLEIN_4B
    return FLUX1_DEV
