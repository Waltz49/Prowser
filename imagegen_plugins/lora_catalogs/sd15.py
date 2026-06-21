#!/usr/bin/env python3
"""Stable Diffusion 1.5 (diffusers) LoRA catalog."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.hf_model_ids import ANYTHING_FURRY
from imagegen_plugins.lora_catalogs._common import sd15_entry
from imagegen_plugins.lora_entry import FluxLoraEntry

SD15_LORAS: Dict[str, FluxLoraEntry] = {
    "sd15_anime_character": sd15_entry(
        "sd15_anime_character",
        "Anime character",
        "Shion1124/anime-character-lora_v1.5",
        "adapter_model.safetensors",
        scale=0.8,
        trigger_word="anime",
    ),
    "sd15_furry": sd15_entry(
        "sd15_furry",
        "Furry",
        "hank87/furrylora",
        "furry_lora.safetensors",
        scale=0.75,
        trigger_word="furry",
    ),
}
