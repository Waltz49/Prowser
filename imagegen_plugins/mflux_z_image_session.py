#!/usr/bin/env python3
"""In-process Z-Image Turbo (MFLUX 4-bit) with model retention."""

from __future__ import annotations

import gc
import time
from argparse import Namespace
from typing import Any

from workers.model_tasks_worker import PerfTimer, perf_log_kv

_z_image_model: Any = None
_z_image_loaded_key: tuple[Any, ...] | None = None


def compute_z_image_model_key(
    model_path: str,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> tuple[Any, ...]:
    paths = tuple(str(p) for p in (lora_paths or ()))
    scales = tuple(float(s) for s in (lora_scales or ()))
    return (model_path, paths, scales)


def _model_unusable_after_low_ram(model: Any) -> bool:
    if model is None or getattr(model, "transformer", None) is None:
        return True
    if getattr(model, "text_encoder", None) is None:
        return True
    return False


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


def get_z_image(
    *,
    model_path: str,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> Any:
    global _z_image_model, _z_image_loaded_key
    key = compute_z_image_model_key(model_path, lora_paths, lora_scales)
    if _z_image_model is not None and _z_image_loaded_key == key:
        if _model_unusable_after_low_ram(_z_image_model):
            perf_log_kv("model_load", kind="z_image_turbo", cache="stale", model=model_path)
            _z_image_model = None
            _z_image_loaded_key = None
            gc.collect()
        else:
            perf_log_kv("model_load", kind="z_image_turbo", cache="warm", model=model_path)
            return _z_image_model

    if _z_image_model is not None:
        _z_image_model = None
        _z_image_loaded_key = None
        gc.collect()

    from mflux.models.common.config import ModelConfig
    from mflux.models.z_image.variants.z_image import ZImage

    t0 = time.perf_counter()
    _z_image_model = ZImage(
        model_config=ModelConfig.z_image_turbo(),
        model_path=model_path,
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )
    _z_image_loaded_key = key
    perf_log_kv(
        "model_load",
        kind="z_image_turbo",
        cache="cold",
        model=model_path,
        elapsed=time.perf_counter() - t0,
    )
    return _z_image_model


def release_z_image_session(*, reason: str = "explicit") -> None:
    global _z_image_model, _z_image_loaded_key
    if _z_image_model is not None:
        perf_log_kv("z_image_session_release", reason=reason)
    _z_image_model = None
    _z_image_loaded_key = None
    gc.collect()


def generate_z_image(
    *,
    model_path: str,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
    prompt: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    low_ram: bool,
    stepwise_dir: str | None,
) -> Any:
    from mflux.models.z_image.latent_creator.z_image_latent_creator import (
        ZImageLatentCreator,
    )

    with PerfTimer("z_image_generate", seed=seed, steps=steps, width=width, height=height):
        model = get_z_image(
            model_path=model_path,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        _register_run_callbacks(
            model,
            stepwise_dir=stepwise_dir,
            low_ram=low_ram,
            seed=seed,
            latent_creator=ZImageLatentCreator,
        )
        with PerfTimer("z_image_generate_image", seed=seed):
            return model.generate_image(
                seed=int(seed),
                prompt=prompt,
                width=int(width),
                height=int(height),
                num_inference_steps=int(steps),
                guidance=0.0,
            )
