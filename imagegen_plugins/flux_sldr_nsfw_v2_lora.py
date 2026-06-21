#!/usr/bin/env python3
"""Create plugin: FLUX.1 dev + aifeifei798/sldr_flux_nsfw_v2-studio LoRA via MFLUX."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.hf_model_ids import FLUX1_DEV
from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    copies_slider_block,
    dim_slider_block,
    guidance_slider_block,
    low_ram_bool,
    mflux_quant_choice_block,
    progressive_images_bool,
    seed_row_block,
    steps_slider_block,
)
from imagegen_plugins.image_gen_fields import FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX1_T2I

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin


def flux_sldr_nsfw_v2_lora_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Readable per-model control table for FLUX.1 Dev + SLDR NSFW v2 LoRA."""
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
        mflux_quant_choice_block(
            values, default_q=3, model_defaults=model_defaults
        ),
        copies_slider_block(values, model_defaults=model_defaults),
        bool_run_block(
            low_ram_bool(values, default=False),
            progressive_images_bool(values),
        ),
    )


FLUX_SLDR_NSFW_V2_LORA_PLUGIN = ImageGenModelPlugin(
    plugin_id="flux_sldr_nsfw_v2_lora",
    pipeline_id="flux_schnell_mflux_play",
    display_name=FLUX1_DEV,
    hf_model_id=FLUX1_DEV,
    lora_host_id=HOST_FLUX1_T2I,
    model_comment="High Quality",
    max_generation_dimension=1440,
    field_layout_builder=flux_sldr_nsfw_v2_lora_field_layout,
    model_defaults={
        "mflux_quantize": 3,
        "guidance_scale": 3.5,
        "steps": 20,
        "width": 1024,
        "height": 1024,
        "seed": 0,
        "random_seed": True,
        "low_ram": False,
        "prompt": "",
        "mflux_lora": "sldr_nsfw_v2",
    },
)
