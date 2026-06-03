#!/usr/bin/env python3
"""LoRA host registry: model families that share a curated LoRA catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

HOST_FLUX1_T2I = "flux1_t2i"
HOST_FLUX1_FILL = "flux1_fill"
HOST_FLUX2_KLEIN = "flux2_klein"

# Probe keys used by compatibility checker and settings display suffixes.
PROBE_SCHNELL = "schnell"
PROBE_DEV = "dev"
PROBE_FILL = "fill"
PROBE_KLEIN_4B = "klein_4b"
PROBE_KLEIN_9B = "klein_9b"

LORA_PROBE_MODEL_ORDER: Tuple[str, ...] = (
    PROBE_SCHNELL,
    PROBE_DEV,
    PROBE_FILL,
    PROBE_KLEIN_4B,
    PROBE_KLEIN_9B,
)

LORA_MODEL_ABBREV: Dict[str, str] = {
    PROBE_SCHNELL: "Schnell",
    PROBE_DEV: "Dev",
    PROBE_FILL: "Fill",
    PROBE_KLEIN_4B: "Klein 4B",
    PROBE_KLEIN_9B: "Klein 9B",
}


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
        probe_targets=(PROBE_SCHNELL, PROBE_DEV),
    ),
    HOST_FLUX1_FILL: LoraHost(
        host_id=HOST_FLUX1_FILL,
        display_name="FLUX.1 Fill (Expand / Infill)",
        pipeline_ids=("mflux_fill_expand", "mflux_fill_infill"),
        probe_targets=(PROBE_FILL,),
    ),
    HOST_FLUX2_KLEIN: LoraHost(
        host_id=HOST_FLUX2_KLEIN,
        display_name="FLUX.2 Klein (Edit)",
        pipeline_ids=("mflux_flux2_klein_edit",),
        probe_targets=(PROBE_KLEIN_4B, PROBE_KLEIN_9B),
    ),
}

# Settings tab order.
LORA_HOST_ORDER: Tuple[str, ...] = (
    HOST_FLUX1_T2I,
    HOST_FLUX1_FILL,
    HOST_FLUX2_KLEIN,
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
