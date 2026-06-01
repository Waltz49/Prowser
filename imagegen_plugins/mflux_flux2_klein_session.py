#!/usr/bin/env python3
"""In-process FLUX.2 Klein edit with model retention and VAE encode caching."""

from __future__ import annotations

import gc
import os
import time
from argparse import Namespace
from collections import OrderedDict
from pathlib import Path
from typing import Any

import mlx.core as mx

from imagegen_plugins.imagegen_perf_log import PerfTimer, perf_log_kv

_VAE_CACHE_MAX = 10

_session_model: Any = None
_session_key: tuple[Any, ...] | None = None


def _image_stat_key(path: str) -> tuple[str, int]:
    p = os.path.abspath(path)
    st = os.stat(p)
    return (os.path.basename(p), int(st.st_mtime_ns))


def _reference_cache_key(
    image_paths: list[str],
    width: int,
    height: int,
    session_key: tuple[Any, ...],
) -> tuple[Any, ...]:
    return (
        session_key,
        int(width),
        int(height),
        tuple(_image_stat_key(p) for p in image_paths),
    )


class _VaeEncodeCache:
    def __init__(self, maxsize: int = _VAE_CACHE_MAX) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[tuple[Any, ...], tuple[mx.array, mx.array]] = OrderedDict()

    def get(self, key: tuple[Any, ...]) -> tuple[mx.array, mx.array] | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: tuple[Any, ...], value: tuple[mx.array, mx.array]) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            evicted_key, _ = self._data.popitem(last=False)
            perf_log_kv(
                "vae_cache",
                event="evict",
                cache_size=self._maxsize,
                key_basename=str(evicted_key[3])[:120] if len(evicted_key) > 3 else "",
            )

    def clear(self) -> None:
        self._data.clear()


_vae_cache = _VaeEncodeCache()


