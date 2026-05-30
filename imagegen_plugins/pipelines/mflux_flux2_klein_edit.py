#!/usr/bin/env python3
"""
MFLUX FLUX.2 Klein edit worker (4B or 9B; one or more images + edit prompt).
Reads JSON from stdin; writes PNG to output_path from payload.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Final

from PIL import Image

from imagegen_plugins.outpaint_mask import fit_edit_output_dims
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
_KLEIN_GUIDANCE: Final[float] = 1.0
_KLEIN_EDIT_MAX_SIDE: Final[int] = 1024


def _output_dims_for_source(source_path: str) -> tuple[int, int]:
    with Image.open(source_path) as image:
        src_w, src_h = image.size
    return fit_edit_output_dims(src_w, src_h, max_side=_KLEIN_EDIT_MAX_SIDE)


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def _source_paths_from_payload(payload: Dict[str, Any]) -> list[str]:
    from imagegen_plugins.image_gen_naming import resolve_source_image_paths

    return resolve_source_image_paths(payload)


def _build_klein_edit_cli_args(
    *,
    image_paths: list[str],
    output_path: str,
    prompt: str,
    model: str,
    steps: int,
    seed: int,
    quantize: int,
    low_ram: bool,
    width: int | None = None,
    height: int | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
) -> list[str]:
    args: list[str] = [
        "-q",
        str(int(quantize)),
        "--steps",
        str(int(steps)),
        "--seed",
        str(int(seed)),
        "--guidance",
        str(_KLEIN_GUIDANCE),
        "--image-paths",
        *[str(p) for p in image_paths],
        "--output",
        output_path,
        "--prompt",
        prompt,
        "--model",
        str(model),
    ]
    if width is not None and height is not None:
        args.extend(["--width", str(int(width)), "--height", str(int(height))])
    if low_ram:
        args.append("--low-ram")
    if stepwise_image_output_dir:
        args.extend(["--stepwise-image-output-dir", str(stepwise_image_output_dir)])
    if lora_paths:
        args.extend(["--lora-paths", *[str(p) for p in lora_paths]])
        if lora_scales:
            args.extend(["--lora-scales", *[str(float(s)) for s in lora_scales]])
    return args


def _run_mflux_klein_edit_cli(
    *,
    image_paths: list[str],
    output_path: str,
    prompt: str,
    model: str,
    steps: int,
    seed: int,
    quantize: int,
    low_ram: bool,
    width: int | None = None,
    height: int | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
    progressive_output_path: str | None = None,
) -> None:
    cli_args = _build_klein_edit_cli_args(
        image_paths=image_paths,
        output_path=output_path,
        prompt=prompt,
        model=model,
        steps=steps,
        seed=seed,
        quantize=quantize,
        low_ram=low_ram,
        width=width,
        height=height,
        lora_paths=lora_paths,
        lora_scales=lora_scales,
        stepwise_image_output_dir=stepwise_image_output_dir,
    )

    def _run_cli() -> None:
        if getattr(sys, "frozen", False):
            old_argv = list(sys.argv)
            try:
                sys.argv = ["flux2_edit_generate", *cli_args]
                from mflux.models.flux2.cli.flux2_edit_generate import main as klein_edit_main

                klein_edit_main()
            finally:
                sys.argv = old_argv
            return

        cmd = [
            sys.executable,
            "-m",
            "mflux.models.flux2.cli.flux2_edit_generate",
            *cli_args,
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            msg = err or out or f"exit {proc.returncode}"
            raise RuntimeError(
                f"mflux FLUX.2 Klein edit failed ({proc.returncode}): {msg[:8000]}"
            )

    run_with_stepwise_watcher(
        seed=seed,
        stepwise_dir=stepwise_image_output_dir,
        progressive_output_path=progressive_output_path,
        run=_run_cli,
    )


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_paths = _source_paths_from_payload(payload)
    if not source_paths:
        raise ValueError(
            "source_image_path (or source_image_paths) is required and must exist"
        )
    source_path = source_paths[0]

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    steps = max(1, min(50, int(payload.get("steps", 4))))
    quantize = int(payload.get("mflux_quantize", 4))
    if quantize not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}")
    low_ram = bool(payload.get("low_ram", True))
    output_path = str(payload["output_path"])
    model = str(
        payload.get("mflux_model_name")
        or payload.get("hf_model_id")
        or "flux2-klein-4b"
    ).strip()
    if not model:
        raise ValueError("mflux_model_name is required")

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

    width_i, height_i = _output_dims_for_source(source_path)
    stepwise_dir, progressive_output_path = stepwise_dirs_for_run(steps, output_path)

    if os.path.isfile(output_path):
        try:
            os.unlink(output_path)
        except OSError:
            pass

    fd, mflux_output_path = tempfile.mkstemp(
        prefix="imagegen-mflux-klein-out-", suffix=".png"
    )
    os.close(fd)
    try:
        os.unlink(mflux_output_path)
    except OSError:
        pass

    t0 = time.perf_counter()
    try:
        _run_mflux_klein_edit_cli(
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
            progressive_output_path=progressive_output_path,
        )
        if (
            not os.path.isfile(mflux_output_path)
            or os.path.getsize(mflux_output_path) < 64
        ):
            raise RuntimeError(
                f"mflux Klein edit did not write output: {mflux_output_path}"
            )
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
