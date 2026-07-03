#!/usr/bin/env python3
"""Expand via FLUX.2 Klein edit (composite + prompt; not true mask fill)."""

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
    model_reset_default,
    seed_row_block,
    steps_quant_row_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin

_KLEIN_EXPAND_DEFAULTS = {
    "prompt": "",
    "width": 1024,
    "height": 1024,
    "steps": 4,
    "mflux_quantize": 4,
    "seed": 0,
    "random_seed": True,
    "low_ram": True,
    "overlap_percentage": 2,
    "mflux_lora": "none",
}


def _klein_expand_field_layout(
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
        FieldSpec(
            key="overlap_percentage",
            label="Overlap %",
            kind="int_slider",
            default=int(
                values.get(
                    "overlap_percentage",
                    model_reset_default(model_defaults, "overlap_percentage", 2),
                )
            ),
            min_value=0,
            max_value=20,
            step=1,
            reset_default=int(
                model_reset_default(model_defaults, "overlap_percentage", 2)
            ),
        ),
        bool_run_block(
            low_ram_bool(values, default=True),
        ),
    )


def _plugin(
    plugin_id: str,
    hf_model_id: str,
    model_comment: str,
) -> ImageGenModelPlugin:
    return ImageGenModelPlugin(
        plugin_id=plugin_id,
        pipeline_id="mflux_flux2_klein_expand",
        display_name=hf_model_id,
        hf_model_id=hf_model_id,
        function="expand",
        lora_host_id=HOST_FLUX2_KLEIN,
        model_comment=model_comment,
        max_generation_dimension=2048,
        field_layout_builder=_klein_expand_field_layout,
        model_defaults=dict(_KLEIN_EXPAND_DEFAULTS),
    )


FLUX_KLEIN_4B_EXPAND_PLUGIN = _plugin(
    "flux_klein_4b_expand",
    FLUX2_KLEIN_4B,
    "Klein edit expand (no mask); faster than Fill",
)
FLUX_KLEIN_9B_EXPAND_PLUGIN = _plugin(
    "flux_klein_9b_expand",
    FLUX2_KLEIN_9B,
    "Klein edit expand (no mask); slower than 4B",
)
FLUX_KLEIN_9B_KV_EXPAND_PLUGIN = _plugin(
    "flux_klein_9b_kv_expand",
    FLUX2_KLEIN_9B_KV,
    "9B KV expand; faster than full 9B",
)
