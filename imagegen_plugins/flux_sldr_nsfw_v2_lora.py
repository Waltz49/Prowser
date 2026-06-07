#!/usr/bin/env python3
"""Create plugin: FLUX.1 dev + aifeifei798/sldr_flux_nsfw_v2-studio LoRA via MFLUX."""

from imagegen_plugins.hf_model_ids import FLUX1_DEV
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_T2I

FLUX_SLDR_NSFW_V2_LORA_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_sldr_nsfw_v2_lora",
    pipeline_id="flux_schnell_mflux_play",
    display_name=FLUX1_DEV,
    hf_model_id=FLUX1_DEV,
    lora_host_id=HOST_FLUX1_T2I,
    model_comment="High Quality",
    model_defaults={
        "mflux_quantize": 3,
        "guidance_scale": 3.5,
        "steps": 20,
        "width": 1024,
        "height": 1024,
        "seed": 0,
        "random_seed": True,
        "low_ram": False,
        "prompt": "",
        "mflux_lora": "sldr_nsfw_v2",
    },
)
