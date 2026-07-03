#!/usr/bin/env python3
"""
Local SANA Sprint 0.6B 1024px worker (diffusers SanaSprintPipeline).

Reads generation parameters from JSON payload on stdin
when run as a standalone script, or via run_from_payload from model_tasks_worker.
"""

from __future__ import annotations

import gc
import json
import os
import random
import sys
import time
from typing import Any, Dict, Optional, Tuple

from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension

_DEFAULT_HF_MODEL_ID = "Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers"
_SANA_EXTRA_KEYS = ("use_resolution_binning", "max_sequence_length", "clean_caption")

_pipe = None
_loaded_hf_model_id: Optional[str] = None


def diffusers_is_installed() -> bool:
    from pyinstaller_frozen_support import diffusers_is_installed as _installed

    return _installed()


def align_sana_sprint_dims(w: int, h: int, *, max_side: int = 1024) -> Tuple[int, int]:
    """32px alignment; sides in [256, max_side] (Sana Sprint 1024px class)."""
    w = max(256, min(max_side, (int(w) // 32) * 32))
    h = max(256, min(max_side, (int(h) // 32) * 32))
    return w, h


def _hf_hub_token_kwargs() -> Dict[str, Any]:
    tok = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if tok:
        return {"token": tok}
    return {"token": False}


def _pick_torch_device() -> Tuple[str, Any]:
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.float16
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps", torch.float32
    return "cpu", torch.float32


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

        perf_log_kv("model_load", kind="sana_sprint", cache="warm", model=hf_model_id)
        return _pipe

    unload_pipeline()
    from diffusers import SanaSprintPipeline
    from workers.model_tasks_worker import perf_log_kv

    load_t0 = time.perf_counter()
    device, torch_dtype = _pick_torch_device()
    tok_kwargs = _hf_hub_token_kwargs()
    kwargs = {"torch_dtype": torch_dtype, "use_safetensors": True, **tok_kwargs}
    _pipe = SanaSprintPipeline.from_pretrained(hf_model_id, **kwargs)
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
        kind="sana_sprint",
        cache="cold",
        model=hf_model_id,
        elapsed=time.perf_counter() - load_t0,
    )
    return _pipe


def _merge_sana_extras(gen_kwargs: Dict[str, Any], payload: Dict[str, Any]) -> None:
    for key in _SANA_EXTRA_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if value is not None:
            gen_kwargs[key] = value


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not diffusers_is_installed():
        raise RuntimeError(
            "diffusers is not installed. Install with: pip install diffusers accelerate"
        )

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    hf_model_id = str(payload.get("hf_model_id") or _DEFAULT_HF_MODEL_ID)
    w, h = align_sana_sprint_dims(
        int(payload["width"]),
        int(payload["height"]),
        max_side=payload_max_generation_dimension(payload),
    )
    steps = max(1, min(50, int(payload.get("steps", 2))))
    guidance = max(1.0, min(20.0, float(payload.get("guidance_scale", 4.5))))
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
        "guidance_scale": guidance,
        "generator": gen,
    }
    _merge_sana_extras(gen_kwargs, payload)
    if steps != 2:
        gen_kwargs["intermediate_timesteps"] = None

    from workers.model_tasks_worker import PerfTimer

    t0 = time.perf_counter()
    with PerfTimer("sana_pipeline", model=hf_model_id):
        pipe = _ensure_pipeline(hf_model_id)
    with PerfTimer("sana_inference", steps=steps, seed=seed):
        out = pipe(**gen_kwargs)
    with PerfTimer("save_output", pipeline="sana_sprint"):
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
