#!/usr/bin/env python3
"""Local SANA Sprint 0.6B 1024px (diffusers; matches testchat gm model 19 defaults)."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

SANA_SPRINT_600M_PLUGIN = ImageGenModelPlugin(
    plugin_id="sana_sprint_600m",
    pipeline_id="sana_sprint_600m",
    display_name="SANA Sprint 0.6B 1024px",
    hf_model_id="Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
    model_comment="SLOW and not realistic",
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 2,
        "guidance_scale": 4.5,
        "seed": 0,
        "random_seed": True,
        "use_resolution_binning": True,
        "max_sequence_length": 300,
        "clean_caption": True,
    },
)
