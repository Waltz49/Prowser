#!/usr/bin/env python3
"""First model plugin: FLUX.1 Schnell MFLUX (default quant 3)."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_T2I

FLUX_SCHNELL_MFLUX_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_schnell_mflux",
    pipeline_id="flux_schnell_mflux_play",
    display_name="FLUX.1 Schnell MFLUX Q3",
    hf_model_id="schnell",
    lora_host_id=HOST_FLUX1_T2I,
    model_comment="High Quality, Low RAM Mode suggested",
    model_defaults={
        "mflux_quantize": 3,
        "guidance_scale": 3.5,
        "steps": 4,
        "width": 1024,
        "height": 1024,
        "seed": 0,
        "random_seed": True,
        "low_ram": False,
        "prompt": "",
    },
)
