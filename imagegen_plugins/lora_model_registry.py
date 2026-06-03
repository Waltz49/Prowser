#!/usr/bin/env python3
"""Per-base-model LoRA settings (Schnell, Dev, Fill, Klein 4B/9B)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

from imagegen_plugins.lora_entry import FluxLoraEntry
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX1_FILL,
    HOST_FLUX1_T2I,
    HOST_FLUX2_KLEIN,
    PROBE_DEV,
    PROBE_FILL,
    PROBE_KLEIN_4B,
    PROBE_KLEIN_9B,
    PROBE_SCHNELL,
)

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

LORA_SETTINGS_MODEL_ORDER: Tuple[str, ...] = (
    PROBE_SCHNELL,
    PROBE_DEV,
    PROBE_FILL,
    PROBE_KLEIN_4B,
    PROBE_KLEIN_9B,
)


@dataclass(frozen=True)
class LoraSettingsModel:
    model_key: str
    display_name: str
    used_in: str


LORA_SETTINGS_MODELS: Tuple[LoraSettingsModel, ...] = (
    LoraSettingsModel(
        PROBE_SCHNELL,
        "FLUX.1 Schnell",
        "Create image dialog when Schnell MFLUX is selected",
    ),
    LoraSettingsModel(
        PROBE_DEV,
        "FLUX.1 Dev",
        "Create image dialog when Dev MFLUX is selected",
    ),
    LoraSettingsModel(
        PROBE_FILL,
        "FLUX.1 Fill",
        "Expand and Infill dialogs",
    ),
    LoraSettingsModel(
        PROBE_KLEIN_4B,
        "FLUX.2 Klein 4B",
        "Edit image dialog (4B model)",
    ),
    LoraSettingsModel(
        PROBE_KLEIN_9B,
        "FLUX.2 Klein 9B",
        "Edit image dialog (9B model)",
    ),
)


def lora_models_for_settings() -> Tuple[LoraSettingsModel, ...]:
    by_key = {m.model_key: m for m in LORA_SETTINGS_MODELS}
    return tuple(by_key[k] for k in LORA_SETTINGS_MODEL_ORDER if k in by_key)


def lora_models_for_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Base model keys this LoRA is intended for (probe / settings keys)."""
    if entry.host_id == HOST_FLUX1_T2I:
        mm = (entry.mflux_model or "dev").strip().lower()
        if mm == "schnell":
            return (PROBE_SCHNELL,)
        return (PROBE_DEV,)
    if entry.host_id == HOST_FLUX1_FILL:
        return (PROBE_FILL,)
    if entry.host_id == HOST_FLUX2_KLEIN:
        if entry.klein_variant == "4b":
            return (PROBE_KLEIN_4B,)
        if entry.klein_variant == "9b":
            return (PROBE_KLEIN_9B,)
        return (PROBE_KLEIN_4B, PROBE_KLEIN_9B)
    return ()


def entry_matches_lora_model(entry: FluxLoraEntry, model_key: str) -> bool:
    return model_key in lora_models_for_entry(entry)


def lora_model_key_for_plugin(plugin: "ImageGenModelPlugin") -> Optional[str]:
    host_id = getattr(plugin, "lora_host_id", None)
    if host_id == HOST_FLUX1_T2I:
        hf = (getattr(plugin, "hf_model_id", None) or "").strip().lower()
        if hf == "schnell":
            return PROBE_SCHNELL
        return PROBE_DEV
    if host_id == HOST_FLUX1_FILL:
        return PROBE_FILL
    if host_id == HOST_FLUX2_KLEIN:
        from imagegen_plugins.lora_catalog import klein_variant_for_plugin

        variant = klein_variant_for_plugin(plugin)
        if variant == "9b":
            return PROBE_KLEIN_9B
        if variant == "4b":
            return PROBE_KLEIN_4B
        return None
    return None


def lora_model_key_from_values(values: dict) -> Optional[str]:
    from imagegen_plugins.lora_catalog import klein_variant_from_values
    from imagegen_plugins.lora_host_registry import lora_host_for_pipeline

    pipeline_id = str(values.get("pipeline_id") or "")
    host_id = lora_host_for_pipeline(pipeline_id)
    if host_id == HOST_FLUX1_T2I:
        hf = str(
            values.get("hf_model_id")
            or values.get("mflux_model_name")
            or ""
        ).lower()
        if hf == "schnell":
            return PROBE_SCHNELL
        return PROBE_DEV
    if host_id == HOST_FLUX1_FILL:
        return PROBE_FILL
    if host_id == HOST_FLUX2_KLEIN:
        variant = klein_variant_from_values(values)
        if variant == "9b":
            return PROBE_KLEIN_9B
        if variant == "4b":
            return PROBE_KLEIN_4B
    return None


def host_id_for_lora_model(model_key: str) -> Optional[str]:
    if model_key in (PROBE_SCHNELL, PROBE_DEV):
        return HOST_FLUX1_T2I
    if model_key == PROBE_FILL:
        return HOST_FLUX1_FILL
    if model_key in (PROBE_KLEIN_4B, PROBE_KLEIN_9B):
        return HOST_FLUX2_KLEIN
    return None


def legacy_host_id_to_model_key(host_id: str) -> str:
    """Map old Settings → LoRA host dropdown to a default model key."""
    if host_id == HOST_FLUX1_FILL:
        return PROBE_FILL
    if host_id == HOST_FLUX2_KLEIN:
        return PROBE_KLEIN_4B
    return PROBE_DEV
