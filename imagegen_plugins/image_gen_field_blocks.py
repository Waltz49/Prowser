#!/usr/bin/env python3
"""Reusable field/group snippets for per-plugin layout tables."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from imagegen_plugins.image_gen_fields import FieldGroup, FieldNode, FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import MFLUX_FLOW_MATCH_MIN_STEPS, MFLUX_QUANT_CHOICES
from imagegen_plugins.mflux_lora_presets import (
    coerce_lora_preset_id,
    effective_steps_for_lora,
    lora_preset_min_steps,
)


def model_reset_default(
    model_defaults: Optional[dict[str, Any]],
    key: str,
    fallback: Any,
) -> Any:
    """Plugin factory default for a field reset target."""
    if model_defaults and key in model_defaults:
        return model_defaults[key]
    return fallback


def seed_row_block(values: dict[str, Any]) -> FieldGroup:
    return FieldGroup(
        layout="seed_row",
        children=(
            FieldSpec(
                key="seed",
                label="Seed",
                kind="seed",
                default=int(values.get("seed", 0)),
            ),
            FieldSpec(
                key="random_seed",
                label="Random seed",
                kind="bool",
                default=bool(values.get("random_seed", True)),
                bool_label_override="Randomize",
            ),
        ),
    )


def dim_slider_block(
    values: dict[str, Any],
    *,
    width_min: int,
    height_min: int,
    dim_max: int,
    dim_step: int,
    model_defaults: Optional[dict[str, Any]] = None,
) -> Tuple[FieldNode, FieldNode]:
    width_reset = int(model_reset_default(model_defaults, "width", 1024))
    height_reset = int(model_reset_default(model_defaults, "height", 1024))
    return (
        FieldSpec(
            key="width",
            label="Width",
            kind="int_slider",
            default=int(values.get("width", width_reset)),
            min_value=width_min,
            max_value=dim_max,
            step=dim_step,
            reset_default=width_reset,
        ),
        FieldSpec(
            key="height",
            label="Height",
            kind="int_slider",
            default=int(values.get("height", height_reset)),
            min_value=height_min,
            max_value=dim_max,
            step=dim_step,
            reset_default=height_reset,
        ),
    )


def steps_slider_block(
    values: dict[str, Any],
    *,
    steps_min: int,
    steps_max: int,
    steps_default: int,
    pipeline_id: str,
    model_defaults: Optional[dict[str, Any]] = None,
) -> FieldSpec:
    lo = steps_min
    lora_id = None
    if pipeline_id == "flux_schnell_mflux_play":
        lora_id = coerce_lora_preset_id(values.get("mflux_lora", "none"))
        lora_min = lora_preset_min_steps(lora_id)
        if lora_min is not None:
            lo = max(lo, lora_min)
    default = int(values.get("steps", steps_default))
    if lora_id is not None:
        default = effective_steps_for_lora(default, lora_id, for_fill=False)
    default = max(lo, min(steps_max, default))
    reset_default = int(
        model_reset_default(model_defaults, "steps", steps_default)
    )
    reset_default = max(lo, min(steps_max, reset_default))
    if lora_id is not None:
        reset_default = effective_steps_for_lora(
            reset_default, lora_id, for_fill=False
        )
        reset_default = max(lo, min(steps_max, reset_default))
    return FieldSpec(
        key="steps",
        label="Steps",
        kind="int_slider",
        default=default,
        min_value=lo,
        max_value=steps_max,
        step=1,
        reset_default=reset_default,
    )


def guidance_slider_block(
    values: dict[str, Any],
    *,
    guidance_min: float,
    guidance_max: float,
    guidance_default: float,
    model_defaults: Optional[dict[str, Any]] = None,
) -> FieldSpec:
    reset_default = float(
        model_reset_default(model_defaults, "guidance_scale", guidance_default)
    )
    return FieldSpec(
        key="guidance_scale",
        label="Guidance scale",
        kind="float_slider",
        default=float(values.get("guidance_scale", reset_default)),
        min_value=guidance_min,
        max_value=guidance_max,
        step=0.1,
        reset_default=reset_default,
    )


def mflux_quant_choice_block(
    values: dict[str, Any],
    *,
    default_q: int,
    model_defaults: Optional[dict[str, Any]] = None,
) -> FieldSpec:
    reset_default = int(
        model_reset_default(model_defaults, "mflux_quantize", default_q)
    )
    return FieldSpec(
        key="mflux_quantize",
        label="Quantization",
        kind="choice",
        default=int(values.get("mflux_quantize", reset_default)),
        choices=MFLUX_QUANT_CHOICES,
        reset_default=reset_default,
    )


def steps_quant_row_block(
    values: dict[str, Any],
    *,
    steps_min: int,
    steps_max: int,
    steps_default: int,
    pipeline_id: str,
    default_q: int,
    model_defaults: Optional[dict[str, Any]] = None,
    include_quant: bool = True,
) -> FieldGroup:
    """Steps slider and optional MFLUX quantization on one half-column row."""
    children: list[FieldNode] = [
        steps_slider_block(
            values,
            steps_min=steps_min,
            steps_max=steps_max,
            steps_default=steps_default,
            pipeline_id=pipeline_id,
            model_defaults=model_defaults,
        ),
    ]
    if include_quant:
        children.append(
            mflux_quant_choice_block(
                values, default_q=default_q, model_defaults=model_defaults
            )
        )
    return FieldGroup(layout="steps_quant_row", children=tuple(children))


def copies_slider_block(
    values: dict[str, Any],
    *,
    copies_max: int = 30,
    model_defaults: Optional[dict[str, Any]] = None,
) -> FieldSpec:
    reset_default = int(model_reset_default(model_defaults, "copies", 1))
    return FieldSpec(
        key="copies",
        label="Copies",
        kind="int_slider",
        default=int(values.get("copies", reset_default)),
        min_value=1,
        max_value=copies_max,
        step=1,
        reset_default=reset_default,
    )


def klein_edit_copies_group(
    values: dict[str, Any],
    *,
    copies_max: int = 30,
    model_defaults: Optional[dict[str, Any]] = None,
) -> FieldGroup:
    """Copies slider with Refinement checkbox (edit-only)."""
    return FieldGroup(
        layout="labeled",
        label="Copies",
        children=(
            copies_slider_block(
                values, copies_max=copies_max, model_defaults=model_defaults
            ),
            FieldSpec(
                key="series_refinement",
                label="Refinement",
                kind="bool",
                default=bool(values.get("series_refinement", False)),
            ),
        ),
    )


def bool_run_block(*specs: FieldSpec) -> FieldGroup:
    return FieldGroup(layout="bool_run", children=specs)


def progressive_images_bool(values: dict[str, Any]) -> FieldSpec:
    return FieldSpec(
        key="show_progressive_images",
        label="Show intermediate images",
        kind="bool",
        default=bool(values.get("show_progressive_images", False)),
    )


def low_ram_bool(values: dict[str, Any], *, default: bool) -> FieldSpec:
    return FieldSpec(
        key="low_ram",
        label="Low RAM mode",
        kind="bool",
        default=bool(values.get("low_ram", default)),
    )


def sana_extra_fields(
    values: dict[str, Any],
    *,
    model_defaults: Optional[dict[str, Any]] = None,
) -> Tuple[FieldNode, ...]:
    max_seq_reset = int(
        model_reset_default(model_defaults, "max_sequence_length", 300)
    )
    return (
        FieldSpec(
            key="use_resolution_binning",
            label="Resolution binning",
            kind="bool",
            default=bool(values.get("use_resolution_binning", True)),
        ),
        FieldSpec(
            key="max_sequence_length",
            label="Max sequence length",
            kind="int_slider",
            default=int(values.get("max_sequence_length", max_seq_reset)),
            min_value=77,
            max_value=512,
            step=1,
            reset_default=max_seq_reset,
        ),
        FieldSpec(
            key="clean_caption",
            label="Clean caption",
            kind="bool",
            default=bool(values.get("clean_caption", True)),
        ),
    )


MFLUX_STEPS_MIN = MFLUX_FLOW_MATCH_MIN_STEPS
