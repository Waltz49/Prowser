#!/usr/bin/env python3
"""
Stable Diffusion XL 1.0 worker (diffusers StableDiffusionXLPipeline).

Apple Silicon: float32 weights with model CPU offload on MPS (16GB-safe), attention/VAE
slicing/tiling, 896px max side. Pipeline unload is debounced (120s idle) unless forced.
"""

from __future__ import annotations

import gc
import json
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from prowser_temp_files import prowser_mkstemp_path

from imagegen_plugins.hf_model_ids import SDXL_BASE_1_0
from imagegen_plugins.image_gen_dim_limits import payload_max_generation_dimension
from imagegen_plugins.lora_catalog import lora_weights_file_is_valid

_DEFAULT_HF_MODEL_ID = SDXL_BASE_1_0
_UNLOAD_IDLE_SECONDS = 120.0
_MPS_OFFLOAD_MODES = frozenset(
    {"mps_model_cpu_offload", "mps_sequential_cpu_offload"}
)

_pipe = None
_loaded_model_key: Optional[str] = None
_active_lora_key: Optional[Tuple[str, float]] = None
_active_lora_peft: bool = False
_unload_timer: Optional[threading.Timer] = None
_unload_lock = threading.Lock()


def diffusers_is_installed() -> bool:
    from pyinstaller_frozen_support import diffusers_is_installed as _installed

    return _installed()


def align_sdxl_dims(w: int, h: int, *, max_side: int = 896) -> Tuple[int, int]:
    """8px alignment; sides in [256, max_side] (SDXL class)."""
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


def _apply_sdxl_memory_optimizations(pipe: Any, device: str) -> str:
    """Reduce peak MPS memory; full float32 SDXL (~13GB) cannot infer on 16GB Macs."""
    if hasattr(pipe, "enable_attention_slicing"):
        try:
            pipe.enable_attention_slicing(1)
        except Exception:
            try:
                pipe.enable_attention_slicing()
            except Exception:
                pass
    vae = getattr(pipe, "vae", None)
    if vae is not None:
        if hasattr(vae, "enable_slicing"):
            try:
                vae.enable_slicing()
            except Exception:
                pass
        elif hasattr(pipe, "enable_vae_slicing"):
            try:
                pipe.enable_vae_slicing()
            except Exception:
                pass
        if hasattr(vae, "enable_tiling"):
            try:
                vae.enable_tiling()
            except Exception:
                pass
        elif hasattr(pipe, "enable_vae_tiling"):
            try:
                pipe.enable_vae_tiling()
            except Exception:
                pass
    if device != "mps":
        pipe.to(device)
        return device
    try:
        from imagegen_plugins.mflux_model_session import release_mlx_metal_cache

        release_mlx_metal_cache()
    except Exception:
        pass
    _release_torch_allocators()
    try:
        pipe.enable_model_cpu_offload()
        return "mps_model_cpu_offload"
    except Exception:
        try:
            pipe.enable_sequential_cpu_offload()
            return "mps_sequential_cpu_offload"
        except Exception:
            pipe.to(device)
            return device


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


def _cancel_scheduled_unload() -> None:
    global _unload_timer
    with _unload_lock:
        if _unload_timer is not None:
            _unload_timer.cancel()
            _unload_timer = None


def _touch_pipeline_activity() -> None:
    _cancel_scheduled_unload()


def _unload_pipeline_now() -> None:
    global _pipe, _loaded_model_key, _active_lora_key, _active_lora_peft
    _pipe = None
    _loaded_model_key = None
    _active_lora_key = None
    _active_lora_peft = False
    _release_torch_allocators()


def _run_deferred_unload() -> None:
    global _unload_timer
    with _unload_lock:
        _unload_timer = None
    _unload_pipeline_now()


def unload_pipeline(*, force: bool = False) -> None:
    """Drop cached pipeline. Default: debounce 120s so back-to-back jobs reuse weights."""
    if force:
        _cancel_scheduled_unload()
        _unload_pipeline_now()
        return
    global _unload_timer
    with _unload_lock:
        if _unload_timer is not None:
            _unload_timer.cancel()
        _unload_timer = threading.Timer(_UNLOAD_IDLE_SECONDS, _run_deferred_unload)
        _unload_timer.daemon = True
        _unload_timer.start()


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
        "SDXL LoRAs require the PEFT package (diffusers 0.38+). "
        "Install with: pip install peft"
    )


