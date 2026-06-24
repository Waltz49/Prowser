#!/usr/bin/env python3
"""Local SANA Sprint 0.6B 1024px (diffusers; default generation parameters)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.image_gen_field_blocks import (
    dim_slider_block,
    guidance_slider_block,
    sana_extra_fields,
    seed_row_block,
    steps_slider_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin


def sana_sprint_600m_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Readable per-model control table for SANA Sprint 0.6B."""
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
        guidance_slider_block(
            values,
            guidance_min=mode.guidance_min,
            guidance_max=mode.guidance_max,
            guidance_default=mode.guidance_default,
            model_defaults=model_defaults,
        ),
        *sana_extra_fields(values, model_defaults=model_defaults),
    )


SANA_SPRINT_600M_PLUGIN = ImageGenModelPlugin(
    plugin_id="sana_sprint_600m",
    pipeline_id="sana_sprint_600m",
    display_name="SANA Sprint 0.6B 1024px",
    hf_model_id="Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers",
    model_comment="SLOW and not realistic",
    max_generation_dimension=1024,
    field_layout_builder=sana_sprint_600m_field_layout,
    model_defaults={
        "prompt": "",
        "width": 1024,
        "height": 1024,
        "steps": 2,
        "guidance_scale": 4.5,
        "seed": 0,
        "random_seed": True,
        "use_resolution_binning": True,
        "max_sequence_length": 300,
        "clean_caption": True,
    },
)
