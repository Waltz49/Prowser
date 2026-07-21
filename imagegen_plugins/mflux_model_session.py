#!/usr/bin/env python3
"""Retain loaded MFLUX models in the model_tasks worker between generations."""

from __future__ import annotations

import gc
import time
from typing import Any, Dict, Optional

from workers.model_tasks_worker import perf_log_kv

IMAGE_MODEL_IDLE_SECONDS = 600.0

_LOADED_PIPELINE_ID: Optional[str] = None
_LOADED_MODEL_KEY: Optional[tuple[Any, ...]] = None
_last_image_activity: Optional[float] = None
_image_model_retained: bool = False


def image_model_key(payload: Dict[str, Any]) -> tuple[Any, ...]:
    """Identity for whether the in-memory MFLUX weights match this payload."""
    pipeline_id = str(payload.get("pipeline_id") or "")
    quantize = int(payload.get("mflux_quantize", 0))
    model = str(payload.get("hf_model_id") or "")
    lora_paths = payload.get("mflux_lora_paths") or []
    lora_scales = payload.get("mflux_lora_scales") or []
    if not isinstance(lora_paths, list):
        lora_paths = [str(lora_paths)]
    if not isinstance(lora_scales, list):
        lora_scales = [float(lora_scales)]
    return (
        pipeline_id,
        model,
        quantize,
        tuple(str(p) for p in lora_paths),
        tuple(float(s) for s in lora_scales),
    )


def touch_image_model_activity() -> None:
    global _last_image_activity, _image_model_retained
    _last_image_activity = time.monotonic()
    _image_model_retained = True


def note_image_model_loaded(payload: Dict[str, Any]) -> None:
    global _LOADED_PIPELINE_ID, _LOADED_MODEL_KEY
    _LOADED_PIPELINE_ID = str(payload.get("pipeline_id") or "")
    _LOADED_MODEL_KEY = image_model_key(payload)
    touch_image_model_activity()



def release_all_mflux_sessions(*, reason: str = "explicit") -> None:
    """Drop retained MFLUX sessions (call before gc / switching to caption)."""
    global _LOADED_PIPELINE_ID, _LOADED_MODEL_KEY, _image_model_retained, _last_image_activity
    if _image_model_retained or _LOADED_PIPELINE_ID is not None:
        perf_log_kv("model_unload", reason=reason, pipeline=_LOADED_PIPELINE_ID or "")
    from imagegen_plugins.mflux_flux1_session import release_flux1_sessions
    from imagegen_plugins.mflux_flux2_klein_session import release_flux2_klein_session

    release_flux2_klein_session(reason=reason)
    release_flux1_sessions(reason=reason)
    _LOADED_PIPELINE_ID = None
    _LOADED_MODEL_KEY = None
    _image_model_retained = False
    _last_image_activity = None


def prepare_image_model_for_payload(payload: Dict[str, Any]) -> None:
    """Unload when pipeline or model identity changes."""
    global _LOADED_PIPELINE_ID, _LOADED_MODEL_KEY
    key = image_model_key(payload)
    pipeline_id = str(payload.get("pipeline_id") or "")
    if _LOADED_PIPELINE_ID is None:
        return
    if _LOADED_PIPELINE_ID != pipeline_id or _LOADED_MODEL_KEY != key:
        release_all_mflux_sessions(
            reason=f"pipeline_change {_LOADED_PIPELINE_ID!r}->{pipeline_id!r}"
        )
        if _LOADED_PIPELINE_ID in (
            "sana_sprint_600m",
            "sd15_diffusers",
            "z_image_turbo_sdnq",
        ) or pipeline_id in (
            "sana_sprint_600m",
            "sd15_diffusers",
            "z_image_turbo_sdnq",
        ):
            try:
                from imagegen_plugins.pipelines.sana_sprint import unload_pipeline as unload_sana

                unload_sana()
            except Exception:
                pass
            try:
                from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline as unload_sd15

                unload_sd15()
            except Exception:
                pass
            try:
                from imagegen_plugins.pipelines.z_image_turbo import unload_pipeline as unload_z_image

                unload_z_image()
            except Exception:
                pass


def maybe_unload_idle_image_model() -> bool:
    """Unload image weights if unused longer than IMAGE_MODEL_IDLE_SECONDS."""
    if not _image_model_retained or _last_image_activity is None:
        return False
    idle = time.monotonic() - _last_image_activity
    if idle < IMAGE_MODEL_IDLE_SECONDS:
        return False
    release_all_mflux_sessions(
        reason=f"idle {round(idle, 1)}s (threshold {int(IMAGE_MODEL_IDLE_SECONDS)}s)"
    )
    try:
        from imagegen_plugins.pipelines.sana_sprint import unload_pipeline as unload_sana

        unload_sana()
    except Exception:
        pass
    try:
        from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline as unload_sd15

        unload_sd15()
    except Exception:
        pass
    try:
        from imagegen_plugins.pipelines.z_image_turbo import unload_pipeline as unload_z_image

        unload_z_image()
    except Exception:
        pass
    gc.collect()
    return True
