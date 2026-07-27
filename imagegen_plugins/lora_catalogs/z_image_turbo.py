#!/usr/bin/env python3
"""Z-Image Turbo (MFLUX 4-bit) LoRA catalog."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.lora_catalogs._common import z_image_turbo_entry
from imagegen_plugins.lora_entry import FluxLoraEntry

Z_IMAGE_TURBO_LORAS: Dict[str, FluxLoraEntry] = {
    "z_childrens_drawings": z_image_turbo_entry(
        "z_childrens_drawings",
        "Children's drawings",
        "ostris/z_image_turbo_childrens_drawings",
        "z_image_turbo_childrens_drawings.safetensors",
        scale=0.8,
    ),
    "z_technically_color": z_image_turbo_entry(
        "z_technically_color",
        "Technically Color",
        "renderartist/Technically-Color-Z-Image-Turbo",
        "Technically_Color_Z_Image_Turbo_v1_renderartist_2000.safetensors",
        scale=0.5,
        trigger_word="t3chnic4lly",
    ),
    "z_classic_painting": z_image_turbo_entry(
        "z_classic_painting",
        "Classic painting",
        "renderartist/Classic-Painting-Z-Image-Turbo-LoRA",
        "Classic_Painting_Z_Image_Turbo_v1_renderartist_1750.safetensors",
        scale=0.8,
    ),
}
