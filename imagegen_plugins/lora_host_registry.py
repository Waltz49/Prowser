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
)

HOST_FLUX1_T2I = "flux1_t2i"
HOST_FLUX1_FILL = "flux1_fill"
HOST_FLUX2_KLEIN = "flux2_klein"
HOST_SD15 = "sd15"


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
}

# Settings tab order.
LORA_HOST_ORDER: Tuple[str, ...] = (
    HOST_FLUX1_T2I,
    HOST_FLUX1_FILL,
    HOST_FLUX2_KLEIN,
    HOST_SD15,
)


def get_lora_host(host_id: str) -> LoraHost | None:
    return LORA_HOSTS.get(host_id)


def lora_host_for_pipeline(pipeline_id: str) -> str | None:
    for host in LORA_HOSTS.values():
        if pipeline_id in host.pipeline_ids:
            return host.host_id
    return None


def lora_hosts_for_settings() -> Tuple[LoraHost, ...]:
    """Hosts shown in Settings → LoRA model-family dropdown."""
    return tuple(LORA_HOSTS[hid] for hid in LORA_HOST_ORDER if hid in LORA_HOSTS)
