#!/usr/bin/env python3
"""Table-driven pipeline modes (shared backends for image generation plugins)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.mflux_lora_presets import (
    coerce_lora_preset_id,
    effective_steps_for_lora,
    lora_choices_for_pipeline,
    lora_preset_min_steps,
)

MFLUX_QUANT_CHOICES = (3, 4, 5, 6, 8)
_COPIES_PIPELINES = frozenset(
    {
        "flux_schnell_mflux_play",
        "mflux_flux2_klein_edit",
        "mflux_fill_expand",
        "mflux_fill_infill",
    }
)
_COPIES_MAX = 200
_PACKAGE_DIR = Path(__file__).resolve().parent

# MFLUX FlowMatchEulerDiscreteScheduler builds timesteps with / (num_steps - 1).
MFLUX_FLOW_MATCH_MIN_STEPS = 2
_MFLUX_PIPELINE_IDS = frozenset(
    {
        "flux_schnell_mflux_play",
        "mflux_fill_expand",
        "mflux_fill_infill",
        "mflux_flux2_klein_edit",
    }
)


@dataclass(frozen=True)
class PipelineMode:
    pipeline_id: str
    worker_script: str  # relative to imagegen_plugins/pipelines/
    steps_min: int = 1
    steps_max: int = 12
    steps_default: int = 4
    guidance_min: float = 0.0
    guidance_max: float = 10.0
    guidance_default: float = 3.5
    width_min: int = 256
    width_max: int = 1440
    height_min: int = 256
    height_max: int = 1440
    dim_step: int = 16
    supports_negative_prompt: bool = False
    supports_progressive_images: bool = False
    prompt_label: str = "Image Prompt"
    prompt_status_label: str = "Prompt:"
    prompt_required: bool = True
    requires_source_image: bool = False
    includes_output_dimensions: bool = True


PIPELINE_MODES: Dict[str, PipelineMode] = {
    "flux_schnell_mflux_play": PipelineMode(
        pipeline_id="flux_schnell_mflux_play",
        worker_script="mflux_schnell.py",
        steps_min=MFLUX_FLOW_MATCH_MIN_STEPS,
        steps_default=4,
        steps_max=30,
        guidance_default=3.5,
        supports_progressive_images=True,
    ),
    "sana_sprint_600m": PipelineMode(
        pipeline_id="sana_sprint_600m",
        worker_script="sana_sprint.py",
        steps_default=2,
        steps_max=50,
        guidance_default=4.5,
        guidance_min=1.0,
        guidance_max=20.0,
        width_min=256,
        width_max=1024,
        height_min=256,
        height_max=1024,
        dim_step=32,
        supports_negative_prompt=False,
        supports_progressive_images=False,
    ),
    "mflux_fill_expand": PipelineMode(
        pipeline_id="mflux_fill_expand",
        worker_script="mflux_fill_expand.py",
        steps_min=8,
        steps_max=30,
        steps_default=20,
        guidance_min=1.0,
        guidance_max=50.0,
        guidance_default=30.0,
        width_min=128,
        width_max=1024,
        height_min=128,
        height_max=1024,
        dim_step=32,
        supports_negative_prompt=False,
        supports_progressive_images=True,
        prompt_label="Outfill prompt",
        prompt_status_label="Outfill:",
        prompt_required=False,
        requires_source_image=True,
    ),
    "mflux_fill_infill": PipelineMode(
        pipeline_id="mflux_fill_infill",
        worker_script="mflux_fill_expand.py",
        steps_min=8,
        steps_max=30,
        steps_default=20,
        guidance_min=1.0,
        guidance_max=50.0,
        guidance_default=30.0,
        supports_negative_prompt=False,
        supports_progressive_images=True,
        prompt_label="Infill prompt",
        prompt_status_label="Infill:",
        prompt_required=False,
        requires_source_image=False,
        includes_output_dimensions=False,
    ),
    "mflux_flux2_klein_edit": PipelineMode(
        pipeline_id="mflux_flux2_klein_edit",
        worker_script="mflux_flux2_klein_edit.py",
        steps_min=MFLUX_FLOW_MATCH_MIN_STEPS,
        steps_max=30,
        steps_default=4,
        guidance_min=1.0,
        guidance_max=1.0,
        guidance_default=1.0,
        supports_negative_prompt=False,
        supports_progressive_images=True,
        prompt_label="Edit prompt",
        prompt_status_label="Prompt:",
        prompt_required=True,
        requires_source_image=True,
        includes_output_dimensions=False,
    ),
}


def get_pipeline(pipeline_id: str) -> PipelineMode:
    mode = PIPELINE_MODES.get(pipeline_id)
    if mode is None:
        raise KeyError(f"Unknown pipeline_id: {pipeline_id}")
    return mode


def align_dims_for_pipeline(pipeline_id: str, width: int, height: int) -> tuple[int, int]:
    """Snap dialog dimensions to pipeline bounds; scale down proportionally when over max."""
    mode = get_pipeline(pipeline_id)
    w, h = int(width), int(height)
    if w > 0 and h > 0:
        scale = min(1.0, mode.width_max / w, mode.height_max / h)
        w = int(w * scale)
        h = int(h * scale)
    if pipeline_id == "flux_schnell_mflux_play":
        from imagegen_plugins.pipelines.mflux_schnell import align_mflux_dims

        return align_mflux_dims(w, h)
    step = int(mode.dim_step or 1)
    w = max(mode.width_min, w - (w % step))
    h = max(mode.height_min, h - (h % step))
    return w, h


def pipeline_is_available(pipeline_id: str) -> bool:
    if pipeline_id == "flux_schnell_mflux_play":
        from imagegen_plugins.pipelines.mflux_schnell import mflux_is_installed

        return mflux_is_installed()
    if pipeline_id == "sana_sprint_600m":
        from imagegen_plugins.pipelines.sana_sprint import diffusers_is_installed

        return diffusers_is_installed()
    if pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        from imagegen_plugins.pipelines.mflux_fill_expand import mflux_is_installed

        return mflux_is_installed()
    if pipeline_id == "mflux_flux2_klein_edit":
        from imagegen_plugins.pipelines.mflux_flux2_klein_edit import mflux_is_installed

        return mflux_is_installed()
    return False


def worker_script_path(pipeline_id: str) -> str:
    mode = get_pipeline(pipeline_id)
    return str(_PACKAGE_DIR / "pipelines" / mode.worker_script)


def resolve_steps_for_run(pipeline_id: str, values: Dict[str, Any]) -> int:
    """Steps sent to the worker after pipeline bounds and LoRA minimums."""
    mode = get_pipeline(pipeline_id)
    steps = int(values.get("steps", mode.steps_default))
    steps = max(mode.steps_min, min(mode.steps_max, steps))
    if pipeline_id == "flux_schnell_mflux_play":
        lora_id = coerce_lora_preset_id(values.get("mflux_lora", "none"))
        steps = effective_steps_for_lora(steps, lora_id, for_fill=False)
        steps = max(mode.steps_min, min(mode.steps_max, steps))
    if pipeline_id in _MFLUX_PIPELINE_IDS:
        steps = max(MFLUX_FLOW_MATCH_MIN_STEPS, steps)
    return steps


def finalize_run_values(pipeline_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Dialog/saved settings aligned with what build_worker_payload will run."""
    out = dict(values)
    out["steps"] = resolve_steps_for_run(pipeline_id, out)
    return out


