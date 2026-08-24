#!/usr/bin/env python3
"""Stable Diffusion XL 1.0 base (diffusers StableDiffusionXLPipeline)."""

from __future__ import annotations

from imagegen_plugins.hf_model_ids import SDXL_BASE_1_0
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SDXL
from imagegen_plugins.sd15_plugin_shared import diffusers_t2i_field_layout

SDXL_BASE_1_0_PLUGIN = ImageGenModelPlugin(
    plugin_id="sdxl_base_1_0",
    pipeline_id="sdxl_diffusers",
    display_name="SDXL 1.0 Base",
    hf_model_id=SDXL_BASE_1_0,
    lora_host_id=HOST_SDXL,
    model_comment="SDXL 1.0; 768–896px recommended on 16GB Mac; SDXL LoRAs",
    max_generation_dimension=896,
    field_layout_builder=diffusers_t2i_field_layout,
    model_defaults={
        "prompt": "",
        "negative_prompt": "low quality, blurry, bad anatomy",
        "width": 768,
        "height": 768,
        "steps": 30,
        "guidance_scale": 7.5,
        "seed": 0,
        "random_seed": True,
        "copies": 1,
        "mflux_lora": "none",
    },
)
