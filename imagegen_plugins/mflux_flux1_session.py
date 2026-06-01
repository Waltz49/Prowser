#!/usr/bin/env python3
"""In-process FLUX.1 Schnell and Fill with model retention."""

from __future__ import annotations

import gc
import time
from argparse import Namespace
from typing import Any

from imagegen_plugins.imagegen_perf_log import PerfTimer, perf_log_kv

_flux1_model: Any = None
_flux1_loaded_key: tuple[Any, ...] | None = None
_flux1_fill_model: Any = None
_flux1_fill_loaded_key: tuple[Any, ...] | None = None


def compute_flux1_model_key(
    model_name: str,
    quantize: int,
    base_model: str | None,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> tuple[Any, ...]:
    paths = tuple(str(p) for p in (lora_paths or ()))
    scales = tuple(float(s) for s in (lora_scales or ()))
    return (model_name, int(quantize), str(base_model or ""), paths, scales)


def compute_flux1_fill_model_key(
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> tuple[Any, ...]:
    paths = tuple(str(p) for p in (lora_paths or ()))
    scales = tuple(float(s) for s in (lora_scales or ()))
    return (int(quantize), paths, scales)


def _model_unusable_after_low_ram(model: Any) -> bool:
    """MemorySaver can drop weights after a run; do not reuse a hollow shell."""
    return model is None or getattr(model, "transformer", None) is None


def _register_run_callbacks(
    model: Any,
    *,
    stepwise_dir: str | None,
    low_ram: bool,
    seed: int,
    latent_creator: Any,
) -> None:
    from mflux.callbacks.callback_manager import CallbackManager
    from mflux.callbacks.callback_registry import CallbackRegistry

    model.callbacks = CallbackRegistry()
    # MemorySaver keeps the transformer only when len(seed) > 1; series jobs need that.
    seed_arg: list[int] = [int(seed)]
    if low_ram:
        seed_arg = [int(seed), int(seed)]
    args = Namespace(
        stepwise_image_output_dir=stepwise_dir,
        low_ram=low_ram,
        seed=seed_arg,
        battery_percentage_stop_limit=None,
        output=None,
        mlx_cache_limit_gb=None,
    )
    CallbackManager.register_callbacks(
        args=args,
        model=model,
        latent_creator=latent_creator,
    )


def get_flux1(
    *,
    model_name: str,
    quantize: int,
    base_model: str | None,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> Any:
    global _flux1_model, _flux1_loaded_key
    key = compute_flux1_model_key(
        model_name, quantize, base_model, lora_paths, lora_scales
    )
    if _flux1_model is not None and _flux1_loaded_key == key:
        if _model_unusable_after_low_ram(_flux1_model):
            perf_log_kv("model_load", kind="flux1", cache="stale", model=model_name)
            _flux1_model = None
            _flux1_loaded_key = None
            gc.collect()
        else:
            perf_log_kv("model_load", kind="flux1", cache="warm", model=model_name)
            return _flux1_model

    if _flux1_model is not None:
        _flux1_model = None
        _flux1_loaded_key = None
        gc.collect()

    from mflux.models.common.config import ModelConfig
    from mflux.models.flux.variants.txt2img.flux import Flux1

    t0 = time.perf_counter()
    model_config = ModelConfig.from_name(
        model_name=model_name,
        base_model=base_model,
    )
    _flux1_model = Flux1(
        model_config=model_config,
        quantize=int(quantize),
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )
    _flux1_loaded_key = key
    perf_log_kv(
        "model_load",
        kind="flux1",
        cache="cold",
        model=model_name,
        quantize=quantize,
        elapsed=time.perf_counter() - t0,
    )
    return _flux1_model


def get_flux1_fill(
    *,
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> Any:
    global _flux1_fill_model, _flux1_fill_loaded_key
    key = compute_flux1_fill_model_key(quantize, lora_paths, lora_scales)
    if _flux1_fill_model is not None and _flux1_fill_loaded_key == key:
        if _model_unusable_after_low_ram(_flux1_fill_model):
            perf_log_kv("model_load", kind="flux1_fill", cache="stale")
            _flux1_fill_model = None
            _flux1_fill_loaded_key = None
            gc.collect()
        else:
            perf_log_kv("model_load", kind="flux1_fill", cache="warm")
            return _flux1_fill_model

    if _flux1_fill_model is not None:
        _flux1_fill_model = None
        _flux1_fill_loaded_key = None
        gc.collect()

    from mflux.models.flux.variants.fill.flux_fill import Flux1Fill

    t0 = time.perf_counter()
    _flux1_fill_model = Flux1Fill(
        quantize=int(quantize),
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )
    _flux1_fill_loaded_key = key
    perf_log_kv(
        "model_load",
        kind="flux1_fill",
        cache="cold",
        quantize=quantize,
        elapsed=time.perf_counter() - t0,
    )
    return _flux1_fill_model


def release_flux1_sessions(*, reason: str = "explicit") -> None:
    global _flux1_model, _flux1_loaded_key, _flux1_fill_model, _flux1_fill_loaded_key
    if _flux1_model is not None or _flux1_fill_model is not None:
        perf_log_kv("flux1_session_release", reason=reason)
    _flux1_model = None
    _flux1_loaded_key = None
    _flux1_fill_model = None
    _flux1_fill_loaded_key = None
    gc.collect()


def generate_flux1(
    *,
    model_name: str,
    quantize: int,
    base_model: str | None,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
    prompt: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    guidance: float,
    scheduler: str,
    low_ram: bool,
    stepwise_dir: str | None,
    image_path: str | None = None,
    image_strength: float | None = None,
    negative_prompt: str = "",
) -> Any:
    from mflux.models.flux.latent_creator.flux_latent_creator import FluxLatentCreator

    with PerfTimer("flux1_generate", seed=seed, steps=steps, width=width, height=height):
        model = get_flux1(
            model_name=model_name,
            quantize=quantize,
            base_model=base_model,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        _register_run_callbacks(
            model,
            stepwise_dir=stepwise_dir,
            low_ram=low_ram,
            seed=seed,
            latent_creator=FluxLatentCreator,
        )
        with PerfTimer("flux1_generate_image", seed=seed):
            return model.generate_image(
                seed=int(seed),
                prompt=prompt,
                width=int(width),
                height=int(height),
                guidance=float(guidance),
                scheduler=scheduler,
                image_path=image_path,
                num_inference_steps=int(steps),
                image_strength=image_strength,
                negative_prompt=negative_prompt or "",
            )


def generate_flux1_fill(
    *,
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
    prompt: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    guidance: float,
    scheduler: str,
    low_ram: bool,
    stepwise_dir: str | None,
    image_path: str,
    masked_image_path: str,
) -> Any:
    from mflux.models.flux.latent_creator.flux_latent_creator import FluxLatentCreator

    with PerfTimer("flux1_fill_generate", seed=seed, steps=steps):
        model = get_flux1_fill(
            quantize=quantize,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        _register_run_callbacks(
            model,
            stepwise_dir=stepwise_dir,
            low_ram=low_ram,
            seed=seed,
            latent_creator=FluxLatentCreator,
        )
        with PerfTimer("flux1_fill_generate_image", seed=seed):
            return model.generate_image(
                seed=int(seed),
                prompt=prompt,
                width=int(width),
                height=int(height),
                guidance=float(guidance),
                scheduler=scheduler,
                image_path=image_path,
                num_inference_steps=int(steps),
                masked_image_path=masked_image_path,
            )
