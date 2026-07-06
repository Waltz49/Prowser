#!/usr/bin/env python3
"""
MFLUX FLUX.2 Klein txt2img worker (4B, 9B, or 9B KV).
Reads JSON from stdin; writes PNG to output_path from payload.
"""

from __future__ import annotations

import json
import os
import random
import sys
from prowser_temp_files import prowser_mkstemp_path
import time
from typing import Any, Dict, Final, Tuple

from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension
from imagegen_plugins.image_gen_pipeline_modes import MFLUX_FLOW_MATCH_MIN_STEPS
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
_KLEIN_GUIDANCE: Final[float] = 1.0


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def align_mflux_flux2_klein_dims(
    w: int, h: int, *, max_side: int
) -> Tuple[int, int]:
    w, h = int(w), int(h)
    max_side = int(max_side)
    if w > 0 and h > 0 and max_side > 0:
        scale = min(1.0, max_side / w, max_side / h)
        w = int(w * scale)
        h = int(h * scale)
    w = max(256, min(max_side, (w // 16) * 16))
    h = max(256, min(max_side, (h // 16) * 16))
    return w, h


def _run_mflux_klein_create(
    *,
    output_path: str,
    prompt: str,
    model: str,
    steps: int,
    seed: int,
    quantize: int | None,
    low_ram: bool,
    width: int,
    height: int,
    model_path: str | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
) -> None:
    if not mflux_is_installed():
        raise RuntimeError(
            "MFLUX is not installed. Install with: pip install mflux"
        )
    from imagegen_plugins.mflux_flux2_klein_session import generate_flux2_klein_create

    def _run() -> None:
        image = generate_flux2_klein_create(
            model_name=model,
            quantize=quantize,
            model_path=model_path,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            prompt=prompt,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            guidance=_KLEIN_GUIDANCE,
            low_ram=low_ram,
            stepwise_dir=stepwise_image_output_dir,
        )
        image.save(path=output_path)

    _run()


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    w, h = align_mflux_flux2_klein_dims(
        int(payload.get("width", 1024)),
        int(payload.get("height", 1024)),
        max_side=payload_max_generation_dimension(payload),
    )
    steps = max(
        MFLUX_FLOW_MATCH_MIN_STEPS,
        min(50, int(payload.get("steps", 4))),
    )
    low_ram = bool(payload.get("low_ram", True))
    output_path = str(payload["output_path"])
    from imagegen_plugins.sceneworks_klein_mlx import klein_load_params_from_payload

    model, quantize, model_path = klein_load_params_from_payload(payload)

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

    stepwise_dir, progressive_output_path = stepwise_dirs_for_run(steps, output_path)

    if os.path.isfile(output_path):
        try:
            os.unlink(output_path)
        except OSError:
            pass

    mflux_output_path = prowser_mkstemp_path(
        prefix="imagegen-mflux-klein-create-", suffix=".png"
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
            run=lambda: _run_mflux_klein_create(
                output_path=mflux_output_path,
                prompt=prompt,
                model=model,
                steps=steps,
                seed=seed,
                quantize=quantize,
                low_ram=low_ram,
                width=w,
                height=h,
                model_path=model_path,
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
                f"mflux Klein create did not write output: {mflux_output_path}"
            )
        from workers.model_tasks_worker import PerfTimer

        with PerfTimer("save_output", pipeline="flux2_klein_create"):
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
        "width": w,
        "height": h,
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
