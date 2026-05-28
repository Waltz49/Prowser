#!/usr/bin/env python3
"""Create plugin: FLUX.1 dev + aifeifei798/sldr_flux_nsfw_v2-studio LoRA via MFLUX."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

FLUX_SLDR_NSFW_V2_LORA_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_sldr_nsfw_v2_lora",
    pipeline_id="flux_schnell_mflux_play",
    display_name="FLUX.1 Dev",
    hf_model_id="dev",
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
        "mflux_lora": "sldr_nsfw_v2",
        "prompt": "",
    },
)