def _unload_sdxl_lora(pipe: Any) -> None:
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


def _sdxl_lora_text_encoder_peft_state(
    state_dict: Dict[str, Any],
    *,
    prefix: str,
    strip_text_model_prefix: bool,
) -> Dict[str, Any]:
    """Convert Kohya/A1111 SDXL TE LoRA keys for diffusers+transformers module names."""
    from diffusers.utils import convert_state_dict_to_diffusers, convert_state_dict_to_peft

    filtered = {
        k.removeprefix(f"{prefix}."): v
        for k, v in state_dict.items()
        if k.startswith(f"{prefix}.")
    }
    if not filtered:
        return {}
    peft_state = convert_state_dict_to_peft(convert_state_dict_to_diffusers(filtered))
    if not strip_text_model_prefix:
        return peft_state
    return {
        (k.removeprefix("text_model.") if k.startswith("text_model.") else k): v
        for k, v in peft_state.items()
    }


def _sdxl_lora_adapter_name(index: int) -> str:
    return f"sdxl_lora_{index}"


def _load_sdxl_lora_into_text_encoder(
    pipe: Any,
    state_dict: Dict[str, Any],
    network_alphas: Any,
    metadata: Any,
    *,
    prefix: str,
    strip_text_model_prefix: bool,
    adapter_name: str,
) -> None:
    """Load SDXL text-encoder LoRA; work around TE1/TE2 module-name prefix mismatch."""
    from diffusers.utils.peft_utils import _create_lora_config, scale_lora_layers

    text_encoder = pipe.text_encoder if prefix == "text_encoder" else pipe.text_encoder_2
    peft_state = _sdxl_lora_text_encoder_peft_state(
        state_dict,
        prefix=prefix,
        strip_text_model_prefix=strip_text_model_prefix,
    )
    if not peft_state:
        return

    rank: Dict[str, int] = {}
    for name, _ in text_encoder.named_modules():
        if name.endswith((".q_proj", ".k_proj", ".v_proj", ".out_proj", ".fc1", ".fc2")):
            rank_key = f"{name}.lora_B.weight"
            if rank_key in peft_state:
                rank[rank_key] = int(peft_state[rank_key].shape[1])
    if not rank:
        return

    te_alphas = network_alphas
    if network_alphas:
        alpha_keys = [
            k for k in network_alphas.keys() if k.startswith(prefix) and k.split(".")[0] == prefix
        ]
        te_alphas = {
            k.removeprefix(f"{prefix}."): v for k, v in network_alphas.items() if k in alpha_keys
        }

    lora_config = _create_lora_config(
        peft_state, te_alphas, metadata, rank, is_unet=False
    )
    text_encoder.load_adapter(
        adapter_name=adapter_name,
        adapter_state_dict=peft_state,
        peft_config=lora_config,
    )
    scale_lora_layers(text_encoder, weight=1.0)


def _load_sdxl_lora_weights(pipe: Any, path: str, *, adapter_name: str) -> None:
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

    # Kohya/A1111 SDXL LoRAs: diffusers 0.39 + transformers 5.x fail inside
    # load_lora_weights() when matching TE1 keys (text_model.* vs encoder.*).
    from diffusers.loaders.lora_pipeline import StableDiffusionXLLoraLoaderMixin

    state_dict, network_alphas, metadata = StableDiffusionXLLoraLoaderMixin.lora_state_dict(
        str(lora_path),
        unet_config=pipe.unet.config,
        return_lora_metadata=True,
    )
    StableDiffusionXLLoraLoaderMixin.load_lora_into_unet(
        state_dict,
        network_alphas=network_alphas,
        unet=pipe.unet,
        adapter_name=adapter_name,
        metadata=metadata,
        _pipeline=pipe,
    )
    _load_sdxl_lora_into_text_encoder(
        pipe,
        state_dict,
        network_alphas,
        metadata,
        prefix="text_encoder",
        strip_text_model_prefix=True,
        adapter_name=adapter_name,
    )
    _load_sdxl_lora_into_text_encoder(
        pipe,
        state_dict,
        network_alphas,
        metadata,
        prefix="text_encoder_2",
        strip_text_model_prefix=False,
        adapter_name=adapter_name,
    )
    _active_lora_peft = False


