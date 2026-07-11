#!/usr/bin/env python3
"""SceneWorks pre-quantized MLX FLUX.2 Klein 9B KV (ungated HF re-host)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from imagegen_plugins.hf_model_ids import SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX
from imagegen_plugins.image_gen_field_blocks import (
    bool_run_block,
    copies_slider_block,
    dim_slider_block,
    klein_edit_copies_group,
    low_ram_bool,
    model_reset_default,
    seed_row_block,
    steps_quant_row_block,
)
from imagegen_plugins.image_gen_fields import FieldGroup, FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN
from imagegen_plugins.sceneworks_klein_mlx import DEFAULT_MLX_TIER, MLX_TIER_CHOICES

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin as _Plugin

_SCENEWORKS_COMMENT = (
    "Ungated SceneWorks MLX Q4/Q8/BF16 tiers; ~22 GB Q4 download; "
    "16 GB Macs: use Q4 + Low RAM, expect tight memory"
)

_SCENEWORKS_CREATE_DEFAULTS = {
    "prompt": "",
    "width": 1024,
    "height": 1024,
    "steps": 4,
    "guidance_scale": 1.0,
    "mlx_tier": DEFAULT_MLX_TIER,
    "seed": 0,
    "random_seed": True,
    "copies": 1,
    "low_ram": True,
}

_SCENEWORKS_EDIT_DEFAULTS = {
    "prompt": "",
    "steps": 4,
    "mlx_tier": DEFAULT_MLX_TIER,
    "seed": 0,
    "random_seed": True,
    "low_ram": True,
    "use_custom_size": False,
    "width": 1024,
    "height": 1024,
    "aspect_ratio_lock": False,
    "aspect_ratio_test": True,
}

_SCENEWORKS_EXPAND_DEFAULTS = {
    "prompt": "",
    "width": 1024,
    "height": 1024,
    "steps": 4,
    "mlx_tier": DEFAULT_MLX_TIER,
    "seed": 0,
    "random_seed": True,
    "low_ram": True,
    "overlap_percentage": 2,
    "mflux_lora": "none",
}


def _mlx_tier_choice_block(
    values: dict[str, Any],
    *,
    model_defaults: dict[str, Any] | None,
) -> FieldSpec:
    reset_default = str(
        model_reset_default(model_defaults, "mlx_tier", DEFAULT_MLX_TIER)
    )
    return FieldSpec(
        key="mlx_tier",
        label="MLX tier",
        kind="choice",
        default=str(values.get("mlx_tier", reset_default)),
        choices=MLX_TIER_CHOICES,
        reset_default=reset_default,
    )


def _sceneworks_steps_tier_row(
    plugin: "_Plugin",
    values: dict[str, Any],
    *,
    model_defaults: dict[str, Any] | None,
) -> FieldGroup:
    mode = get_pipeline(plugin.pipeline_id)
    return FieldGroup(
        layout="steps_quant_row",
        children=(
            steps_quant_row_block(
                values,
                steps_min=mode.steps_min,
                steps_max=mode.steps_max,
                steps_default=mode.steps_default,
                pipeline_id=plugin.pipeline_id,
                default_q=4,
                model_defaults=model_defaults,
                include_quant=False,
            ).children[0],
            _mlx_tier_choice_block(values, model_defaults=model_defaults),
        ),
    )


def sceneworks_klein_create_field_layout(
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
        _sceneworks_steps_tier_row(plugin, values, model_defaults=model_defaults),
        copies_slider_block(values, model_defaults=model_defaults),
        bool_run_block(
            low_ram_bool(values, default=True),
        ),
    )


def sceneworks_klein_edit_field_layout(
    plugin: "_Plugin",
    values: dict[str, Any],
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    del effective_max_side
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
        _sceneworks_steps_tier_row(plugin, values, model_defaults=model_defaults),
        klein_edit_copies_group(values, model_defaults=model_defaults),
        bool_run_block(
            FieldSpec(
                key="aspect_ratio_test",
                label="Aspect ratio correction for multiple images",
                kind="bool",
                default=bool(values.get("aspect_ratio_test", True)),
            ),
            low_ram_bool(values, default=True),
        ),
    )


def sceneworks_klein_expand_field_layout(
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
        _sceneworks_steps_tier_row(plugin, values, model_defaults=model_defaults),
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
    *,
    function: str,
    pipeline_id: str,
    field_layout_builder,
    model_defaults: dict[str, Any],
) -> ImageGenModelPlugin:
    return ImageGenModelPlugin(
        plugin_id=plugin_id,
        pipeline_id=pipeline_id,
        display_name=SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        hf_model_id=SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        function=function,
        lora_host_id=HOST_FLUX2_KLEIN,
        model_comment=_SCENEWORKS_COMMENT,
        max_generation_dimension=2048,
        field_layout_builder=field_layout_builder,
        model_defaults=model_defaults,
        quantize_status_key="mlx_tier",
    )


SCENEWORKS_KLEIN_9B_KV_MLX_CREATE_PLUGIN = _plugin(
    "sceneworks_klein_9b_kv_mlx_create",
    function="create",
    pipeline_id="mflux_flux2_klein_create",
    field_layout_builder=sceneworks_klein_create_field_layout,
    model_defaults=dict(_SCENEWORKS_CREATE_DEFAULTS),
)

SCENEWORKS_KLEIN_9B_KV_MLX_EDIT_PLUGIN = _plugin(
    "sceneworks_klein_9b_kv_mlx_edit",
    function="edit",
    pipeline_id="mflux_flux2_klein_edit",
    field_layout_builder=sceneworks_klein_edit_field_layout,
    model_defaults=dict(_SCENEWORKS_EDIT_DEFAULTS),
)

SCENEWORKS_KLEIN_9B_KV_MLX_EXPAND_PLUGIN = _plugin(
    "sceneworks_klein_9b_kv_mlx_expand",
    function="expand",
    pipeline_id="mflux_flux2_klein_expand",
    field_layout_builder=sceneworks_klein_expand_field_layout,
    model_defaults=dict(_SCENEWORKS_EXPAND_DEFAULTS),
)
