#!/usr/bin/env python3
"""Canonical Hugging Face model ids for image generation and LoRA settings."""

from __future__ import annotations

FLUX1_SCHNELL = "black-forest-labs/FLUX.1-schnell"
FLUX1_DEV = "black-forest-labs/FLUX.1-dev"
FLUX1_FILL_DEV = "black-forest-labs/FLUX.1-Fill-dev"
FLUX2_KLEIN_4B = "black-forest-labs/FLUX.2-klein-4B"
FLUX2_KLEIN_9B = "black-forest-labs/FLUX.2-klein-9B"
FLUX2_KLEIN_9B_KV = "black-forest-labs/FLUX.2-klein-9b-kv"
SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX = "SceneWorks/flux2-klein-9b-kv-mlx"

REALISTIC_VISION_V4_NOVAE = "SG161222/Realistic_Vision_V4.0_noVAE"
ANYTHING_FURRY = "stablediffusionapi/anythingfurry"
SD15_DEFAULT_VAE = "stabilityai/sd-vae-ft-mse"

SDXL_BASE_1_0 = "stabilityai/stable-diffusion-xl-base-1.0"

# Diffusers-only subset for sdxl_diffusers (~13–14 GB fp32 weights; not the full ~54 GB repo).
SDXL_DIFFUSERS_ALLOW_PATTERNS: tuple[str, ...] = (
    "model_index.json",
    "scheduler/*",
    "tokenizer/*",
    "tokenizer_2/*",
    "unet/config.json",
    "unet/diffusion_pytorch_model.safetensors",
    "text_encoder/config.json",
    "text_encoder/model.safetensors",
    "text_encoder_2/config.json",
    "text_encoder_2/model.safetensors",
    "vae/config.json",
    "vae/diffusion_pytorch_model.safetensors",
)

Z_IMAGE_TURBO_SDNQ_INT8 = "Disty0/Z-Image-Turbo-SDNQ-int8"
Z_IMAGE_TURBO_MFLUX_4BIT = "filipstrand/Z-Image-Turbo-mflux-4bit"

# SD 1.5 checkpoints that use HOST_SD15 (settings + run dialog LoRA lists).
SD15_LORA_MODEL_KEYS: tuple[str, ...] = (
    REALISTIC_VISION_V4_NOVAE,
    ANYTHING_FURRY,
)

# SDXL 1.0 checkpoints that use HOST_SDXL (settings + run dialog LoRA lists).
SDXL_LORA_MODEL_KEYS: tuple[str, ...] = (
    SDXL_BASE_1_0,
)

LORA_PROBE_MODEL_ORDER: tuple[str, ...] = (
    FLUX1_SCHNELL,
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    Z_IMAGE_TURBO_MFLUX_4BIT,
    REALISTIC_VISION_V4_NOVAE,
    ANYTHING_FURRY,
    SDXL_BASE_1_0,
)

LORA_MODEL_DISPLAY_NAMES: dict[str, str] = {
    FLUX1_SCHNELL: "FLUX.1 Schnell",
    FLUX1_DEV: "FLUX.1 Dev",
    FLUX1_FILL_DEV: "FLUX.1 Fill",
    FLUX2_KLEIN_4B: "FLUX.2 Klein 4B",
    FLUX2_KLEIN_9B: "FLUX.2 Klein 9B",
    FLUX2_KLEIN_9B_KV: "FLUX.2 Klein 9B KV",
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX: "FLUX.2 Klein 9B KV MLX",
    REALISTIC_VISION_V4_NOVAE: "Realistic Vision V4.0",
    ANYTHING_FURRY: "Anything Furry",
    SDXL_BASE_1_0: "SDXL 1.0 Base",
    Z_IMAGE_TURBO_SDNQ_INT8: "Z-Image Turbo",
    Z_IMAGE_TURBO_MFLUX_4BIT: "Z-Image Turbo 4-bit",
}


def lora_model_display_name(hf_model_id: str) -> str:
    return LORA_MODEL_DISPLAY_NAMES.get(hf_model_id, hf_model_id)


def hf_repo_snapshot_allow_patterns(
    pipeline_id: str, repo_id: str
) -> tuple[str, ...] | None:
    """Subset of HF repo files to download for a pipeline (None = full repo)."""
    if pipeline_id == "sdxl_diffusers" and repo_id == SDXL_BASE_1_0:
        return SDXL_DIFFUSERS_ALLOW_PATTERNS
    return None
