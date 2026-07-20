#!/usr/bin/env python3
"""Realistic Vision V4.0 noVAE (diffusers Stable Diffusion 1.5)."""

from __future__ import annotations

from imagegen_plugins.hf_model_ids import REALISTIC_VISION_V4_NOVAE, SD15_DEFAULT_VAE
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15
from imagegen_plugins.sd15_plugin_shared import sd15_create_field_layout

REALISTIC_VISION_V4_SD15_PLUGIN = ImageGenModelPlugin(
    plugin_id="realistic_vision_v4_sd15",
    pipeline_id="sd15_diffusers",
    display_name="Realistic Vision V4.0",
    hf_model_id=REALISTIC_VISION_V4_NOVAE,
    lora_host_id=HOST_SD15,
    model_comment="SD 1.5 photorealistic; uses sd-vae-ft-mse (no bundled VAE); SD 1.5 LoRAs",
    max_generation_dimension=768,
    field_layout_builder=sd15_create_field_layout,
    model_defaults={
        "prompt": "",
        "negative_prompt": "",
        "width": 512,
        "height": 512,
        "steps": 36, # was 25
        "guidance_scale": 7.5,
        "seed": 0,
        "random_seed": True,
        "copies": 1,
        "vae_hf_model_id": SD15_DEFAULT_VAE,
        "mflux_lora": "none",
    },
)