def _klein_session_key(
    model_name: str,
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> tuple[Any, ...]:
    paths = tuple(str(p) for p in (lora_paths or ()))
    scales = tuple(float(s) for s in (lora_scales or ()))
    return (model_name, int(quantize), paths, scales)


def _register_run_callbacks(
    model: Any,
    *,
    stepwise_dir: str | None,
    low_ram: bool,
    seed: int,
) -> None:
    from mflux.callbacks.callback_manager import CallbackManager
    from mflux.callbacks.callback_registry import CallbackRegistry
    from mflux.models.flux2.latent_creator.flux2_latent_creator import Flux2LatentCreator

    model.callbacks = CallbackRegistry()
    args = Namespace(
        stepwise_image_output_dir=stepwise_dir,
        low_ram=low_ram,
        seed=[int(seed)],
        battery_percentage_stop_limit=None,
        output=None,
        mlx_cache_limit_gb=None,
    )
    CallbackManager.register_callbacks(
        args=args,
        model=model,
        latent_creator=Flux2LatentCreator,
    )


def get_flux2_klein_edit(
    *,
    model_name: str,
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
) -> Any:
    global _session_model, _session_key
    key = _klein_session_key(model_name, quantize, lora_paths, lora_scales)
    if _session_model is not None and _session_key == key:
        perf_log_kv("model_load", kind="flux2_klein_edit", cache="warm", model=model_name)
        return _session_model

    release_flux2_klein_session(reason="reload")
    from mflux.models.common.config import ModelConfig
    from mflux.models.flux2.variants.edit.flux2_klein_edit import Flux2KleinEdit

    t0 = time.perf_counter()
    model_config = ModelConfig.from_name(model_name=model_name)
    _session_model = Flux2KleinEdit(
        model_config=model_config,
        quantize=int(quantize),
        lora_paths=lora_paths,
        lora_scales=lora_scales,
    )
    _session_key = key
    perf_log_kv(
        "model_load",
        kind="flux2_klein_edit",
        cache="cold",
        model=model_name,
        quantize=quantize,
        elapsed=time.perf_counter() - t0,
    )
    return _session_model


def release_flux2_klein_session(*, reason: str = "explicit") -> None:
    global _session_model, _session_key
    if _session_model is not None:
        perf_log_kv("klein_session_release", reason=reason)
    _session_model = None
    _session_key = None
    _vae_cache.clear()
    gc.collect()


def _reference_conditioning(
    model: Any,
    image_paths: list[str],
    *,
    width: int,
    height: int,
    batch_size: int,
    session_key: tuple[Any, ...],
) -> tuple[mx.array | None, mx.array | None]:
    if not image_paths:
        return None, None

    cache_key = _reference_cache_key(image_paths, width, height, session_key)
    cached = _vae_cache.get(cache_key)
    if cached is not None:
        perf_log_kv(
            "vae_reference",
            cache="hit",
            num_images=len(image_paths),
            width=width,
            height=height,
        )
        return cached

    from mflux.models.flux2.variants.edit.flux2_klein_edit_helpers import (
        _Flux2KleinEditHelpers,
    )

    t0 = time.perf_counter()
    image_latents, image_latent_ids = _Flux2KleinEditHelpers.prepare_reference_image_conditioning(
        vae=model.vae,
        tiling_config=model.tiling_config,
        image_paths=[Path(p) for p in image_paths],
        height=height,
        width=width,
        batch_size=batch_size,
    )
    elapsed = time.perf_counter() - t0
    _vae_cache.put(cache_key, (image_latents, image_latent_ids))
    perf_log_kv(
        "vae_reference",
        cache="miss",
        num_images=len(image_paths),
        width=width,
        height=height,
        elapsed=elapsed,
    )
    return image_latents, image_latent_ids


def generate_flux2_klein_edit(
    *,
    model_name: str,
    quantize: int,
    lora_paths: list[str] | None,
    lora_scales: list[float] | None,
    prompt: str,
    seed: int,
    steps: int,
    width: int,
    height: int,
    guidance: float,
    image_paths: list[str],
    low_ram: bool,
    stepwise_dir: str | None,
) -> Any:
    """Run one Klein edit; returns mflux GeneratedImage."""
    from mflux.models.common.config.config import Config
    from mflux.models.flux2.variants.edit.flux2_klein_edit import Flux2KleinEdit
    from mflux.models.flux2.variants.edit.flux2_klein_edit_helpers import (
        _Flux2KleinEditHelpers,
    )
    from mflux.utils.exceptions import StopImageGenerationException
    from mflux.utils.image_util import ImageUtil

    with PerfTimer("klein_generate", seed=seed, steps=steps):
        model = get_flux2_klein_edit(
            model_name=model_name,
            quantize=quantize,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
        )
        _register_run_callbacks(
            model,
            stepwise_dir=stepwise_dir,
            low_ram=low_ram,
            seed=seed,
        )

        primary_image_path = image_paths[0] if image_paths else None
        config = Config(
            model_config=model.model_config,
            num_inference_steps=int(steps),
            height=int(height),
            width=int(width),
            guidance=float(guidance),
            image_path=primary_image_path,
            image_strength=None,
            scheduler="flow_match_euler_discrete",
        )

        with PerfTimer("prompt_encode", pipeline="flux2_klein_edit"):
            prompt_embeds, text_ids, negative_prompt_embeds, negative_text_ids = (
                model._encode_prompt_pair(
                    prompt=prompt,
                    negative_prompt=" ",
                    guidance=guidance,
                )
            )

        with PerfTimer("latents_init", seed=seed):
            latents, latent_ids, latent_height, latent_width = (
                _Flux2KleinEditHelpers.prepare_generation_latents(
                    seed=int(seed),
                    height=config.height,
                    width=config.width,
                )
            )

        session_key = _klein_session_key(model_name, quantize, lora_paths, lora_scales)
        image_latents, image_latent_ids = _reference_conditioning(
            model,
            image_paths,
            width=config.width,
            height=config.height,
            batch_size=latents.shape[0],
            session_key=session_key,
        )

        ctx = model.callbacks.start(seed=seed, prompt=prompt, config=config)
        ctx.before_loop(latents)
        predict = Flux2KleinEdit._predict(model.transformer)
        total_steps = len(config.time_steps)
        denoise_t0 = time.perf_counter()
        for step_idx, t in enumerate(config.time_steps):
            step_t0 = time.perf_counter()
            try:
                noise = predict(
                    latents=latents,
                    image_latents=image_latents,
                    latent_ids=latent_ids,
                    image_latent_ids=image_latent_ids,
                    prompt_embeds=prompt_embeds,
                    text_ids=text_ids,
                    negative_prompt_embeds=negative_prompt_embeds,
                    negative_text_ids=negative_text_ids,
                    guidance=guidance,
                    timestep=config.scheduler.timesteps[t],
                )
                latents = config.scheduler.step(
                    noise=noise,
                    timestep=t,
                    latents=latents,
                    sigmas=config.scheduler.sigmas,
                )
                ctx.in_loop(t, latents)
                mx.eval(latents)
            except KeyboardInterrupt:
                ctx.interruption(t, latents)
                raise StopImageGenerationException(
                    f"Stopping image generation at step {t + 1}/{config.num_inference_steps}"
                ) from None
            perf_log_kv(
                "denoise_step",
                step=step_idx + 1,
                total=total_steps,
                elapsed=time.perf_counter() - step_t0,
            )

        perf_log_kv("denoise_total", steps=total_steps, elapsed=time.perf_counter() - denoise_t0)
        ctx.after_loop(latents)

        with PerfTimer("vae_decode", pipeline="flux2_klein_edit"):
            packed_latents = latents.reshape(
                latents.shape[0], latent_height, latent_width, latents.shape[-1]
            ).transpose(0, 3, 1, 2)
            decoded = model.vae.decode_packed_latents(packed_latents)
        return ImageUtil.to_image(
            decoded_latents=decoded,
            config=config,
            seed=seed,
            prompt=prompt,
            negative_prompt=None,
            quantization=model.bits,
            image_paths=[Path(p) for p in image_paths],
            image_path=config.image_path,
            generation_time=config.time_steps.format_dict["elapsed"],
        )
