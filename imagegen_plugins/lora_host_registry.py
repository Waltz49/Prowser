#!/usr/bin/env python3
"""LoRA host registry: model families that share a curated LoRA catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    SD15_LORA_MODEL_KEYS,
    SDXL_LORA_MODEL_KEYS,
    Z_IMAGE_TURBO_MFLUX_4BIT,
)

HOST_FLUX1_T2I = "flux1_t2i"
HOST_FLUX1_FILL = "flux1_fill"
HOST_FLUX2_KLEIN = "flux2_klein"
HOST_SD15 = "sd15"
HOST_SDXL = "sdxl"
HOST_Z_IMAGE_TURBO = "z_image_turbo"


@dataclass(frozen=True)
class LoraHost:
    host_id: str
    display_name: str
    pipeline_ids: Tuple[str, ...]
    probe_targets: Tuple[str, ...]


LORA_HOSTS: Dict[str, LoraHost] = {
    HOST_FLUX1_T2I: LoraHost(
        host_id=HOST_FLUX1_T2I,
        display_name="FLUX.1 Create (Schnell / Dev)",
        pipeline_ids=("flux_schnell_mflux_play",),
        probe_targets=(FLUX1_SCHNELL, FLUX1_DEV),
    ),
    HOST_FLUX1_FILL: LoraHost(
        host_id=HOST_FLUX1_FILL,
        display_name="FLUX.1 Fill (Expand / Infill)",
        pipeline_ids=("mflux_fill_expand", "mflux_fill_infill"),
        probe_targets=(FLUX1_FILL_DEV,),
    ),
    HOST_FLUX2_KLEIN: LoraHost(
        host_id=HOST_FLUX2_KLEIN,
        display_name="FLUX.2 Klein (Create / Edit / Expand)",
        pipeline_ids=(
            "mflux_flux2_klein_create",
            "mflux_flux2_klein_edit",
            "mflux_flux2_klein_expand",
        ),
        probe_targets=(
            FLUX2_KLEIN_4B,
            FLUX2_KLEIN_9B,
            FLUX2_KLEIN_9B_KV,
            SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        ),
    ),
    HOST_SD15: LoraHost(
        host_id=HOST_SD15,
        display_name="SD 1.5 (Create)",
        pipeline_ids=("sd15_diffusers",),
        probe_targets=SD15_LORA_MODEL_KEYS,
    ),
    HOST_SDXL: LoraHost(
        host_id=HOST_SDXL,
        display_name="SDXL 1.0 (Create)",
        pipeline_ids=("sdxl_diffusers",),
        probe_targets=SDXL_LORA_MODEL_KEYS,
    ),
    HOST_Z_IMAGE_TURBO: LoraHost(
        host_id=HOST_Z_IMAGE_TURBO,
        display_name="Z-Image Turbo (Create)",
        pipeline_ids=("mflux_z_image_turbo",),
        probe_targets=(Z_IMAGE_TURBO_MFLUX_4BIT,),
    ),
}

# Settings tab order.
LORA_HOST_ORDER: Tuple[str, ...] = (
    HOST_FLUX1_T2I,
    HOST_FLUX1_FILL,
    HOST_FLUX2_KLEIN,
    HOST_Z_IMAGE_TURBO,
    HOST_SD15,
    HOST_SDXL,
)


_PIPELINE_TO_LORA_HOST: Dict[str, str] = {
    pipeline_id: host.host_id
    for host in LORA_HOSTS.values()
    for pipeline_id in host.pipeline_ids
}


def lora_host_for_pipeline(pipeline_id: str) -> str | None:
    return _PIPELINE_TO_LORA_HOST.get(pipeline_id)
