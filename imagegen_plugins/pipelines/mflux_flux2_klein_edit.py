#!/usr/bin/env python3
"""
MFLUX FLUX.2 Klein edit worker (4B or 9B; one or more images + edit prompt).
Reads JSON from stdin; writes PNG to output_path from payload.
"""

from __future__ import annotations

import json
import os
import random
import sys
from prowser_temp_files import prowser_mkstemp_path
import time
from typing import Any, Dict, Final

from PIL import Image

from imagegen_plugins.image_gen_pipeline_modes import MFLUX_FLOW_MATCH_MIN_STEPS
from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension
from imagegen_plugins.outpaint_mask import (
    composite_masked_regions_for_klein_edit,
    fit_edit_output_dims,
    prepare_image_and_mask_at_rect,
)
from imagegen_plugins.pipelines.mflux_flux2_klein_create import align_mflux_flux2_klein_dims
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
_KLEIN_GUIDANCE: Final[float] = 1.0


def _output_dims_for_source(source_path: str, *, max_side: int) -> tuple[int, int]:
    with Image.open(source_path) as image:
        src_w, src_h = image.size
    return fit_edit_output_dims(src_w, src_h, max_side=max_side)


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def _source_paths_from_payload(payload: Dict[str, Any]) -> list[str]:
    from imagegen_plugins.image_gen_naming import resolve_source_image_paths

    return resolve_source_image_paths(payload)


def _run_mflux_klein_edit(
    *,
    image_paths: list[str],
    output_path: str,
    prompt: str,
    model: str,
    steps: int,
    seed: int,
    quantize: int,
    low_ram: bool,
    width: int,
    height: int,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
) -> None:
    if not mflux_is_installed():
        raise RuntimeError(
            "MFLUX is not installed. Install with: pip install mflux"
        )
    from imagegen_plugins.mflux_flux2_klein_session import generate_flux2_klein_edit

    def _run() -> None:
        image = generate_flux2_klein_edit(
            model_name=model,
            quantize=quantize,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            prompt=prompt,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            guidance=_KLEIN_GUIDANCE,
            image_paths=image_paths,
            low_ram=low_ram,
            stepwise_dir=stepwise_image_output_dir,
        )
        image.save(path=output_path)

    _run()


def _klein_expand_dims(payload: Dict[str, Any]) -> tuple[int, int]:
    max_side = payload_max_generation_dimension(payload)
    return align_mflux_flux2_klein_dims(
        int(payload["width"]),
        int(payload["height"]),
        max_side=max_side,
    )


def _run_klein_expand_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = str(payload.get("source_image_path") or "")
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("source_image_path is required and must exist")

    w, h = _klein_expand_dims(payload)
    px = int(payload.get("placement_x", 0))
    py = int(payload.get("placement_y", 0))
    pw = int(payload.get("placement_w", w))
    ph = int(payload.get("placement_h", h))
    overlap = max(0, min(20, int(payload.get("overlap_percentage", 2))))

    image = Image.open(source_path).convert("RGB")
    try:
        background, mask = prepare_image_and_mask_at_rect(
            image, w, h, px, py, pw, ph, overlap
        )
        composite = composite_masked_regions_for_klein_edit(background, mask)
    finally:
        image.close()

    composite_path = prowser_mkstemp_path(
        prefix="imagegen-klein-expand-", suffix=".png"
    )
    try:
        os.unlink(composite_path)
    except OSError:
        pass
    try:
        composite.save(composite_path)
        run_payload = dict(payload)
        run_payload["source_image_path"] = composite_path
        run_payload["source_image_paths"] = [composite_path]
        run_payload["width"] = w
        run_payload["height"] = h
        return _run_klein_edit_from_payload(run_payload)
    finally:
        try:
            if os.path.isfile(composite_path):
                os.unlink(composite_path)
        except OSError:
            pass


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    pipeline_id = str(payload.get("pipeline_id") or "")
    if pipeline_id == "mflux_flux2_klein_expand":
        return _run_klein_expand_from_payload(payload)
    return _run_klein_edit_from_payload(payload)


def _run_klein_edit_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_paths = _source_paths_from_payload(payload)
    if not source_paths:
        raise ValueError(
            "source_image_path (or source_image_paths) is required and must exist"
        )
    source_path = source_paths[0]

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    steps = max(
        MFLUX_FLOW_MATCH_MIN_STEPS,
        min(50, int(payload.get("steps", 4))),
    )
    quantize = int(payload.get("mflux_quantize", 4))
    if quantize not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}")
    low_ram = bool(payload.get("low_ram", True))
    output_path = str(payload["output_path"])
    model = str(payload.get("hf_model_id") or "").strip()
    if not model:
        raise ValueError("hf_model_id is required")

    if payload.get("random_seed", True):
        seed = random.randint(0, 2**31 - 1)
    else:
        seed = int(payload.get("seed", 0)) % (2**31)

    lora_paths = payload.get("mflux_lora_paths")
    lora_scales = payload.get("mflux_lora_scales")
    if lora_paths and not isinstance(lora_paths, list):
        lora_paths = [str(lora_paths)]
    if lora_scales and not isinstance(lora_scales, list):
        lora_scales = [float(lora_scales)]

    pipeline_id = str(payload.get("pipeline_id") or "")
    if pipeline_id == "mflux_flux2_klein_expand":
        width_i = int(payload.get("width", 0))
        height_i = int(payload.get("height", 0))
        if width_i <= 0 or height_i <= 0:
            raise ValueError("width and height are required for Klein expand")
    else:
        width_i, height_i = _output_dims_for_source(
            source_path,
            max_side=payload_max_generation_dimension(payload),
        )
    stepwise_dir, progressive_output_path = stepwise_dirs_for_run(steps, output_path)

    if os.path.isfile(output_path):
        try:
            os.unlink(output_path)
        except OSError:
            pass

    mflux_output_path = prowser_mkstemp_path(
        prefix="imagegen-mflux-klein-out-", suffix=".png"
    )
    try:
        os.unlink(mflux_output_path)
    except OSError:
        pass

    t0 = time.perf_counter()
    try:
        run_with_stepwise_watcher(
            seed=seed,
            stepwise_dir=stepwise_dir,
            progressive_output_path=progressive_output_path,
            run=lambda: _run_mflux_klein_edit(
                image_paths=source_paths,
                output_path=mflux_output_path,
                prompt=prompt,
                model=model,
                steps=steps,
                seed=seed,
                quantize=quantize,
                low_ram=low_ram,
                width=width_i,
                height=height_i,
                lora_paths=lora_paths,
                lora_scales=lora_scales,
                stepwise_image_output_dir=stepwise_dir,
            ),
        )
        if (
            not os.path.isfile(mflux_output_path)
            or os.path.getsize(mflux_output_path) < 64
        ):
            raise RuntimeError(
                f"mflux Klein edit did not write output: {mflux_output_path}"
            )
        from workers.model_tasks_worker import PerfTimer

        with PerfTimer("save_output", pipeline="flux2_klein_edit"):
            atomic_copy2(mflux_output_path, output_path)
        finalize_stepwise_progress(output_path, steps)
        generation_time_seconds = time.perf_counter() - t0
    finally:
        try:
            if os.path.isfile(mflux_output_path):
                os.unlink(mflux_output_path)
        except OSError:
            pass
        cleanup_stepwise_dir(stepwise_dir)

    result: Dict[str, Any] = {
        "output_path": output_path,
        "seed": seed,
        "width": width_i,
        "height": height_i,
    }
    result["generation_time_seconds"] = generation_time_seconds
    return result


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        result = run_from_payload(payload)
        print(json.dumps(result))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
