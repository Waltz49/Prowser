#!/usr/bin/env python3
"""Table-driven pipeline modes (shared backends for image generation plugins)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from imagegen_plugins.hf_model_ids import FLUX1_SCHNELL
from imagegen_plugins.mflux_lora_presets import (
    coerce_lora_preset_id,
    effective_steps_for_lora,
    effective_steps_for_lora_stack,
    lora_preset_min_steps,
    lora_stack_min_steps,
    normalize_lora_stack_from_values,
)

MFLUX_QUANT_CHOICES = (3, 4, 5, 6, 8)
_PACKAGE_DIR = Path(__file__).resolve().parent

# MFLUX FlowMatchEulerDiscreteScheduler builds timesteps with / (num_steps - 1).
MFLUX_FLOW_MATCH_MIN_STEPS = 2
_MFLUX_PIPELINE_IDS = frozenset(
    {
        "flux_schnell_mflux_play",
        "mflux_fill_expand",
        "mflux_fill_infill",
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    }
)

_KLEIN_EXPAND_PROMPT_PREFIX = "Expand this image.\n"


def klein_expand_prompt(user_prompt: str) -> str:
    text = (user_prompt or "").strip()
    if text:
        return _KLEIN_EXPAND_PROMPT_PREFIX + text
    return _KLEIN_EXPAND_PROMPT_PREFIX.rstrip("\n")


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
    "z_image_turbo_sdnq": PipelineMode(
        pipeline_id="z_image_turbo_sdnq",
        worker_script="z_image_turbo.py",
        steps_default=9,
        steps_max=20,
        guidance_min=0.0,
        guidance_max=0.0,
        guidance_default=0.0,
        width_min=256,
        width_max=1024,
        height_min=256,
        height_max=1024,
        dim_step=16,
        supports_negative_prompt=False,
        supports_progressive_images=False,
    ),
    "sd15_diffusers": PipelineMode(
        pipeline_id="sd15_diffusers",
        worker_script="sd15_diffusers.py",
        steps_default=25,
        steps_max=50,
        guidance_default=7.5,
        guidance_min=1.0,
        guidance_max=20.0,
        width_min=256,
        width_max=768,
        height_min=256,
        height_max=768,
        dim_step=8,
        supports_negative_prompt=True,
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
    "mflux_flux2_klein_create": PipelineMode(
        pipeline_id="mflux_flux2_klein_create",
        worker_script="mflux_flux2_klein_create.py",
        steps_min=MFLUX_FLOW_MATCH_MIN_STEPS,
        steps_max=30,
        steps_default=4,
        guidance_min=1.0,
        guidance_max=1.0,
        guidance_default=1.0,
        width_min=256,
        width_max=2048,
        height_min=256,
        height_max=2048,
        dim_step=16,
        supports_negative_prompt=False,
        supports_progressive_images=True,
        prompt_required=True,
        requires_source_image=False,
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
    "mflux_flux2_klein_expand": PipelineMode(
        pipeline_id="mflux_flux2_klein_expand",
        worker_script="mflux_flux2_klein_edit.py",
        steps_min=MFLUX_FLOW_MATCH_MIN_STEPS,
        steps_max=30,
        steps_default=4,
        guidance_min=1.0,
        guidance_max=1.0,
        guidance_default=1.0,
        width_min=256,
        width_max=2048,
        height_min=256,
        height_max=2048,
        dim_step=16,
        supports_negative_prompt=False,
        supports_progressive_images=True,
        prompt_label="Outfill prompt",
        prompt_status_label="Outfill:",
        prompt_required=False,
        requires_source_image=True,
    ),
}


def get_pipeline(pipeline_id: str) -> PipelineMode:
    mode = PIPELINE_MODES.get(pipeline_id)
    if mode is None:
        raise KeyError(f"Unknown pipeline_id: {pipeline_id}")
    return mode


def align_dims_for_pipeline(
    pipeline_id: str,
    width: int,
    height: int,
    *,
    effective_max_side: int,
) -> tuple[int, int]:
    """Snap dialog dimensions to pipeline bounds; scale down proportionally when over max."""
    mode = get_pipeline(pipeline_id)
    w, h = int(width), int(height)
    max_side = int(effective_max_side)
    if w > 0 and h > 0 and max_side > 0:
        scale = min(1.0, max_side / w, max_side / h)
        w = int(w * scale)
        h = int(h * scale)
    if pipeline_id == "flux_schnell_mflux_play":
        from imagegen_plugins.pipelines.mflux_schnell import align_mflux_dims

        return align_mflux_dims(w, h, max_side=max_side)
    if pipeline_id in ("mflux_flux2_klein_create", "mflux_flux2_klein_expand"):
        from imagegen_plugins.pipelines.mflux_flux2_klein_create import (
            align_mflux_flux2_klein_dims,
        )

        return align_mflux_flux2_klein_dims(w, h, max_side=max_side)
    if pipeline_id == "sd15_diffusers":
        from imagegen_plugins.pipelines.sd15_diffusers import align_sd15_dims

        return align_sd15_dims(w, h, max_side=max_side)
    if pipeline_id == "z_image_turbo_sdnq":
        from imagegen_plugins.pipelines.z_image_turbo import align_z_image_dims

        return align_z_image_dims(w, h, max_side=max_side)
    step = int(mode.dim_step or 1)
    w = max(mode.width_min, w - (w % step))
    h = max(mode.height_min, h - (h % step))
    return w, h


def clamp_output_dims_in_values(
    pipeline_id: str,
    values: Dict[str, Any],
    *,
    effective_max_side: int,
) -> Dict[str, Any]:
    """Scale width/height down together when either edge exceeds effective max."""
    mode = get_pipeline(pipeline_id)
    if not mode.includes_output_dimensions:
        return values
    out = dict(values)
    try:
        w = int(out.get("width", 1024))
        h = int(out.get("height", 1024))
    except (TypeError, ValueError):
        return values
    w, h = align_dims_for_pipeline(
        pipeline_id,
        w,
        h,
        effective_max_side=effective_max_side,
    )
    out["width"] = w
    out["height"] = h
    return out


def generation_status_display_size(
    pipeline_id: str,
    values: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
    *,
    effective_max_side: int,
) -> Optional[tuple[int, int]]:
    """Output dimensions shown in job control / queue (matches worker target size)."""
    merged = dict(values)
    if payload:
        merged.update(payload)
    max_side = int(merged.get("max_generation_dimension") or effective_max_side)

    if pipeline_id == "mflux_flux2_klein_edit":
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths
        from imagegen_plugins.outpaint_mask import fit_edit_output_dims

        if merged.get("use_custom_size"):
            try:
                w = int(merged.get("width", 0))
                h = int(merged.get("height", 0))
            except (TypeError, ValueError):
                return None
            if w <= 0 or h <= 0:
                return None
            return fit_edit_output_dims(w, h, max_side=max_side)
        paths = resolve_source_image_paths(merged)
        if not paths:
            return None
        from PIL import Image

        with Image.open(paths[0]) as image:
            src_w, src_h = image.size
        return fit_edit_output_dims(src_w, src_h, max_side=max_side)

    if pipeline_id == "mflux_fill_infill":
        base_path = str(merged.get("pixelmator_base_path") or "")
        if not base_path or not os.path.isfile(base_path):
            return None
        from PIL import Image
        from imagegen_plugins.pipelines.mflux_schnell import align_mflux_dims

        with Image.open(base_path) as image:
            src_w, src_h = image.size
        return align_mflux_dims(src_w, src_h, max_side=max_side)

    mode = get_pipeline(pipeline_id)
    if not mode.includes_output_dimensions:
        return None

    w = h = None
    if payload is not None:
        try:
            pw = payload.get("width")
            ph = payload.get("height")
            if pw is not None and ph is not None:
                w, h = int(pw), int(ph)
        except (TypeError, ValueError):
            w = h = None
    if w is None or h is None or w <= 0 or h <= 0:
        try:
            w = int(merged.get("width", 0))
            h = int(merged.get("height", 0))
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        w, h = align_dims_for_pipeline(
            pipeline_id, w, h, effective_max_side=max_side
        )

    if pipeline_id == "mflux_fill_expand":
        from imagegen_plugins.outpaint_mask import clamp_outpaint_dims

        return clamp_outpaint_dims(w, h, max_side=max_side)

    return w, h


_pipeline_available_cache: dict[str, bool] = {}


def invalidate_pipeline_availability_cache() -> None:
    _pipeline_available_cache.clear()


def warm_pipeline_availability_cache(
    plugins: Optional[Iterable[Any]] = None,
) -> None:
    """Prime pipeline_is_available once per unique pipeline_id (menu / dialog probes)."""
    if plugins is None:
        from imagegen_plugins import discover_plugins

        plugins = discover_plugins()
    seen: set[str] = set()
    for plugin in plugins:
        pipeline_id = getattr(plugin, "pipeline_id", None)
        if not pipeline_id or pipeline_id in seen:
            continue
        seen.add(pipeline_id)
        pipeline_is_available(pipeline_id)


def pipeline_is_available(pipeline_id: str) -> bool:
    cached = _pipeline_available_cache.get(pipeline_id)
    if cached is not None:
        return cached
    result = False
    if pipeline_id == "flux_schnell_mflux_play":
        from imagegen_plugins.pipelines.mflux_schnell import mflux_is_installed

        result = mflux_is_installed()
    elif pipeline_id == "sana_sprint_600m":
        from pyinstaller_frozen_support import sana_sprint_pipeline_is_installed

        result = sana_sprint_pipeline_is_installed()
    elif pipeline_id == "sd15_diffusers":
        from pyinstaller_frozen_support import sd15_diffusers_pipeline_is_installed

        result = sd15_diffusers_pipeline_is_installed()
    elif pipeline_id == "z_image_turbo_sdnq":
        from imagegen_plugins.pipelines.z_image_turbo import z_image_turbo_is_installed

        result = z_image_turbo_is_installed()
    elif pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        from imagegen_plugins.pipelines.mflux_fill_expand import mflux_is_installed

        result = mflux_is_installed()
    elif pipeline_id in (
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    ):
        from imagegen_plugins.pipelines.mflux_flux2_klein_edit import mflux_is_installed

        result = mflux_is_installed()
    _pipeline_available_cache[pipeline_id] = result
    return result


def worker_script_path(pipeline_id: str) -> str:
    mode = get_pipeline(pipeline_id)
    return str(_PACKAGE_DIR / "pipelines" / mode.worker_script)


def resolve_steps_for_run(pipeline_id: str, values: Dict[str, Any]) -> int:
    """Steps sent to the worker after pipeline bounds and LoRA minimums."""
    mode = get_pipeline(pipeline_id)
    steps = int(values.get("steps", mode.steps_default))
    steps = max(mode.steps_min, min(mode.steps_max, steps))
    if pipeline_id == "flux_schnell_mflux_play":
        stack = normalize_lora_stack_from_values(values, pop=False)
        if stack:
            steps = effective_steps_for_lora_stack(steps, stack, for_fill=False)
        else:
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
    if get_pipeline(pipeline_id).supports_progressive_images:
        from imagegen_plugins.image_gen_persistence import load_show_progressive_images

        out["show_progressive_images"] = load_show_progressive_images()
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
        "mflux_lora": "none",
        "mflux_lora_stack": [],
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
    if "mflux_lora_stack" in base:
        base["mflux_lora_stack"] = normalize_lora_stack_from_values(
            {"mflux_lora_stack": base.get("mflux_lora_stack"), "mflux_lora": base.get("mflux_lora")},
            pop=False,
        )
    elif base.get("mflux_lora"):
        base["mflux_lora_stack"] = normalize_lora_stack_from_values(base, pop=False)
    return base


def build_worker_payload(
    pipeline_id: str,
    values: Dict[str, Any],
    output_path: str,
    hf_model_id: str,
    *,
    effective_max_side: int,
    apply_image_exit: bool = True,
) -> Dict[str, Any]:
    from imagegen_plugins.flux_prompt_job import clear_flux_prompt_ai_job

    run_values = dict(values)
    clear_flux_prompt_ai_job(run_values)
    merged = finalize_run_values(pipeline_id, run_values)
    merged["pipeline_id"] = pipeline_id
    merged["output_path"] = output_path
    merged["hf_model_id"] = hf_model_id
    merged["max_generation_dimension"] = int(effective_max_side)
    mode = get_pipeline(pipeline_id)
    if mode.includes_output_dimensions:
        w, h = align_dims_for_pipeline(
            pipeline_id,
            int(merged.get("width", 1024)),
            int(merged.get("height", 1024)),
            effective_max_side=int(effective_max_side),
        )
        merged["width"] = w
        merged["height"] = h
    if pipeline_id in ("flux_schnell_mflux_play", "mflux_fill_expand", "mflux_fill_infill"):
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        merged.pop("copies", None)
        apply_lora_to_mflux_payload(
            merged,
            for_fill=(pipeline_id in ("mflux_fill_expand", "mflux_fill_infill")),
        )
    if pipeline_id == "mflux_fill_infill":
        from imagegen_plugins.pixelmator_export import missing_infill_export_paths

        missing = missing_infill_export_paths(merged)
        if missing:
            preview = ", ".join(missing[:3])
            raise ValueError(
                "Infill base image or mask is not available on disk "
                f"({preview}). Re-run infill from the paint or Pixelmator dialog."
            )
    if pipeline_id == "mflux_fill_expand":
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths

        source_paths = resolve_source_image_paths(merged)
        if source_paths:
            merged["source_image_paths"] = source_paths
            merged["source_image_path"] = source_paths[0]
    if pipeline_id == "mflux_flux2_klein_create":
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        apply_lora_to_mflux_payload(merged, for_fill=False, for_klein=True)
    if pipeline_id == "sd15_diffusers":
        from imagegen_plugins.sd15_lora_presets import apply_lora_to_sd15_payload

        merged.pop("copies", None)
        apply_lora_to_sd15_payload(merged)
    if pipeline_id == "mflux_flux2_klein_expand":
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        merged["prompt"] = klein_expand_prompt(str(merged.get("prompt") or ""))
        apply_lora_to_mflux_payload(merged, for_fill=False, for_klein=True)
        source_paths = resolve_source_image_paths(merged)
        if source_paths:
            merged["source_image_paths"] = source_paths
            merged["source_image_path"] = source_paths[0]
    if pipeline_id == "mflux_flux2_klein_edit":
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths
        from imagegen_plugins.mflux_lora_presets import apply_lora_to_mflux_payload

        apply_lora_to_mflux_payload(merged, for_fill=False, for_klein=True)
        source_paths = resolve_source_image_paths(merged)
        if source_paths:
            merged["_canonical_source_image_paths"] = list(source_paths)
            merged["source_image_paths"] = source_paths
            merged["source_image_path"] = source_paths[0]
            pad_temps: list[str] = []
            if merged.get("use_custom_size"):
                from imagegen_plugins.edit_aspect_pad import (
                    SCREEN_SIZE_EXPERIMENTAL_PROMPT_SUFFIX,
                    generator_paths_with_screen_size_expansion,
                )

                try:
                    target_w = int(merged.get("width", 0))
                    target_h = int(merged.get("height", 0))
                except (TypeError, ValueError):
                    target_w = target_h = 0
                if target_w > 0 and target_h > 0:
                    source_paths, screen_temps = (
                        generator_paths_with_screen_size_expansion(
                            source_paths,
                            target_width=target_w,
                            target_height=target_h,
                        )
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
    merged.pop("series_refinement", None)
    merged.pop("aspect_ratio_test", None)
    merged.pop("use_custom_size", None)
    merged.pop("pass_image_to_ai_with_prompt", None)
    from imagegen_plugins.lora_trigger_prompt_guard import apply_lora_triggers_for_run

    apply_lora_triggers_for_run(merged)
    if apply_image_exit:
        from imagegen_plugins.ai_prompt_exit import apply_image_ai_exit_to_payload

        apply_image_ai_exit_to_payload(merged)
    return merged
