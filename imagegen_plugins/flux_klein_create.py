#!/usr/bin/env python3
"""Create plugins: text-to-image via local MFLUX FLUX.2 Klein 4B / 9B / 9B KV."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
)
from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    copies_slider_block,
    dim_slider_block,
    low_ram_bool,
    progressive_images_bool,
    seed_row_block,
    steps_quant_row_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin

_KLEIN_CREATE_DEFAULTS = {
    "prompt": "",
    "width": 1024,
    "height": 1024,
    "steps": 4,
    "guidance_scale": 1.0,
    "mflux_quantize": 4,
    "seed": 0,
    "random_seed": True,
    "copies": 1,
    "low_ram": True,
    "show_progressive_images": False,
}


def _klein_create_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    mode = get_pipeline(plugin.pipeline_id)
    model_defaults = plugin.model_defaults
    w_spec, h_spec = dim_slider_block(
        values,
        width_min=mode.width_min,
        height_min=mode.height_min,
        dim_max=effective_max_side,
        dim_step=mode.dim_step,
        model_defaults=model_defaults,
    )
    return (
        FieldSpec(
            key="prompt",
            label=mode.prompt_label,
            kind="text",
            default=values.get("prompt", ""),
            required=mode.prompt_required,
        ),
        w_spec,
        h_spec,
        seed_row_block(values),
        steps_quant_row_block(
            values,
            steps_min=mode.steps_min,
            steps_max=mode.steps_max,
            steps_default=mode.steps_default,
            pipeline_id=plugin.pipeline_id,
            default_q=4,
            model_defaults=model_defaults,
        ),
        copies_slider_block(values, model_defaults=model_defaults),
        bool_run_block(
            low_ram_bool(values, default=True),
            progressive_images_bool(values),
        ),
    )


def flux_klein_4b_create_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    return _klein_create_field_layout(plugin, values, effective_max_side)


def flux_klein_9b_create_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    return _klein_create_field_layout(plugin, values, effective_max_side)


FLUX_KLEIN_4B_CREATE_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_4b_create",
    pipeline_id="mflux_flux2_klein_create",
    display_name=FLUX2_KLEIN_4B,
    hf_model_id=FLUX2_KLEIN_4B,
    function="create",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="Medium Quality",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_4b_create_field_layout,
    model_defaults=_KLEIN_CREATE_DEFAULTS,
)

FLUX_KLEIN_9B_CREATE_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_9b_create",
    pipeline_id="mflux_flux2_klein_create",
    display_name=FLUX2_KLEIN_9B,
    hf_model_id=FLUX2_KLEIN_9B,
    function="create",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="High Quality, slower than 4B, Low RAM Mode suggested",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_9b_create_field_layout,
    model_defaults=_KLEIN_CREATE_DEFAULTS,
)

FLUX_KLEIN_9B_KV_CREATE_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_klein_9b_kv_create",
    pipeline_id="mflux_flux2_klein_create",
    display_name=FLUX2_KLEIN_9B_KV,
    hf_model_id=FLUX2_KLEIN_9B_KV,
    function="create",
    lora_host_id=HOST_FLUX2_KLEIN,
    model_comment="9B KV-cache variant; faster than full 9B, shares 9B LoRAs",
    max_generation_dimension=2048,
    field_layout_builder=flux_klein_9b_create_field_layout,
    model_defaults=_KLEIN_CREATE_DEFAULTS,
)
