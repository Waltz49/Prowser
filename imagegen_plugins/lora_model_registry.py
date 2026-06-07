#!/usr/bin/env python3
"""Per-base-model LoRA settings (full Hugging Face model ids)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    LORA_PROBE_MODEL_ORDER,
    lora_model_display_name,
)
from imagegen_plugins.lora_entry import FluxLoraEntry
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX1_FILL,
    HOST_FLUX1_T2I,
    HOST_FLUX2_KLEIN,
)

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

LORA_SETTINGS_MODEL_ORDER: Tuple[str, ...] = LORA_PROBE_MODEL_ORDER


@dataclass(frozen=True)
class LoraSettingsModel:
    model_key: str
    display_name: str
    used_in: str


LORA_SETTINGS_MODELS: Tuple[LoraSettingsModel, ...] = (
    LoraSettingsModel(
        FLUX1_SCHNELL,
        lora_model_display_name(FLUX1_SCHNELL),
        "Create image dialog when FLUX.1 Schnell is selected",
    ),
    LoraSettingsModel(
        FLUX1_DEV,
        lora_model_display_name(FLUX1_DEV),
        "Create image dialog when FLUX.1 Dev is selected",
    ),
    LoraSettingsModel(
        FLUX1_FILL_DEV,
        lora_model_display_name(FLUX1_FILL_DEV),
        "Expand and Infill dialogs",
    ),
    LoraSettingsModel(
        FLUX2_KLEIN_4B,
        lora_model_display_name(FLUX2_KLEIN_4B),
        "Edit image dialog (4B model)",
    ),
    LoraSettingsModel(
        FLUX2_KLEIN_9B,
        lora_model_display_name(FLUX2_KLEIN_9B),
        "Edit image dialog (9B model)",
    ),
)


def lora_models_for_settings() -> Tuple[LoraSettingsModel, ...]:
    by_key = {m.model_key: m for m in LORA_SETTINGS_MODELS}
    return tuple(by_key[k] for k in LORA_SETTINGS_MODEL_ORDER if k in by_key)


def lora_models_for_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Base model keys this LoRA is intended for (full hf_model_id)."""
    if entry.base_hf_model_id:
        return (entry.base_hf_model_id,)
    if entry.host_id == HOST_FLUX1_FILL:
        return (FLUX1_FILL_DEV,)
    return ()


def entry_matches_lora_model(entry: FluxLoraEntry, model_key: str) -> bool:
    return model_key in lora_models_for_entry(entry)


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
    if model_key in (FLUX2_KLEIN_4B, FLUX2_KLEIN_9B):
        return HOST_FLUX2_KLEIN
    return None


def legacy_host_id_to_model_key(host_id: str) -> str:
    """Map old Settings → LoRA host dropdown to a default model key."""
    if host_id == HOST_FLUX1_FILL:
        return FLUX1_FILL_DEV
    if host_id == HOST_FLUX2_KLEIN:
        return FLUX2_KLEIN_4B
    return FLUX1_DEV
