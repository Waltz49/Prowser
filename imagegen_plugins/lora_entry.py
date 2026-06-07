#!/usr/bin/env python3
"""LoRA catalog entry type and shared constants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from imagegen_plugins.hf_model_ids import FLUX1_DEV

PAPER_CUTOUT_LORA_PATH = (
    Path.home()
    / ".cache"
    / "mflux_loras"
    / "paper-cutout"
    / "Flux_1_Dev_LoRA_Paper-Cutout-Style.safetensors"
)

DEFAULT_CACHE = Path.home() / ".cache" / "image_browser" / "mflux_loras"
_ALT_CACHE = Path.home() / ".cache" / "mflux_loras"

LORA_MIN_STEPS = 2

DEFAULT_ENABLED_LORA_IDS_BY_HOST: dict[str, tuple[str, ...]] = {
    "flux1_t2i": (
        "mspaint1",
        "super_realism",
        "sldr_nsfw_v2",
        "pola_photo_flux",
        "paper_cutout",
    ),
    "flux1_fill": (),
    "flux2_klein": (),
}

# Back-compat alias for migration/tests.
DEFAULT_ENABLED_LORA_IDS: tuple[str, ...] = DEFAULT_ENABLED_LORA_IDS_BY_HOST["flux1_t2i"]


@dataclass(frozen=True)
class FluxLoraEntry:
    host_id: str
    lora_id: str
    display_name: str
    repo_id: str = ""
    filename: str = ""
    scale: float = 1.0
    local_path: Optional[str] = None
    base_hf_model_id: str = FLUX1_DEV
    min_steps: int = LORA_MIN_STEPS
    # True = verified MFLUX; False = known incompatible; None = untested HF entry.
    mflux_compatible: Optional[bool] = None
