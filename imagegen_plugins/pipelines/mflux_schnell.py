#!/usr/bin/env python3
"""
MFLUX FLUX.1 Schnell worker (subprocess entry) and shared generation helpers.
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
from typing import Any, Dict, Final, Optional, Tuple

from imagegen_plugins.image_gen_pipeline_modes import MFLUX_FLOW_MATCH_MIN_STEPS
from imagegen_plugins.pipelines.mflux_stepwise_progress import (
    atomic_copy2,
    cleanup_stepwise_dir,
    finalize_stepwise_progress,
    run_with_stepwise_watcher,
    stepwise_dirs_for_run,
)

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
FLUX_LOCAL_IMAGE_DIM_MAX = 1440


def mflux_is_installed() -> bool:
    from pyinstaller_frozen_support import mflux_is_installed as _installed

    return _installed()


def _align_flux_dims(w: int, h: int) -> Tuple[int, int]:
    w = max(256, min(FLUX_LOCAL_IMAGE_DIM_MAX, (int(w) // 8) * 8))
    h = max(256, min(FLUX_LOCAL_IMAGE_DIM_MAX, (int(h) // 8) * 8))
    return w, h


def align_mflux_dims(w: int, h: int) -> Tuple[int, int]:
    w, h = _align_flux_dims(w, h)
    w = max(256, min(FLUX_LOCAL_IMAGE_DIM_MAX, (int(w) // 16) * 16))
    h = max(256, min(FLUX_LOCAL_IMAGE_DIM_MAX, (int(h) // 16) * 16))
    return w, h


def run_mflux_flux_schnell_generate(
    *,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    model: str,
    quantize: int,
    mflux_output_path: str,
    low_ram: bool = False,
    stepwise_image_output_dir: str | None = None,
    progressive_output_path: str | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
) -> str:
    """Run mflux FLUX Schnell CLI; write mflux_output_path (may differ from progressive preview path)."""
    q = int(quantize)
    if q not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}, got {q}")
    if not mflux_is_installed():
        raise RuntimeError(
            "MFLUX is not installed. Install with: pip install mflux"
        )
    if os.path.isfile(mflux_output_path):
        raise RuntimeError(
            f"MFLUX output path already exists (MFLUX will not overwrite): {mflux_output_path}"
        )

    cli_args = _build_mflux_cli_args(
        prompt=prompt,
        width=width,
        height=height,
        steps=steps,
        guidance=guidance,
        seed=seed,
        model=model,
        quantize=q,
        mflux_output_path=mflux_output_path,
        low_ram=low_ram,
        stepwise_image_output_dir=stepwise_image_output_dir,
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )

    out = ""
    err = ""

    def _run_inprocess() -> None:
        from imagegen_plugins.mflux_flux1_session import generate_flux1

        base_model = "schnell" if "/" in str(model) else None
        image = generate_flux1(
            model_name=str(model),
            quantize=q,
            base_model=base_model,
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
        )
        image.save(path=mflux_output_path)

    def _run_cli() -> None:
        nonlocal out, err
        if mflux_is_installed():
            _run_inprocess()
            return
        if getattr(sys, "frozen", False):
            _run_mflux_cli_inprocess(cli_args)
        else:
            out, err = _run_mflux_cli_subprocess(cli_args)

    run_with_stepwise_watcher(
        seed=seed,
        stepwise_dir=stepwise_image_output_dir,
        progressive_output_path=progressive_output_path,
        run=_run_cli,
    )

    if err:
        combined = f"{out}\n{err}"
        hint = ""
        if lora_paths and (
            "matmul" in combined
            or "Could not find target path" in combined
            or "lora_unet_" in combined
        ):
            hint = (
                "\n\nLoRA likely incompatible with MFLUX (wrong key layout). "
                "Try Realism (arch), MS Paint, or Paper cutout."
            )
        raise RuntimeError(f"mflux FLUX generate failed:{hint}\n{err[-6000:]}")
    if not os.path.isfile(mflux_output_path):
        tail = f"\nstdout:\n{out[:4000]}\nstderr:\n{err[:4000]}" if (out or err) else ""
        raise RuntimeError(f"mflux did not write output file: {mflux_output_path}{tail}")
    try:
        sz = os.path.getsize(mflux_output_path)
    except OSError as e:
        raise RuntimeError(f"mflux output path not readable: {mflux_output_path} ({e})") from e
    if sz < 64:
        tail = f"\nstdout:\n{out[:4000]}\nstderr:\n{err[:4000]}" if (out or err) else ""
        raise RuntimeError(
            f"mflux wrote an empty or trivial output ({sz} bytes) at {mflux_output_path}.{tail}"
        )
    return mflux_output_path


def _build_mflux_cli_args(
    *,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    guidance: float,
    seed: int,
    model: str,
    quantize: int,
    mflux_output_path: str,
    low_ram: bool,
    stepwise_image_output_dir: str | None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
) -> list[str]:
    args: list[str] = ["--model", str(model)]
    if "/" in str(model):
        args.extend(["--base-model", "schnell"])
    args.extend(
        [
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
            "--output",
            mflux_output_path,
            "--prompt",
            prompt,
        ]
    )
    if low_ram:
        args.append("--low-ram")
    if stepwise_image_output_dir:
        args.extend(["--stepwise-image-output-dir", str(stepwise_image_output_dir)])
    if lora_paths:
        args.append("--lora-paths")
        args.extend(str(p) for p in lora_paths)
        if lora_scales:
            args.append("--lora-scales")
            args.extend(str(float(s)) for s in lora_scales)
    return args


def _run_mflux_cli_subprocess(cli_args: list[str]) -> Tuple[str, str]:
    cmd = [sys.executable, "-m", "mflux.models.flux.cli.flux_generate", *cli_args]
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
        return out, msg
    return out, ""


def _run_mflux_cli_inprocess(cli_args: list[str]) -> None:
    """PyInstaller bundle: avoid spawning Prowser again as ``-m`` (use in-process CLI)."""
    old_argv = list(sys.argv)
    try:
        sys.argv = ["flux_generate", *cli_args]
        from mflux.models.flux.cli.flux_generate import main as flux_main

        flux_main()
    except Exception as e:
        err = str(e)
        if getattr(sys, "frozen", False):
            from pyinstaller_frozen_support import log_frozen_diagnostic

            log_frozen_diagnostic(f"[mflux] in-process generate failed: {err}")
            if "initializing the extension" in err.lower():
                log_frozen_diagnostic(
                    "[mflux] MLX native extension failed to load in the app bundle. "
                    "Rebuild with ./pyInstallerBuild.sh and check Tools > Debug > View log."
                )
        raise RuntimeError(err) from e
    finally:
        sys.argv = old_argv


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute generation from a JSON-serializable dict."""
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    w, h = align_mflux_dims(int(payload["width"]), int(payload["height"]))
    steps = max(
        MFLUX_FLOW_MATCH_MIN_STEPS,
        min(30, int(payload.get("steps", 4))),
    )
    guidance = max(0.0, min(10.0, float(payload.get("guidance_scale", 3.5))))
    quantize = int(payload.get("mflux_quantize", 3))
    model = str(payload.get("hf_model_id") or "schnell")
    low_ram = bool(payload.get("low_ram", False))
    output_path = str(payload["output_path"])
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

    fd, mflux_output_path = tempfile.mkstemp(prefix="imagegen-mflux-", suffix=".png")
    os.close(fd)
    try:
        os.unlink(mflux_output_path)
    except OSError:
        pass

    generation_time_seconds: Optional[float] = None
    try:
        t0 = time.perf_counter()
        run_mflux_flux_schnell_generate(
            prompt=prompt,
            width=w,
            height=h,
            steps=steps,
            guidance=guidance,
            seed=seed,
            model=model,
            quantize=quantize,
            mflux_output_path=mflux_output_path,
            low_ram=low_ram,
            stepwise_image_output_dir=stepwise_dir,
            progressive_output_path=progressive_output_path,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        generation_time_seconds = time.perf_counter() - t0
        from imagegen_plugins.imagegen_perf_log import PerfTimer

        with PerfTimer("save_output", pipeline="flux_schnell"):
            atomic_copy2(mflux_output_path, output_path)
        finalize_stepwise_progress(output_path, steps)
    finally:
        try:
            if os.path.isfile(mflux_output_path):
                os.unlink(mflux_output_path)
        except OSError:
            pass
        cleanup_stepwise_dir(stepwise_dir)

    result: Dict[str, Any] = {"output_path": output_path, "seed": seed, "width": w, "height": h}
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
