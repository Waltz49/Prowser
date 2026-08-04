#!/usr/bin/env python3
"""
MFLUX Z-Image-Turbo 4-bit worker (pre-quantized weights + LoRA support).

Reads generation parameters from JSON payload on stdin when run standalone,
or via run_from_payload from model_tasks_worker.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from typing import Any, Dict, Optional

from imagegen_plugins.image_gen_output_format import mflux_temp_suffix_for_output_path
from imagegen_plugins.hf_model_ids import Z_IMAGE_TURBO_MFLUX_4BIT
from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension
from imagegen_plugins.pipelines.z_image_turbo import align_z_image_dims
from prowser_temp_files import prowser_mkstemp_path
from workers.model_tasks_worker import PerfTimer
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_DEFAULT_HF_MODEL_ID = Z_IMAGE_TURBO_MFLUX_4BIT


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def run_mflux_z_image_generate(
    *,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
    model: str,
    mflux_output_path: str,
    low_ram: bool = False,
    stepwise_image_output_dir: str | None = None,
    progressive_output_path: str | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    isolate_session: bool = False,
    require_lora_layers: bool = False,
) -> str:
    if not mflux_is_installed():
        raise RuntimeError(
            "MFLUX is not installed. Install with: pip install mflux"
        )
    if os.path.isfile(mflux_output_path):
        raise RuntimeError(
            f"MFLUX output path already exists (MFLUX will not overwrite): {mflux_output_path}"
        )

    def _run_inprocess() -> None:
        from imagegen_plugins.mflux_z_image_session import (
            generate_z_image,
            release_z_image_session,
        )

        if isolate_session:
            release_z_image_session(reason="z_image_probe_isolate")

        image = generate_z_image(
            model_path=str(model),
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            prompt=prompt,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            low_ram=low_ram,
            stepwise_dir=stepwise_image_output_dir,
            require_lora_layers=require_lora_layers,
        )
        if image is None:
            raise RuntimeError("lora likely incompatible: no layers matched")
        image.save(path=mflux_output_path)

    run_with_stepwise_watcher(
        seed=seed,
        stepwise_dir=stepwise_image_output_dir,
        progressive_output_path=progressive_output_path,
        run=_run_inprocess,
    )

    if not os.path.isfile(mflux_output_path):
        raise RuntimeError(f"mflux did not write output file: {mflux_output_path}")
    try:
        sz = os.path.getsize(mflux_output_path)
    except OSError as e:
        raise RuntimeError(f"mflux output path not readable: {mflux_output_path} ({e})") from e
    if sz < 64:
        raise RuntimeError(
            f"mflux wrote an empty or trivial output ({sz} bytes) at {mflux_output_path}"
        )
    return mflux_output_path


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not mflux_is_installed():
        raise RuntimeError(
            "Z-Image Turbo (4-bit) requires mflux. Install with: pip install mflux"
        )

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    hf_model_id = str(payload.get("hf_model_id") or _DEFAULT_HF_MODEL_ID)
    w, h = align_z_image_dims(
        int(payload["width"]),
        int(payload["height"]),
        max_side=payload_max_generation_dimension(payload),
    )
    steps = max(1, min(20, int(payload.get("steps", 9))))
    output_path = str(payload["output_path"])
    low_ram = bool(payload.get("low_ram", False))
    lora_paths = payload.get("mflux_lora_paths")
    lora_scales = payload.get("mflux_lora_scales")
    if lora_paths and not isinstance(lora_paths, list):
        lora_paths = [str(lora_paths)]
    if lora_scales and not isinstance(lora_scales, list):
        lora_scales = [float(lora_scales)]

    if payload.get("random_seed", True):
        seed = random.randint(0, 2**31 - 1)
    else:
        seed = int(payload.get("seed", 0)) % (2**31)

    stepwise_dir, progressive_output_path = stepwise_dirs_for_run(steps, output_path)

    mflux_output_path = prowser_mkstemp_path(
        prefix="imagegen-zimage-",
        suffix=mflux_temp_suffix_for_output_path(output_path),
    )
    try:
        os.unlink(mflux_output_path)
    except OSError:
        pass

    generation_time_seconds: Optional[float] = None
    try:
        t0 = time.perf_counter()
        run_mflux_z_image_generate(
            prompt=prompt,
            width=w,
            height=h,
            steps=steps,
            seed=seed,
            model=hf_model_id,
            mflux_output_path=mflux_output_path,
            low_ram=low_ram,
            stepwise_image_output_dir=stepwise_dir,
            progressive_output_path=progressive_output_path,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        generation_time_seconds = time.perf_counter() - t0
        with PerfTimer("save_output", pipeline="mflux_z_image_turbo"):
            atomic_copy2(mflux_output_path, output_path)
        finalize_stepwise_progress(output_path, steps)
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
    if generation_time_seconds is not None:
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
