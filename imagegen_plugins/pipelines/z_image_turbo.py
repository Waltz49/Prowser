#!/usr/bin/env python3
"""
Z-Image-Turbo worker (diffusers ZImagePipeline + SDNQ 8-bit weights).

Reads generation parameters from JSON payload on stdin when run standalone,
or via run_from_payload from model_tasks_worker.
"""

from __future__ import annotations

import gc
import json
import os
import random
import sys
import time
from typing import Any, Dict, Optional, Tuple

from imagegen_plugins.hf_model_ids import Z_IMAGE_TURBO_SDNQ_INT8
from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension

_DEFAULT_HF_MODEL_ID = Z_IMAGE_TURBO_SDNQ_INT8
_TURBO_GUIDANCE_SCALE = 0.0

_pipe = None
_loaded_hf_model_id: Optional[str] = None


def diffusers_is_installed() -> bool:
    from pyinstaller_frozen_support import diffusers_is_installed as _installed

    return _installed()


def z_image_turbo_is_installed() -> bool:
    """True when diffusers Z-Image pipeline module and SDNQ are available (no import)."""
    from pyinstaller_frozen_support import sdnq_is_installed, z_image_pipeline_is_installed

    return z_image_pipeline_is_installed() and sdnq_is_installed()


def align_z_image_dims(w: int, h: int, *, max_side: int = 1024) -> Tuple[int, int]:
    """16px alignment; sides in [256, max_side] (Z-Image Turbo class)."""
    w = max(256, min(max_side, (int(w) // 16) * 16))
    h = max(256, min(max_side, (int(h) // 16) * 16))
    return w, h


def _hf_hub_token_kwargs() -> Dict[str, Any]:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if tok:
        return {"token": tok}
    return {"token": False}


def _pick_torch_device() -> Tuple[str, Any]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.bfloat16
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.bfloat16
    return "cpu", torch.bfloat16


def _release_torch_allocators() -> None:
    gc.collect()
    try:
        import torch
    except ImportError:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


def unload_pipeline() -> None:
    global _pipe, _loaded_hf_model_id
    _pipe = None
    _loaded_hf_model_id = None
    _release_torch_allocators()


def _ensure_pipeline(hf_model_id: str) -> Any:
    global _pipe, _loaded_hf_model_id
    if _pipe is not None and _loaded_hf_model_id == hf_model_id:
        from workers.model_tasks_worker import perf_log_kv

        perf_log_kv("model_load", kind="z_image_turbo", cache="warm", model=hf_model_id)
        return _pipe

    unload_pipeline()
    import sdnq  # noqa: F401
    from diffusers import ZImagePipeline
    from workers.model_tasks_worker import perf_log_kv

    import torch

    load_t0 = time.perf_counter()
    device, torch_dtype = _pick_torch_device()
    tok_kwargs = _hf_hub_token_kwargs()
    kwargs = {"torch_dtype": torch_dtype, "use_safetensors": True, **tok_kwargs}
    _pipe = ZImagePipeline.from_pretrained(hf_model_id, **kwargs)
    if device == "mps" and getattr(_pipe, "vae", None) is not None:
        try:
            _pipe.vae.to(dtype=torch.float32)
        except Exception:
            pass
    _pipe.to(device)
    if hasattr(_pipe, "enable_attention_slicing"):
        try:
            _pipe.enable_attention_slicing()
        except Exception:
            pass
    if hasattr(_pipe, "enable_vae_slicing"):
        try:
            _pipe.enable_vae_slicing()
        except Exception:
            pass
    _loaded_hf_model_id = hf_model_id
    perf_log_kv(
        "model_load",
        kind="z_image_turbo",
        cache="cold",
        model=hf_model_id,
        elapsed=time.perf_counter() - load_t0,
    )
    return _pipe


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not z_image_turbo_is_installed():
        raise RuntimeError(
            "Z-Image Turbo requires diffusers and sdnq. "
            "Install with: pip install diffusers accelerate sdnq"
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

    if payload.get("random_seed", True):
        seed = random.randint(0, 2**31 - 1)
    else:
        seed = int(payload.get("seed", 0)) % (2**31)

    import torch

    gen = torch.Generator(device="cpu")
    gen.manual_seed(seed)

    gen_kwargs: Dict[str, Any] = {
        "prompt": prompt,
        "width": w,
        "height": h,
        "num_inference_steps": steps,
        "guidance_scale": _TURBO_GUIDANCE_SCALE,
        "generator": gen,
    }

    from workers.model_tasks_worker import PerfTimer

    t0 = time.perf_counter()
    with PerfTimer("z_image_pipeline", model=hf_model_id):
        pipe = _ensure_pipeline(hf_model_id)
    with PerfTimer("z_image_inference", steps=steps, seed=seed):
        out = pipe(**gen_kwargs)
    with PerfTimer("save_output", pipeline="z_image_turbo"):
        out.images[0].save(output_path)
    generation_time_seconds = time.perf_counter() - t0

    return {
        "output_path": output_path,
        "seed": seed,
        "width": w,
        "height": h,
        "generation_time_seconds": generation_time_seconds,
    }


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
