#!/usr/bin/env python3
"""Create plugin: Infill via local MFLUX FLUX.1 Fill (Pixelmator base + mask)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    copies_slider_block,
    guidance_slider_block,
    low_ram_bool,
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


def flux_fill_infill_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Readable per-model control table for FLUX.1 Fill infill."""
    del effective_max_side  # infill has no output dimension fields
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
        bool_run_block(
            low_ram_bool(values, default=True),
            progressive_images_bool(values),
        ),
    )


FLUX_FILL_INFILL_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_fill_infill",
    pipeline_id="mflux_fill_infill",
    display_name=HF_MODEL_ID,
    hf_model_id=HF_MODEL_ID,
    function="infill",
    lora_host_id=HOST_FLUX1_FILL,
    model_comment="High Quality",
    max_generation_dimension=1024,
    field_layout_builder=flux_fill_infill_field_layout,
    model_defaults={
        "prompt": "",
        "steps": 20,
        "guidance_scale": 30.0,
        "mflux_quantize": 4,
        "seed": 0,
        "random_seed": True,
        "low_ram": True,
        "mflux_lora": "none",
    },
)