def _sync_lora_weights(
    pipe: Any, lora_paths: Any, lora_scales: Any
) -> Optional[list[float]]:
    """Load/unload LoRA weights on the active pipeline; apply per-adapter scales."""
    global _active_lora_key
    paths = [str(p).strip() for p in (lora_paths if isinstance(lora_paths, list) else []) if str(p).strip()]
    scales_in = lora_scales if isinstance(lora_scales, list) else []
    scales: list[float] = []
    for index, _path in enumerate(paths):
        if index < len(scales_in):
            scales.append(float(scales_in[index]))
        else:
            scales.append(1.0)
    key: Optional[Tuple[Tuple[str, float], ...]] = (
        tuple(zip(paths, scales)) if paths else None
    )
    if key == _active_lora_key:
        return scales if paths else None
    if _active_lora_key is not None:
        _unload_sdxl_lora(pipe)
    _active_lora_key = None
    if not paths:
        return None
    adapter_names: list[str] = []
    for index, path in enumerate(paths):
        name = _sdxl_lora_adapter_name(index)
        _load_sdxl_lora_weights(pipe, path, adapter_name=name)
        adapter_names.append(name)
    if hasattr(pipe, "set_adapters"):
        pipe.set_adapters(adapter_names, adapter_weights=scales)
    _active_lora_key = key
    return scales


def _ensure_pipeline(hf_model_id: str) -> Any:
    global _pipe, _loaded_model_key
    _touch_pipeline_activity()
    device, _ = _pick_torch_device()
    if _pipe is not None and _loaded_model_key == hf_model_id:
        deploy_mode = getattr(_pipe, "_deploy_mode", "")
        if device == "mps" and deploy_mode not in _MPS_OFFLOAD_MODES:
            unload_pipeline(force=True)
        else:
            from workers.model_tasks_worker import perf_log_kv

            perf_log_kv("model_load", kind="sdxl_diffusers", cache="warm", model=hf_model_id)
            return _pipe

    unload_pipeline(force=True)
    from diffusers import StableDiffusionXLPipeline
    from workers.model_tasks_worker import perf_log_kv

    load_t0 = time.perf_counter()
    device, torch_dtype = _pick_torch_device()
    tok_kwargs = _hf_hub_token_kwargs()
    _pipe = StableDiffusionXLPipeline.from_pretrained(
        hf_model_id,
        torch_dtype=torch_dtype,
        use_safetensors=True,
        **tok_kwargs,
    )
    deploy_mode = _apply_sdxl_memory_optimizations(_pipe, device)
    _pipe._deploy_mode = deploy_mode  # type: ignore[attr-defined]
    _loaded_model_key = hf_model_id
    perf_log_kv(
        "model_load",
        kind="sdxl_diffusers",
        cache="cold",
        model=hf_model_id,
        deploy_mode=deploy_mode,
        elapsed=time.perf_counter() - load_t0,
    )
    return _pipe


def probe_lora_weights(hf_model_id: str, lora_path: str, lora_scale: float) -> None:
    """Load pipeline + LoRA weights without running inference (import compatibility probe)."""
    pipe = _ensure_pipeline(hf_model_id)
    _sync_lora_weights(pipe, [lora_path], [lora_scale])


def _preview_image_from_latents(pipe: Any, latents: Any) -> Any:
    """Decode denoised latents to a PIL preview (VAE decode; used for progressive display)."""
    import torch

    vae = pipe.vae
    with torch.no_grad():
        latents = latents.to(device=vae.device, dtype=vae.dtype)
        if hasattr(pipe, "upcast_vae") and getattr(vae.config, "force_upcast", False):
            pipe.upcast_vae()
            latents = latents.to(
                next(iter(vae.post_quant_conv.parameters())).dtype
            )
        scaling = float(getattr(vae.config, "scaling_factor", 0.13025))
        decoded = vae.decode(latents / scaling, return_dict=False)[0]
        image = pipe.image_processor.postprocess(decoded, output_type="pil")
    if isinstance(image, list):
        return image[0]
    return image


