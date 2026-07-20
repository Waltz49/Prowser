#!/usr/bin/env python3
"""Anything Furry SD 1.5 (diffusers; anime/furry illustration base)."""

from __future__ import annotations

from imagegen_plugins.hf_model_ids import ANYTHING_FURRY
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15
from imagegen_plugins.sd15_plugin_shared import sd15_create_field_layout

ANYTHING_FURRY_SD15_PLUGIN = ImageGenModelPlugin(
    plugin_id="anything_furry_sd15",
    pipeline_id="sd15_diffusers",
    display_name="Anything Furry",
    hf_model_id=ANYTHING_FURRY,
    lora_host_id=HOST_SD15,
    model_comment="SD 1.5 anime/furry illustration; bundled VAE; anime & furry LoRAs",
    max_generation_dimension=768,
    field_layout_builder=sd15_create_field_layout,
    model_defaults={
        "prompt": "",
        "negative_prompt": "low quality, blurry, bad anatomy",
        "width": 512,
        "height": 512,
        "steps": 36, # was 25
        "guidance_scale": 7.0,
        "seed": 0,
        "random_seed": True,
        "copies": 1,
        "vae_hf_model_id": "",
        "mflux_lora": "none",
    },
)
