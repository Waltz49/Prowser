#!/usr/bin/env python3
"""Stable Diffusion XL 1.0 (diffusers) LoRA catalog."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.lora_catalogs._common import sdxl_entry
from imagegen_plugins.lora_entry import FluxLoraEntry

SDXL_LORAS: Dict[str, FluxLoraEntry] = {
    "sdxl_werewolf": sdxl_entry(
        "sdxl_werewolf",
        "Werewolf",
        "RalFinger/werewolf-lora-1-5-sdxl",
        "werewolf-sdxl.safetensors",
        scale=0.8,
        trigger_word="werewolf",
    ),
}
