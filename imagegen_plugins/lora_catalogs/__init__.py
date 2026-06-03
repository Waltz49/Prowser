#!/usr/bin/env python3
"""Per-host curated LoRA catalogs."""

from imagegen_plugins.lora_catalogs.flux1_fill import FLUX1_FILL_LORAS
from imagegen_plugins.lora_catalogs.flux1_t2i import FLUX1_T2I_LORAS
from imagegen_plugins.lora_catalogs.flux2_klein import FLUX2_KLEIN_LORAS

__all__ = [
    "FLUX1_FILL_LORAS",
    "FLUX1_T2I_LORAS",
    "FLUX2_KLEIN_LORAS",
]
