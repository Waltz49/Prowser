#!/usr/bin/env python3
"""Canonical Hugging Face model ids for image generation and LoRA settings."""

from __future__ import annotations

FLUX1_SCHNELL = "black-forest-labs/FLUX.1-schnell"
FLUX1_DEV = "black-forest-labs/FLUX.1-dev"
FLUX1_FILL_DEV = "black-forest-labs/FLUX.1-Fill-dev"
FLUX2_KLEIN_4B = "black-forest-labs/FLUX.2-klein-4B"
FLUX2_KLEIN_9B = "black-forest-labs/FLUX.2-klein-9B"
FLUX2_KLEIN_9B_KV = "black-forest-labs/FLUX.2-klein-9b-kv"

REALISTIC_VISION_V4_NOVAE = "SG161222/Realistic_Vision_V4.0_noVAE"
ANYTHING_FURRY = "stablediffusionapi/anythingfurry"
SD15_DEFAULT_VAE = "stabilityai/sd-vae-ft-mse"

Z_IMAGE_TURBO_SDNQ_INT8 = "Disty0/Z-Image-Turbo-SDNQ-int8"

# SD 1.5 checkpoints that use HOST_SD15 (settings + run dialog LoRA lists).
SD15_LORA_MODEL_KEYS: tuple[str, ...] = (
    REALISTIC_VISION_V4_NOVAE,
    ANYTHING_FURRY,
)

LORA_PROBE_MODEL_ORDER: tuple[str, ...] = (
    FLUX1_SCHNELL,
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    REALISTIC_VISION_V4_NOVAE,
    ANYTHING_FURRY,
)

LORA_MODEL_DISPLAY_NAMES: dict[str, str] = {
    FLUX1_SCHNELL: "FLUX.1 Schnell",
    FLUX1_DEV: "FLUX.1 Dev",
    FLUX1_FILL_DEV: "FLUX.1 Fill",
    FLUX2_KLEIN_4B: "FLUX.2 Klein 4B",
    FLUX2_KLEIN_9B: "FLUX.2 Klein 9B",
    FLUX2_KLEIN_9B_KV: "FLUX.2 Klein 9B KV",
    REALISTIC_VISION_V4_NOVAE: "Realistic Vision V4.0",
    ANYTHING_FURRY: "Anything Furry",
    Z_IMAGE_TURBO_SDNQ_INT8: "Z-Image Turbo (8-bit)",
}


def lora_model_display_name(hf_model_id: str) -> str:
    return LORA_MODEL_DISPLAY_NAMES.get(hf_model_id, hf_model_id)
