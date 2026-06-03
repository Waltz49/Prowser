#!/usr/bin/env python3
"""Create plugins: Edit via local MFLUX FLUX.2 Klein 4B / 9B."""

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN

_KLEIN_EDIT_DEFAULTS = {
    "prompt": "",
    "steps": 4,
    "mflux_quantize": 4,
    "seed": 0,
    "random_seed": True,
    "low_ram": True,
}

FLUX_KLEIN_4B_EDIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_4b_edit",
    pipeline_id="mflux_flux2_klein_edit",
    display_name="black-forest-labs/FLUX.2-klein-4B",
    hf_model_id="black-forest-labs/FLUX.2-klein-4B",
    function="edit",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="Medium Quality",
    model_defaults={
        **_KLEIN_EDIT_DEFAULTS,
        "mflux_model_name": "flux2-klein-4b",
    },
)

FLUX_KLEIN_9B_EDIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_9b_edit",
    pipeline_id="mflux_flux2_klein_edit",
    display_name="black-forest-labs/FLUX.2-klein-9B",
    hf_model_id="black-forest-labs/FLUX.2-klein-9B",
    function="edit",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="High Quality, slower than 4B, Low RAM Mode suggested",
    model_defaults={
        **_KLEIN_EDIT_DEFAULTS,
        "mflux_model_name": "flux2-klein-9b",
    },
)

# Back-compat alias (was flux_klein_edit / flux_klein_4b naming in early wiring).
FLUX_KLEIN_EDIT_PLUGIN = FLUX_KLEIN_4B_EDIT_PLUGIN
