#!/usr/bin/env python3
"""
Stable Diffusion 1.5 worker (diffusers StableDiffusionPipeline).

Supports checkpoints without a bundled VAE (e.g. Realistic Vision noVAE) by
loading a separate VAE from the Hugging Face cache.
"""

from __future__ import annotations

import gc
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from imagegen_plugins.hf_model_ids import REALISTIC_VISION_V4_NOVAE, SD15_DEFAULT_VAE
from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension
from imagegen_plugins.lora_catalog import lora_weights_file_is_valid

_DEFAULT_HF_MODEL_ID = REALISTIC_VISION_V4_NOVAE
_DEFAULT_VAE_HF_MODEL_ID = SD15_DEFAULT_VAE

_pipe = None
_loaded_model_key: Optional[Tuple[str, str]] = None
_active_lora_key: Optional[Tuple[str, float]] = None
_active_lora_peft: bool = False


def diffusers_is_installed() -> bool:
    from pyinstaller_frozen_support import diffusers_is_installed as _installed

    return _installed()


def align_sd15_dims(w: int, h: int, *, max_side: int = 768) -> Tuple[int, int]:
    """8px alignment; sides in [256, max_side] (SD 1.5 class)."""
    w = max(256, min(max_side, (int(w) // 8) * 8))
    h = max(256, min(max_side, (int(h) // 8) * 8))
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
    global _pipe, _loaded_model_key, _active_lora_key, _active_lora_peft
    _pipe = None
    _loaded_model_key = None
    _active_lora_key = None
    _active_lora_peft = False
    _release_torch_allocators()


def _validate_lora_file(path: Path) -> None:
    if not lora_weights_file_is_valid(path):
        raise RuntimeError(
            f"LoRA file is missing or corrupt: {path}. "
            "Re-download from Settings → LoRA (Install) or delete the cache file and try again."
        )


def _require_peft_backend() -> None:
    from diffusers.utils import USE_PEFT_BACKEND

    if USE_PEFT_BACKEND:
        return
    raise RuntimeError(
        "SD 1.5 LoRAs require the PEFT package (diffusers 0.38+). "
        "Install with: pip install peft"
    )


def _unload_sd15_lora(pipe: Any) -> None:
    global _active_lora_peft
    if _active_lora_peft:
        try:
            from peft import PeftModel

            if isinstance(pipe.unet, PeftModel):
                pipe.unet = pipe.unet.unload()
        except Exception:
            pass
        _active_lora_peft = False
        return
    try:
        pipe.unload_lora_weights()
    except Exception:
        pass


def _load_sd15_lora_weights(pipe: Any, path: str) -> None:
    global _active_lora_peft
    _require_peft_backend()
    lora_path = Path(path).expanduser().resolve()
    _validate_lora_file(lora_path)
    parent = lora_path.parent
    if (parent / "adapter_config.json").is_file():
        from peft import PeftModel

        pipe.unet = PeftModel.from_pretrained(pipe.unet, str(parent))
        pipe.unet.set_adapter("default")
        _active_lora_peft = True
        return
    pipe.load_lora_weights(str(lora_path))
    _active_lora_peft = False


def _sync_lora_weights(pipe: Any, lora_paths: Any, lora_scales: Any) -> Optional[float]:
    """Load/unload LoRA weights on the active pipeline; return adapter scale."""
    global _active_lora_key
    paths = lora_paths if isinstance(lora_paths, list) else []
    scales = lora_scales if isinstance(lora_scales, list) else []
    path = str(paths[0]).strip() if paths else ""
    scale = float(scales[0]) if scales else 1.0
    key = (path, scale) if path else None
    if key == _active_lora_key:
        return scale if path else None
    if _active_lora_key is not None:
        _unload_sd15_lora(pipe)
    _active_lora_key = None
    if not path:
        return None
    _load_sd15_lora_weights(pipe, path)
    _active_lora_key = key
    return scale


def _resolve_vae_hf_model_id(payload: Dict[str, Any]) -> str:
    if "vae_hf_model_id" in payload:
        return str(payload.get("vae_hf_model_id") or "").strip()
    return _DEFAULT_VAE_HF_MODEL_ID


def _ensure_pipeline(hf_model_id: str, vae_hf_model_id: str) -> Any:
    global _pipe, _loaded_model_key
    model_key = (hf_model_id, vae_hf_model_id)
    if _pipe is not None and _loaded_model_key == model_key:
        from workers.model_tasks_worker import perf_log_kv

        perf_log_kv("model_load", kind="sd15_diffusers", cache="warm", model=hf_model_id)
        return _pipe

    unload_pipeline()
    from diffusers import AutoencoderKL, StableDiffusionPipeline
    from workers.model_tasks_worker import perf_log_kv

    load_t0 = time.perf_counter()
    device, torch_dtype = _pick_torch_device()
    tok_kwargs = _hf_hub_token_kwargs()
    pipe_kwargs: Dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "safety_checker": None,
        "requires_safety_checker": False,
        **tok_kwargs,
    }
    if vae_hf_model_id:
        pipe_kwargs["vae"] = AutoencoderKL.from_pretrained(
            vae_hf_model_id,
            torch_dtype=torch_dtype,
            **tok_kwargs,
        )
    _pipe = StableDiffusionPipeline.from_pretrained(hf_model_id, **pipe_kwargs)
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
    _loaded_model_key = model_key
    perf_log_kv(
        "model_load",
        kind="sd15_diffusers",
        cache="cold",
        model=hf_model_id,
        vae=vae_hf_model_id,
        elapsed=time.perf_counter() - load_t0,
    )
    return _pipe


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not diffusers_is_installed():
        raise RuntimeError(
            "diffusers is not installed. Install with: pip install diffusers accelerate"
        )

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    hf_model_id = str(payload.get("hf_model_id") or _DEFAULT_HF_MODEL_ID)
    vae_hf_model_id = _resolve_vae_hf_model_id(payload)
    w, h = align_sd15_dims(
        int(payload["width"]),
        int(payload["height"]),
        max_side=payload_max_generation_dimension(payload),
    )
    steps = max(1, min(50, int(payload.get("steps", 25))))
    guidance = max(1.0, min(20.0, float(payload.get("guidance_scale", 7.5))))
    output_path = str(payload["output_path"])
    negative_prompt = str(payload.get("negative_prompt") or "").strip()

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
    if negative_prompt:
        gen_kwargs["negative_prompt"] = negative_prompt

    from workers.model_tasks_worker import PerfTimer

    t0 = time.perf_counter()
    with PerfTimer("sd15_pipeline", model=hf_model_id):
        pipe = _ensure_pipeline(hf_model_id, vae_hf_model_id)
    lora_scale = _sync_lora_weights(
        pipe,
        payload.get("sd15_lora_paths"),
        payload.get("sd15_lora_scales"),
    )
    if lora_scale is not None:
        gen_kwargs["cross_attention_kwargs"] = {"scale": lora_scale}
    with PerfTimer("sd15_inference", steps=steps, seed=seed):
        out = pipe(**gen_kwargs)
    with PerfTimer("save_output", pipeline="sd15_diffusers"):
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
