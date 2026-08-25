#!/usr/bin/env python3
"""Z-Image-Turbo MFLUX 4-bit (pre-quantized; LoRA support; 16 GB friendly)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.hf_model_ids import Z_IMAGE_TURBO_MFLUX_4BIT
from imagegen_plugins.image_gen_field_blocks import (
    copies_slider_block,
    dim_slider_block,
    seed_row_block,
    steps_slider_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_Z_IMAGE_TURBO

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin


def z_image_turbo_mflux_field_layout(
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
        steps_slider_block(
            values,
            steps_min=mode.steps_min,
            steps_max=mode.steps_max,
            steps_default=mode.steps_default,
            pipeline_id=plugin.pipeline_id,
            model_defaults=model_defaults,
        ),
        copies_slider_block(values, model_defaults=model_defaults),
    )


Z_IMAGE_TURBO_MFLUX_4BIT_PLUGIN = ImageGenModelPlugin(
    plugin_id="z_image_turbo_mflux_4bit",
    pipeline_id="mflux_z_image_turbo",
    display_name="Z-Image Turbo (4-bit)",
    hf_model_id=Z_IMAGE_TURBO_MFLUX_4BIT,
    lora_host_id=HOST_Z_IMAGE_TURBO,
    model_comment="Fast, photorealistic, LoRA support, Low RAM suggested",
    max_generation_dimension=1440,
    field_layout_builder=z_image_turbo_mflux_field_layout,
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 9,
        "seed": 0,
        "random_seed": True,
        "copies": 1,
        "mflux_quantize": 4,
    },
)
