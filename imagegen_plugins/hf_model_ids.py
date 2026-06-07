#!/usr/bin/env python3
"""Canonical Hugging Face model ids for image generation and LoRA settings."""

from __future__ import annotations

FLUX1_SCHNELL = "black-forest-labs/FLUX.1-schnell"
FLUX1_DEV = "black-forest-labs/FLUX.1-dev"
FLUX1_FILL_DEV = "black-forest-labs/FLUX.1-Fill-dev"
FLUX2_KLEIN_4B = "black-forest-labs/FLUX.2-klein-4B"
FLUX2_KLEIN_9B = "black-forest-labs/FLUX.2-klein-9B"

LORA_PROBE_MODEL_ORDER: tuple[str, ...] = (
    FLUX1_SCHNELL,
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
)

LORA_MODEL_DISPLAY_NAMES: dict[str, str] = {
    FLUX1_SCHNELL: "FLUX.1 Schnell",
    FLUX1_DEV: "FLUX.1 Dev",
    FLUX1_FILL_DEV: "FLUX.1 Fill",
    FLUX2_KLEIN_4B: "FLUX.2 Klein 4B",
    FLUX2_KLEIN_9B: "FLUX.2 Klein 9B",
}


def lora_model_display_name(hf_model_id: str) -> str:
    return LORA_MODEL_DISPLAY_NAMES.get(hf_model_id, hf_model_id)
