#!/usr/bin/env python3
"""Create plugin: Infill via local MFLUX FLUX.1 Fill (Pixelmator base + mask)."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_FILL

HF_MODEL_ID = "black-forest-labs/FLUX.1-Fill-dev"

FLUX_FILL_INFILL_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_fill_infill",
    pipeline_id="mflux_fill_infill",
    display_name=HF_MODEL_ID,
    hf_model_id=HF_MODEL_ID,
    function="infill",
    lora_host_id=HOST_FLUX1_FILL,
    model_comment="High Quality",
    model_defaults={
        "prompt": "",
        "steps": 20,
        "guidance_scale": 30.0,
        "mflux_quantize": 4,
        "seed": 0,
        "random_seed": True,
        "low_ram": True,
        "mflux_lora": "none",
    },
)
