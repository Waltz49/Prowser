#!/usr/bin/env python3
"""Create plugin: Expand via local MFLUX FLUX.1 Fill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    copies_slider_block,
    dim_slider_block,
    guidance_slider_block,
    low_ram_bool,
    model_reset_default,
    progressive_images_bool,
    seed_row_block,
    steps_quant_row_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_FILL

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin

HF_MODEL_ID = "black-forest-labs/FLUX.1-Fill-dev"


def flux_fill_expand_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Readable per-model control table for FLUX.1 Fill expand."""
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
        guidance_slider_block(
            values,
            guidance_min=mode.guidance_min,
            guidance_max=mode.guidance_max,
            guidance_default=mode.guidance_default,
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
            progressive_images_bool(values),
        ),
    )


FLUX_FILL_EXPAND_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_fill_expand",
    pipeline_id="mflux_fill_expand",
    display_name=HF_MODEL_ID,
    hf_model_id=HF_MODEL_ID,
    function="expand",
    lora_host_id=HOST_FLUX1_FILL,
    model_comment="High Quality",
    max_generation_dimension=1024,
    field_layout_builder=flux_fill_expand_field_layout,
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "guidance_scale": 30.0,
        "mflux_quantize": 4,
        "seed": 0,
        "random_seed": True,
        "low_ram": True,
        "overlap_percentage": 2,
        "mflux_lora": "none",
    },
)
