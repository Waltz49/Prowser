#!/usr/bin/env python3
"""Image-gen settings in ~/.prowser/data/settings.json (per dialog/function)."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from config import get_config

# Serialize imagegen settings writes (model params, LoRA catalog, active plugin, …).
_imagegen_settings_lock = threading.Lock()


def _ensure_imagegen_dict(settings: dict) -> dict:
    """Ensure settings['imagegen'] is a dict without dropping existing keys (e.g. lora_catalog)."""
    imagegen = settings.get("imagegen")
    if not isinstance(imagegen, dict):
        imagegen = {}
        settings["imagegen"] = imagegen
    return imagegen


def _mutate_imagegen_settings(mutator: Callable[[dict], None]) -> None:
    """Load settings, mutate imagegen under lock, save (avoids lost LoRA catalog updates)."""
    config = get_config()
    with _imagegen_settings_lock:
        settings = config.load_settings()
        imagegen = _ensure_imagegen_dict(settings)
        mutator(imagegen)
        config.save_settings(settings)


def _normalize_plugin_id(plugin_id: str) -> str:
    if plugin_id == "flux_fill_infil":
        return "flux_fill_infill"
    return plugin_id


_DIALOGS_KEY = "dialogs"
_LEGACY_MODELS_KEY = "models"

# Not shared across models in a function dialog (come from plugin model_defaults).
_PLUGIN_SPECIFIC_DIALOG_KEYS = frozenset(
    {
        "mflux_model_name",
        "hf_model_id",
        "source_image_path",
    }
)


def _sanitize_dialog_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v
        for k, v in dict(values).items()
        if k not in _PLUGIN_SPECIFIC_DIALOG_KEYS
    }


def _legacy_settings_for_function(function: str) -> Dict[str, Any]:
    """Merge legacy per-plugin settings into one function-level dict (shared prompt)."""
    from imagegen_plugins import plugins_for_function

    merged: Dict[str, Any] = {}
    for plugin in plugins_for_function(function):
        legacy = _sanitize_dialog_values(load_model_settings(plugin.plugin_id))
        if not legacy:
            continue
        prompt = (legacy.get("prompt") or "").strip()
        if prompt:
            merged["prompt"] = legacy["prompt"]
        for key, value in legacy.items():
            if key == "prompt":
                continue
            merged.setdefault(key, value)
    return merged


def _merge_shared_prompt_from_legacy(
    saved: Dict[str, Any],
    function: str,
    *,
    fallback_plugin_id: Optional[str],
) -> Dict[str, Any]:
    if (saved.get("prompt") or "").strip():
        return saved
    legacy = _legacy_settings_for_function(function)
    prompt = (legacy.get("prompt") or "").strip()
    if not prompt and fallback_plugin_id:
        single = _sanitize_dialog_values(load_model_settings(fallback_plugin_id))
        prompt = (single.get("prompt") or "").strip()
    if prompt:
        return {**saved, "prompt": prompt}
    return saved


def load_dialog_settings(
    function: str,
    *,
    fallback_plugin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Saved field values for a function dialog (create, edit, expand, …)."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    dialogs = imagegen.get(_DIALOGS_KEY) or {}
    saved = dict(dialogs.get(function) or {})
    if not saved:
        saved = _legacy_settings_for_function(function)
        if not saved and fallback_plugin_id:
            saved = _sanitize_dialog_values(load_model_settings(fallback_plugin_id))
    else:
        saved = _merge_shared_prompt_from_legacy(
            saved, function, fallback_plugin_id=fallback_plugin_id
        )
    return _sanitize_dialog_values(saved)


def save_dialog_settings(function: str, values: Dict[str, Any]) -> None:
    values = _sanitize_dialog_values(values)

    def mutate(imagegen: dict) -> None:
        dialogs = imagegen.get(_DIALOGS_KEY)
        if not isinstance(dialogs, dict):
            dialogs = {}
            imagegen[_DIALOGS_KEY] = dialogs
        dialogs[function] = values

    _mutate_imagegen_settings(mutate)


def load_model_settings(plugin_id: str) -> Dict[str, Any]:
    """Legacy per-plugin settings (used only when migrating to per-dialog storage)."""
    plugin_id = _normalize_plugin_id(plugin_id)
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    models = imagegen.get(_LEGACY_MODELS_KEY) or {}
    saved = dict(models.get(plugin_id) or {})
    if not saved and plugin_id == "flux_fill_infill":
        saved = dict(models.get("flux_fill_infil") or {})
    return saved


def save_model_settings(plugin_id: str, values: Dict[str, Any]) -> None:
    """Legacy per-plugin save — prefer :func:`save_dialog_settings`."""
    plugin_id = _normalize_plugin_id(plugin_id)
    values = dict(values)

    def mutate(imagegen: dict) -> None:
        models = imagegen.get(_LEGACY_MODELS_KEY)
        if not isinstance(models, dict):
            models = {}
            imagegen[_LEGACY_MODELS_KEY] = models
        models[plugin_id] = values

    _mutate_imagegen_settings(mutate)


def load_imagegen_dialog_geometry_hex() -> Optional[str]:
    """Saved image-generation prompt dialog geometry (hex QByteArray), if any."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    geom = imagegen.get("dialog_geometry")
    return geom if isinstance(geom, str) and geom else None


