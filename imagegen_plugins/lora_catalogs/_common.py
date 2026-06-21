#!/usr/bin/env python3
"""Shared helpers for per-host LoRA catalog modules."""

from __future__ import annotations

from typing import Optional

from imagegen_plugins.hf_model_ids import ANYTHING_FURRY, FLUX1_DEV, FLUX1_FILL_DEV
from imagegen_plugins.lora_entry import FluxLoraEntry, LORA_MIN_STEPS
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX1_FILL,
    HOST_FLUX1_T2I,
    HOST_FLUX2_KLEIN,
    HOST_SD15,
)


def catalog_entry(
    host_id: str,
    lora_id: str,
    display_name: str,
    repo_id: str = "",
    filename: str = "",
    *,
    mflux_compatible: Optional[bool] = None,
    local_path: Optional[str] = None,
    scale: float = 1.0,
    min_steps: int = LORA_MIN_STEPS,
    base_hf_model_id: str = FLUX1_DEV,
    trigger_word: Optional[str] = None,
) -> FluxLoraEntry:
    return FluxLoraEntry(
        host_id=host_id,
        lora_id=lora_id,
        display_name=display_name,
        repo_id=repo_id,
        filename=filename,
        scale=scale,
        local_path=local_path,
        base_hf_model_id=base_hf_model_id,
        min_steps=min_steps,
        mflux_compatible=mflux_compatible,
        trigger_word=trigger_word,
    )


def t2i_entry(
    lora_id: str,
    display_name: str,
    repo_id: str,
    filename: str,
    **kwargs,
) -> FluxLoraEntry:
    return catalog_entry(HOST_FLUX1_T2I, lora_id, display_name, repo_id, filename, **kwargs)


def fill_entry(
    lora_id: str,
    display_name: str,
    repo_id: str,
    filename: str,
    **kwargs,
) -> FluxLoraEntry:
    return catalog_entry(
        HOST_FLUX1_FILL,
        lora_id,
        display_name,
        repo_id,
        filename,
        base_hf_model_id=FLUX1_FILL_DEV,
        **kwargs,
    )


def klein_entry(
    lora_id: str,
    display_name: str,
    repo_id: str,
    filename: str,
    *,
    base_hf_model_id: str,
    **kwargs,
) -> FluxLoraEntry:
    return catalog_entry(
        HOST_FLUX2_KLEIN,
        lora_id,
        display_name,
        repo_id,
        filename,
        base_hf_model_id=base_hf_model_id,
        **kwargs,
    )


def sd15_entry(
    lora_id: str,
    display_name: str,
    repo_id: str,
    filename: str,
    **kwargs,
) -> FluxLoraEntry:
    # host_id=HOST_SD15 → all SD15_LORA_MODEL_KEYS (see lora_models_for_entry).
    return catalog_entry(
        HOST_SD15,
        lora_id,
        display_name,
        repo_id,
        filename,
        base_hf_model_id=ANYTHING_FURRY,
        mflux_compatible=True,
        **kwargs,
    )
