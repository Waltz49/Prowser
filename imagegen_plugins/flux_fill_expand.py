#!/usr/bin/env python3
"""Create plugin: Expand via local MFLUX FLUX.1 Fill."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_FILL

HF_MODEL_ID = "black-forest-labs/FLUX.1-Fill-dev"

FLUX_FILL_EXPAND_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_fill_expand",
    pipeline_id="mflux_fill_expand",
    display_name=HF_MODEL_ID,
    hf_model_id=HF_MODEL_ID,
    function="expand",
    lora_host_id=HOST_FLUX1_FILL,
    model_comment="High Quality",
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "guidance_scale": 30.0,
        "mflux_quantize": 4,
        "seed": 0,
        "random_seed": True,
        "low_ram": True,
        "overlap_percentage": 2,
        "mflux_lora": "none",
    },
)
