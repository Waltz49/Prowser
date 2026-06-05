#!/usr/bin/env python3
"""
MFLUX FLUX.1 Fill outfill worker (graphical expand placement).
Reads JSON from stdin; writes PNG to output_path from payload.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from prowser_temp_files import prowser_mkstemp_path
import time
from typing import Any, Dict, Final

from PIL import Image

from imagegen_plugins.outpaint_mask import clamp_outpaint_dims, prepare_image_and_mask_at_rect
from imagegen_plugins.pixelmator_export import pixelmator_mask_to_mflux
from imagegen_plugins.pipelines.mflux_schnell import align_mflux_dims
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
_OUTFILL_DEFAULT_PROMPT: Final[str] = "high quality"


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def _outfill_prompt(prompt: str) -> str:
    text = (prompt or "").strip()
    return text if text else _OUTFILL_DEFAULT_PROMPT


def _build_fill_cli_args(
    *,
    image_path: str,
    mask_path: str,
    output_path: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    quantize: int,
    low_ram: bool,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
) -> list[str]:
    args: list[str] = [
        "-q",
        str(int(quantize)),
        "--steps",
        str(int(steps)),
        "--width",
        str(int(width)),
        "--height",
        str(int(height)),
        "--seed",
        str(int(seed)),
        "--guidance",
        str(float(guidance)),
        "--image-path",
        image_path,
        "--masked-image-path",
        mask_path,
        "--output",
        output_path,
        "--prompt",
        prompt,
    ]
    if low_ram:
        args.append("--low-ram")
    if stepwise_image_output_dir:
        args.extend(["--stepwise-image-output-dir", str(stepwise_image_output_dir)])
    if lora_paths:
        args.extend(["--lora-paths", *[str(p) for p in lora_paths]])
        if lora_scales:
            args.extend(["--lora-scales", *[str(float(s)) for s in lora_scales]])
    return args


def _run_mflux_fill_cli(
    *,
    image_path: str,
    mask_path: str,
    output_path: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    quantize: int,
    low_ram: bool,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    stepwise_image_output_dir: str | None = None,
    progressive_output_path: str | None = None,
) -> None:
    cli_args = _build_fill_cli_args(
        image_path=image_path,
        mask_path=mask_path,
        output_path=output_path,
        prompt=prompt,
        width=width,
        height=height,
        steps=steps,
        guidance=guidance,
        seed=seed,
        quantize=quantize,
        low_ram=low_ram,
        lora_paths=lora_paths,
        lora_scales=lora_scales,
        stepwise_image_output_dir=stepwise_image_output_dir,
    )

    def _run_inprocess() -> None:
        from imagegen_plugins.mflux_flux1_session import generate_flux1_fill

        image = generate_flux1_fill(
            quantize=quantize,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            prompt=prompt,
            seed=seed,
            steps=steps,
            width=width,
            height=height,
            guidance=guidance,
            scheduler="flow_match_euler_discrete",
            low_ram=low_ram,
            stepwise_dir=stepwise_image_output_dir,
            image_path=image_path,
            masked_image_path=mask_path,
        )
        image.save(path=output_path)

    def _run_cli() -> None:
        if mflux_is_installed():
            _run_inprocess()
            return
        if getattr(sys, "frozen", False):
            old_argv = list(sys.argv)
            try:
                sys.argv = ["flux_generate_fill", *cli_args]
                from mflux.models.flux.cli.flux_generate_fill import main as fill_main

                fill_main()
            finally:
                sys.argv = old_argv
            return

        cmd = [
            sys.executable,
            "-m",
            "mflux.models.flux.cli.flux_generate_fill",
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
            raise RuntimeError(f"mflux FLUX Fill failed ({proc.returncode}): {msg[:8000]}")

    run_with_stepwise_watcher(
        seed=seed,
        stepwise_dir=stepwise_image_output_dir,
        progressive_output_path=progressive_output_path,
        run=_run_cli,
    )


def _run_fill_generation(
    *,
    image_path: str,
    mask_path: str,
    output_path: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    quantize: int,
    low_ram: bool,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> float:
    stepwise_dir, progressive_output_path = stepwise_dirs_for_run(steps, output_path)
    if os.path.isfile(output_path):
        try:
            os.unlink(output_path)
        except OSError:
            pass
    mflux_output_path = prowser_mkstemp_path(
        prefix="imagegen-mflux-fill-out-", suffix=".png"
    )
    try:
        os.unlink(mflux_output_path)
    except OSError:
        pass
    t0 = time.perf_counter()
    try:
        _run_mflux_fill_cli(
            image_path=image_path,
            mask_path=mask_path,
            output_path=mflux_output_path,
            prompt=prompt,
            width=width,
            height=height,
            steps=steps,
            guidance=guidance,
            seed=seed,
            quantize=quantize,
            low_ram=low_ram,
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
                f"mflux Fill did not write output: {mflux_output_path}"
            )
        from imagegen_plugins.imagegen_perf_log import PerfTimer

        with PerfTimer("save_output", pipeline="mflux_fill"):
            atomic_copy2(mflux_output_path, output_path)
        finalize_stepwise_progress(output_path, steps)
        return time.perf_counter() - t0
    finally:
        try:
            if os.path.isfile(mflux_output_path):
                os.unlink(mflux_output_path)
        except OSError:
            pass
        cleanup_stepwise_dir(stepwise_dir)


def _run_infill_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    base_path = str(payload.get("pixelmator_base_path") or "")
    mask_path = str(payload.get("pixelmator_mask_path") or "")
    if not base_path or not os.path.isfile(base_path):
        raise ValueError("pixelmator_base_path is required and must exist")
    if not mask_path or not os.path.isfile(mask_path):
        raise ValueError("pixelmator_mask_path is required and must exist")

    steps = max(8, min(30, int(payload.get("steps", 20))))
    guidance = max(1.0, min(50.0, float(payload.get("guidance_scale", 30.0))))
    quantize = int(payload.get("mflux_quantize", 4))
    if quantize not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}")
    low_ram = bool(payload.get("low_ram", True))
    output_path = str(payload["output_path"])

    if payload.get("random_seed", True):
        seed = random.randint(0, 2**31 - 1)
    else:
        seed = int(payload.get("seed", 0)) % (2**31)

    prompt = _outfill_prompt(str(payload.get("prompt") or ""))

    lora_paths = payload.get("mflux_lora_paths")
    lora_scales = payload.get("mflux_lora_scales")
    if lora_paths and not isinstance(lora_paths, list):
        lora_paths = [str(lora_paths)]
    if lora_scales and not isinstance(lora_scales, list):
        lora_scales = [float(lora_scales)]

    background = Image.open(base_path).convert("RGB")
    mask_src = Image.open(mask_path)
    try:
        w, h = align_mflux_dims(background.width, background.height)
        if (w, h) != (background.width, background.height):
            background = background.resize((w, h), Image.LANCZOS)
            mask_src = mask_src.resize((w, h), Image.LANCZOS)
        mask = pixelmator_mask_to_mflux(mask_src)
    finally:
        mask_src.close()

    img_path = prowser_mkstemp_path(prefix="imagegen-mflux-infill-", suffix=".png")
    mask_tmp = prowser_mkstemp_path(prefix="imagegen-mflux-infill-mask-", suffix=".png")
    try:
        background.save(img_path)
        mask.save(mask_tmp)
        generation_time_seconds = _run_fill_generation(
            image_path=img_path,
            mask_path=mask_tmp,
            output_path=output_path,
            prompt=prompt,
            width=w,
            height=h,
            steps=steps,
            guidance=guidance,
            seed=seed,
            quantize=quantize,
            low_ram=low_ram,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
    finally:
        background.close()
        for p in (img_path, mask_tmp):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass

    result: Dict[str, Any] = {
        "output_path": output_path,
        "seed": seed,
        "width": w,
        "height": h,
    }
    result["generation_time_seconds"] = generation_time_seconds
    return result


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if str(payload.get("pipeline_id") or "") == "mflux_fill_infill":
        return _run_infill_from_payload(payload)

    source_path = str(payload.get("source_image_path") or "")
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("source_image_path is required and must exist")

    w, h = clamp_outpaint_dims(int(payload["width"]), int(payload["height"]))
    steps = max(8, min(30, int(payload.get("steps", 20))))
    guidance = max(1.0, min(50.0, float(payload.get("guidance_scale", 30.0))))
    quantize = int(payload.get("mflux_quantize", 4))
    if quantize not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}")
    low_ram = bool(payload.get("low_ram", True))
    overlap = max(0, min(20, int(payload.get("overlap_percentage", 2))))
    output_path = str(payload["output_path"])

    px = int(payload.get("placement_x", 0))
    py = int(payload.get("placement_y", 0))
    pw = int(payload.get("placement_w", w))
    ph = int(payload.get("placement_h", h))

    if payload.get("random_seed", True):
        seed = random.randint(0, 2**31 - 1)
    else:
        seed = int(payload.get("seed", 0)) % (2**31)

    prompt = _outfill_prompt(str(payload.get("prompt") or ""))

    lora_paths = payload.get("mflux_lora_paths")
    lora_scales = payload.get("mflux_lora_scales")
    if lora_paths and not isinstance(lora_paths, list):
        lora_paths = [str(lora_paths)]
    if lora_scales and not isinstance(lora_scales, list):
        lora_scales = [float(lora_scales)]

    prepared = str(payload.get("prepared_fill_image_path") or "")
    if prepared and os.path.isfile(prepared):
        background = Image.open(prepared).convert("RGB")
        image = Image.open(source_path).convert("RGB")
        try:
            _, mask = prepare_image_and_mask_at_rect(
                image, w, h, px, py, pw, ph, overlap
            )
        finally:
            image.close()
    else:
        image = Image.open(source_path).convert("RGB")
        background, mask = prepare_image_and_mask_at_rect(
            image, w, h, px, py, pw, ph, overlap
        )
        image.close()

    img_path = prowser_mkstemp_path(prefix="imagegen-mflux-fill-", suffix=".png")
    mask_path = prowser_mkstemp_path(prefix="imagegen-mflux-mask-", suffix=".png")
    try:
        background.save(img_path)
        mask.save(mask_path)
        generation_time_seconds = _run_fill_generation(
            image_path=img_path,
            mask_path=mask_path,
            output_path=output_path,
            prompt=prompt,
            width=w,
            height=h,
            steps=steps,
            guidance=guidance,
            seed=seed,
            quantize=quantize,
            low_ram=low_ram,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
    finally:
        for p in (img_path, mask_path):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass

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
