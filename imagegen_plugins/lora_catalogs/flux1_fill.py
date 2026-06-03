#!/usr/bin/env python3
"""FLUX.1 Fill (expand/infill) LoRA catalog."""

from __future__ import annotations

from typing import Dict

from imagegen_plugins.lora_catalogs._common import fill_entry
from imagegen_plugins.lora_entry import FluxLoraEntry

FLUX1_FILL_LORAS: Dict[str, FluxLoraEntry] = {
    "omnipaint": fill_entry(
        "omnipaint",
        "OmniPaint",
        "yeates/OmniPaint",
        "weights/omnipaint_insert.safetensors",
        mflux_compatible=True,
    ),
}