def _write_progressive_preview(pipe: Any, latents: Any, output_path: str) -> bool:
    """Decode latents and atomically update the run's output PNG for browse preview."""
    from imagegen_plugins.pipelines.mflux_stepwise_progress import atomic_copy2

    tmp_path = prowser_mkstemp_path(prefix="sdxl-progress-", suffix=".png")
    try:
        _preview_image_from_latents(pipe, latents).save(tmp_path)
        atomic_copy2(tmp_path, output_path)
        return True
    finally:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def run_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not diffusers_is_installed():
        raise RuntimeError(
            "diffusers is not installed. Install with: pip install diffusers accelerate"
        )

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    hf_model_id = str(payload.get("hf_model_id") or _DEFAULT_HF_MODEL_ID)
    w, h = align_sdxl_dims(
        int(payload["width"]),
        int(payload["height"]),
        max_side=payload_max_generation_dimension(payload),
    )
    steps = max(1, min(50, int(payload.get("steps", 30))))
    guidance = max(1.0, min(20.0, float(payload.get("guidance_scale", 7.5))))
    output_path = str(payload["output_path"])
    negative_prompt = str(payload.get("negative_prompt") or "").strip()
    if "show_progressive_images" in payload:
        show_progressive = bool(payload.get("show_progressive_images"))
    else:
        from imagegen_plugins.image_gen_persistence import load_show_progressive_images

        show_progressive = load_show_progressive_images()

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
    with PerfTimer("sdxl_pipeline", model=hf_model_id):
        pipe = _ensure_pipeline(hf_model_id)
    deploy_mode = str(getattr(pipe, "_deploy_mode", "") or "")
    # VAE decode inside the denoise loop forces UNet<->VAE swaps under CPU offload (very slow).
    progressive_vae_previews = (
        show_progressive
        and steps > 1
        and deploy_mode not in _MPS_OFFLOAD_MODES
    )
    if show_progressive and deploy_mode in _MPS_OFFLOAD_MODES:
        print(
            "[sdxl_diffusers] progressive VAE previews skipped under CPU offload "
            "(step counter only; previews are not practical on 16GB MPS)",
            file=sys.stderr,
        )
    _sync_lora_weights(
        pipe,
        payload.get("sdxl_lora_paths"),
        payload.get("sdxl_lora_scales"),
    )
    from imagegen_plugins.pipelines.mflux_stepwise_progress import emit_mflux_progress

    def _on_step_end(
        pipe_obj: Any, step_index: int, timestep: Any, callback_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        step_num = step_index + 1
        preview_path: Optional[str] = None
        if progressive_vae_previews and step_num < steps:
            latents = callback_kwargs.get("latents")
            if latents is not None:
                try:
                    if _write_progressive_preview(pipe_obj, latents, output_path):
                        preview_path = output_path
                except Exception as exc:
                    print(
                        f"[sdxl_diffusers] progressive preview failed at step {step_num}: {exc}",
                        file=sys.stderr,
                    )
                    preview_path = None
        emit_mflux_progress(
            preview_path,
            step=step_num,
            step_total=steps,
        )
        return callback_kwargs

    pipe_kwargs: Dict[str, Any] = {
        **gen_kwargs,
        "callback_on_step_end": _on_step_end,
    }
    if progressive_vae_previews:
        pipe_kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]
    with PerfTimer("sdxl_inference", steps=steps, seed=seed):
        out = pipe(**pipe_kwargs)
    emit_mflux_progress(step=steps, step_total=steps)
    with PerfTimer("save_output", pipeline="sdxl_diffusers"):
        out.images[0].save(output_path)
    generation_time_seconds = time.perf_counter() - t0
    unload_pipeline()

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
