#!/usr/bin/env python3
"""Shared Create-dialog field layout for SD 1.5 diffusers plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.image_gen_field_blocks import (
    copies_slider_block,
    dim_slider_block,
    guidance_slider_block,
    seed_row_block,
    steps_slider_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin


def sd15_create_field_layout(
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
        FieldSpec(
            key="negative_prompt",
            label="Negative prompt",
            kind="text",
            default=values.get("negative_prompt", ""),
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
        guidance_slider_block(
            values,
            guidance_min=mode.guidance_min,
            guidance_max=mode.guidance_max,
            guidance_default=mode.guidance_default,
            model_defaults=model_defaults,
        ),
        copies_slider_block(values, model_defaults=model_defaults),
    )