def save_imagegen_dialog_geometry_hex(geom_hex: str) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["dialog_geometry"] = geom_hex

    _mutate_imagegen_settings(mutate)


def load_job_queue_geometry_hex() -> Optional[str]:
    """Saved job queue dialog geometry (hex QByteArray), if any."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    geom = imagegen.get("job_queue_geometry")
    return geom if isinstance(geom, str) and geom else None


def save_job_queue_geometry_hex(geom_hex: str) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["job_queue_geometry"] = geom_hex

    _mutate_imagegen_settings(mutate)


def load_infill_paint_dialog_geometry_hex() -> Optional[str]:
    """Saved infill-by-painting dialog geometry (hex QByteArray), if any."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    geom = imagegen.get("infill_paint_dialog_geometry")
    return geom if isinstance(geom, str) and geom else None


def save_infill_paint_dialog_geometry_hex(geom_hex: str) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["infill_paint_dialog_geometry"] = geom_hex

    _mutate_imagegen_settings(mutate)


def load_lora_catalog_enabled_ids() -> list:
    from imagegen_plugins.flux_lora_catalog import DEFAULT_ENABLED_LORA_IDS, FLUX_LORA_CATALOG

    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    lc = imagegen.get("lora_catalog") or {}
    raw = lc.get("enabled_ids")
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x) in FLUX_LORA_CATALOG]
    return list(DEFAULT_ENABLED_LORA_IDS)


def load_lora_catalog_deleted_ids() -> list:
    from imagegen_plugins.flux_lora_catalog import deleted_lora_ids

    return sorted(deleted_lora_ids(get_config().load_settings()))


def save_lora_catalog_enabled_ids(enabled_ids: list) -> None:
    save_lora_catalog_state(enabled_ids=enabled_ids)


def load_lora_catalog_model_support() -> dict:
    from imagegen_plugins.flux_lora_catalog import lora_model_support

    return {
        lid: list(models)
        for lid, models in lora_model_support(get_config().load_settings()).items()
    }


def save_lora_catalog_state(
    *,
    enabled_ids: Optional[list] = None,
    deleted_ids: Optional[list] = None,
    model_support: Optional[dict] = None,
) -> None:
    from imagegen_plugins.flux_lora_catalog import FLUX_LORA_CATALOG, LORA_PROBE_MODEL_ORDER

    def mutate(imagegen: dict) -> None:
        lc = imagegen.get("lora_catalog")
        if not isinstance(lc, dict):
            lc = {}
            imagegen["lora_catalog"] = lc
        if enabled_ids is not None:
            lc["enabled_ids"] = [str(x) for x in enabled_ids if str(x) in FLUX_LORA_CATALOG]
        if deleted_ids is not None:
            lc["deleted_ids"] = [str(x) for x in deleted_ids if str(x) in FLUX_LORA_CATALOG]
        if model_support is not None:
            cleaned: dict = {}
            allowed = set(LORA_PROBE_MODEL_ORDER)
            for lid, models in model_support.items():
                lid_s = str(lid)
                if lid_s not in FLUX_LORA_CATALOG:
                    continue
                if not isinstance(models, (list, tuple)):
                    continue
                cleaned[lid_s] = [
                    str(m)
                    for m in models
                    if str(m) in allowed
                ]
            lc["model_support"] = cleaned

    _mutate_imagegen_settings(mutate)