def merge_defaults(
    pipeline_id: str,
    model_defaults: Dict[str, Any],
    saved: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pipeline bounds + model defaults + per-plugin saved settings."""
    mode = get_pipeline(pipeline_id)
    base: Dict[str, Any] = {
        "prompt": "",
        "negative_prompt": "",
        "steps": mode.steps_default,
        "guidance_scale": mode.guidance_default,
        "mflux_quantize": 3,
        "seed": 0,
        "random_seed": True,
        "copies": 1,
        "low_ram": False,
        "show_progressive_images": False,
        "hf_model_id": "schnell",
        "mflux_lora": "none",
    }
    if mode.includes_output_dimensions:
        base["width"] = 1024
        base["height"] = 1024
        base["aspect_ratio_lock"] = False
    base.update(model_defaults or {})
    if saved:
        base.update(saved)
    if "mflux_lora" in base:
        base["mflux_lora"] = coerce_lora_preset_id(base["mflux_lora"])
    return base


def seed_field_specs(values: Dict[str, Any]) -> List[FieldSpec]:
    """Seed + random seed row; placed after dimension sliders in dialogs."""
    return [
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
        ),
    ]


def field_specs_for_pipeline(
    pipeline_id: str,
    values: Dict[str, Any],
    *,
    plugin_hf_model_id: str = "schnell",
    lora_host_id: Optional[str] = None,
) -> List[FieldSpec]:
    mode = get_pipeline(pipeline_id)
    specs: List[FieldSpec] = [
        FieldSpec(
            key="prompt",
            label=mode.prompt_label,
            kind="text",
            default=values.get("prompt", ""),
            required=mode.prompt_required,
        ),
    ]
    if mode.supports_negative_prompt:
        specs.append(
            FieldSpec(
                key="negative_prompt",
                label="Negative prompt",
                kind="text",
                default=values.get("negative_prompt", ""),
            )
        )
    dim_specs: List[FieldSpec] = []
    if mode.includes_output_dimensions:
        dim_specs.extend(
            [
                FieldSpec(
                    key="width",
                    label="Width",
                    kind="int_slider",
                    default=int(values.get("width", 1024)),
                    min_value=mode.width_min,
                    max_value=mode.width_max,
                    step=mode.dim_step,
                ),
                FieldSpec(
                    key="height",
                    label="Height",
                    kind="int_slider",
                    default=int(values.get("height", 1024)),
                    min_value=mode.height_min,
                    max_value=mode.height_max,
                    step=mode.dim_step,
                ),
            ]
        )
    specs.extend(dim_specs)
    specs.extend(seed_field_specs(values))
    steps_min = mode.steps_min
    steps_default = int(values.get("steps", mode.steps_default))
    if pipeline_id == "flux_schnell_mflux_play":
        lora_id = coerce_lora_preset_id(values.get("mflux_lora", "none"))
        lora_min = lora_preset_min_steps(lora_id)
        if lora_min is not None:
            steps_min = max(steps_min, lora_min)
        steps_default = effective_steps_for_lora(steps_default, lora_id, for_fill=False)
    steps_default = max(steps_min, min(mode.steps_max, steps_default))
    step_specs: List[FieldSpec] = [
        FieldSpec(
            key="steps",
            label="Steps",
            kind="int_slider",
            default=steps_default,
            min_value=steps_min,
            max_value=mode.steps_max,
            step=1,
        ),
    ]
    if pipeline_id != "mflux_flux2_klein_edit":
        step_specs.append(
            FieldSpec(
                key="guidance_scale",
                label="Guidance scale",
                kind="float_slider",
                default=float(values.get("guidance_scale", mode.guidance_default)),
                min_value=mode.guidance_min,
                max_value=mode.guidance_max,
                step=0.1,
            )
        )
    specs.extend(step_specs)
    if lora_host_id:
        from config import get_config

        from imagegen_plugins.lora_catalog import klein_variant_from_values

        lora_choices = lora_choices_for_pipeline(
            pipeline_id,
            plugin_hf_model_id,
            get_config().load_settings(),
            lora_host_id=lora_host_id,
            klein_variant=klein_variant_from_values(values),
        )
        if len(lora_choices) > 1:
            current_lora = coerce_lora_preset_id(values.get("mflux_lora", "none"))
            choice_ids = {c[1] for c in lora_choices}
            if current_lora not in choice_ids:
                current_lora = "none"
            specs.append(
                FieldSpec(
                    key="mflux_lora",
                    label="LoRA",
                    kind="choice",
                    default=current_lora,
                    choices=lora_choices,
                )
            )
    if pipeline_id in (
        "flux_schnell_mflux_play",
        "mflux_fill_expand",
        "mflux_fill_infill",
        "mflux_flux2_klein_edit",
    ):
        default_q = 3 if pipeline_id == "flux_schnell_mflux_play" else 4
        specs.append(
            FieldSpec(
                key="mflux_quantize",
                label="Quantization",
                kind="choice",
                default=int(values.get("mflux_quantize", default_q)),
                choices=MFLUX_QUANT_CHOICES,
            )
        )
    if pipeline_id == "sana_sprint_600m":
        specs.extend(
            [
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
                    default=int(values.get("max_sequence_length", 300)),
                    min_value=77,
                    max_value=512,
                    step=1,
                ),
                FieldSpec(
                    key="clean_caption",
                    label="Clean caption",
                    kind="bool",
                    default=bool(values.get("clean_caption", True)),
                ),
            ]
        )
    if pipeline_id in _COPIES_PIPELINES:
        specs.append(
            FieldSpec(
                key="copies",
                label="Copies",
                kind="int_slider",
                default=int(values.get("copies", 1)),
                min_value=1,
                max_value=_COPIES_MAX,
                step=1,
            )
        )
    if pipeline_id == "flux_schnell_mflux_play":
        specs.append(
            FieldSpec(
                key="low_ram",
                label="Low RAM mode",
                kind="bool",
                default=bool(values.get("low_ram", False)),
            )
        )
    if pipeline_id in ("mflux_fill_expand", "mflux_fill_infill", "mflux_flux2_klein_edit"):
        specs.append(
            FieldSpec(
                key="low_ram",
                label="Low RAM mode",
                kind="bool",
                default=bool(values.get("low_ram", True)),
            )
        )
    if pipeline_id == "mflux_flux2_klein_edit":
        specs.append(
            FieldSpec(
                key="aspect_ratio_test",
                label="Aspect ratio correction for multiple images",
                kind="bool",
                default=bool(values.get("aspect_ratio_test", False)),
            )
        )
        specs.append(
            FieldSpec(
                key="screen_size_experimental",
                label="Screen Size",
                kind="bool",
                default=bool(values.get("screen_size_experimental", False)),
            )
        )
    if pipeline_id == "mflux_fill_expand":
        specs.append(
            FieldSpec(
                key="overlap_percentage",
                label="Overlap %",
                kind="int_slider",
                default=int(values.get("overlap_percentage", 2)),
                min_value=0,
                max_value=20,
                step=1,
            )
        )
    if get_pipeline(pipeline_id).supports_progressive_images:
        specs.append(
            FieldSpec(
                key="show_progressive_images",
                label="Show progressive images",
                kind="bool",
                default=bool(values.get("show_progressive_images", False)),
            )
        )
    return specs


def menu_label_with_quant(display_name: str, saved: Dict[str, Any]) -> str:
    """Substitute Q{n} in display name from saved mflux_quantize."""
    q = saved.get("mflux_quantize")
    if q is not None:
        try:
            return re.sub(r"Q\d+", f"Q{int(q)}", display_name, count=1)
        except (TypeError, ValueError):
            pass
    return display_name


def build_worker_payload(
    pipeline_id: str,
    values: Dict[str, Any],
    output_path: str,
    hf_model_id: str,
) -> Dict[str, Any]:
    merged = finalize_run_values(pipeline_id, values)
    merged["pipeline_id"] = pipeline_id
    merged["output_path"] = output_path
    merged["hf_model_id"] = hf_model_id
    if pipeline_id in ("flux_schnell_mflux_play", "mflux_fill_expand", "mflux_fill_infill"):
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        merged.pop("copies", None)
        apply_lora_to_mflux_payload(
            merged,
            for_fill=(pipeline_id in ("mflux_fill_expand", "mflux_fill_infill")),
        )
    if pipeline_id == "mflux_flux2_klein_edit":
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        apply_lora_to_mflux_payload(merged, for_fill=False, for_klein=True)
        source_paths = resolve_source_image_paths(merged)
        if source_paths:
            merged["source_image_paths"] = source_paths
            merged["source_image_path"] = source_paths[0]
            pad_temps: list[str] = []
            if merged.get("screen_size_experimental"):
                from imagegen_plugins.edit_aspect_pad import (
                    SCREEN_SIZE_EXPERIMENTAL_PROMPT_SUFFIX,
                    generator_paths_with_screen_size_expansion,
                )

                source_paths, screen_temps = generator_paths_with_screen_size_expansion(
                    source_paths
                )
                pad_temps.extend(screen_temps)
                prompt = str(merged.get("prompt") or "")
                merged["prompt"] = prompt + SCREEN_SIZE_EXPERIMENTAL_PROMPT_SUFFIX
            if merged.get("aspect_ratio_test"):
                from imagegen_plugins.edit_aspect_pad import (
                    generator_paths_with_aspect_padding,
                )

                gen_paths, aspect_temps = generator_paths_with_aspect_padding(
                    source_paths
                )
                source_paths = gen_paths
                pad_temps.extend(aspect_temps)
            merged["source_image_paths"] = source_paths
            merged["source_image_path"] = source_paths[0]
            if pad_temps:
                merged["_aspect_pad_temp_paths"] = pad_temps
        merged.pop("width", None)
        merged.pop("height", None)
    merged.pop("aspect_ratio_lock", None)
    merged.pop("_pixelmator_batch_dir", None)
    merged.pop("use_last_generated_image", None)
    merged.pop("aspect_ratio_test", None)
    merged.pop("screen_size_experimental", None)
    return merged
