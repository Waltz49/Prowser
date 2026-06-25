#!/usr/bin/env python3
"""Create plugins: Edit via local MFLUX FLUX.2 Klein 4B / 9B."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
)
from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    klein_edit_copies_group,
    low_ram_bool,
    mflux_quant_choice_block,
    progressive_images_bool,
    seed_row_block,
    steps_slider_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin

_KLEIN_EDIT_DEFAULTS = {
    "prompt": "",
    "steps": 4,
    "mflux_quantize": 4,
    "seed": 0,
    "random_seed": True,
    "low_ram": True,
    "use_custom_size": False,
    "width": 1024,
    "height": 1024,
    "aspect_ratio_lock": False,
    "aspect_ratio_test": True,
}


def _klein_edit_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Readable per-model control table for FLUX.2 Klein edit."""
    del effective_max_side  # edit has no output dimension fields
    mode = get_pipeline(plugin.pipeline_id)
    model_defaults = plugin.model_defaults
    return (
        FieldSpec(
            key="prompt",
            label=mode.prompt_label,
            kind="text",
            default=values.get("prompt", ""),
            required=mode.prompt_required,
        ),
        seed_row_block(values),
        steps_slider_block(
            values,
            steps_min=mode.steps_min,
            steps_max=mode.steps_max,
            steps_default=mode.steps_default,
            pipeline_id=plugin.pipeline_id,
            model_defaults=model_defaults,
        ),
        mflux_quant_choice_block(
            values, default_q=4, model_defaults=model_defaults
        ),
        klein_edit_copies_group(values, model_defaults=model_defaults),
        bool_run_block(
            FieldSpec(
                key="aspect_ratio_test",
                label="Aspect ratio correction for multiple images",
                kind="bool",
                default=bool(values.get("aspect_ratio_test", True)),
            ),
            low_ram_bool(values, default=True),
            progressive_images_bool(values),
        ),
    )


def flux_klein_4b_edit_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    return _klein_edit_field_layout(plugin, values, effective_max_side)


def flux_klein_9b_edit_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    return _klein_edit_field_layout(plugin, values, effective_max_side)


FLUX_KLEIN_4B_EDIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_4b_edit",
    pipeline_id="mflux_flux2_klein_edit",
    display_name=FLUX2_KLEIN_4B,
    hf_model_id=FLUX2_KLEIN_4B,
    function="edit",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="Medium Quality",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_4b_edit_field_layout,
    model_defaults=_KLEIN_EDIT_DEFAULTS,
)

FLUX_KLEIN_9B_EDIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_9b_edit",
    pipeline_id="mflux_flux2_klein_edit",
    display_name=FLUX2_KLEIN_9B,
    hf_model_id=FLUX2_KLEIN_9B,
    function="edit",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="High Quality, slower than 4B, Low RAM Mode suggested",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_9b_edit_field_layout,
    model_defaults=_KLEIN_EDIT_DEFAULTS,
)

FLUX_KLEIN_9B_KV_EDIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_9b_kv_edit",
    pipeline_id="mflux_flux2_klein_edit",
    display_name=FLUX2_KLEIN_9B_KV,
    hf_model_id=FLUX2_KLEIN_9B_KV,
    function="edit",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="9B KV-cache variant; faster than full 9B, shares 9B LoRAs",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_9b_edit_field_layout,
    model_defaults=_KLEIN_EDIT_DEFAULTS,
)

# Back-compat alias (was flux_klein_edit / flux_klein_4b naming in early wiring).
FLUX_KLEIN_EDIT_PLUGIN = FLUX_KLEIN_4B_EDIT_PLUGIN
