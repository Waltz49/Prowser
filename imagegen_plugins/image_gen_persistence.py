#!/usr/bin/env python3
"""Per-model imagegen settings in ~/.prowser/data/settings.json."""

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


def load_model_settings(plugin_id: str) -> Dict[str, Any]:
    plugin_id = _normalize_plugin_id(plugin_id)
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    models = imagegen.get("models") or {}
    saved = dict(models.get(plugin_id) or {})
    if not saved and plugin_id == "flux_fill_infill":
        saved = dict(models.get("flux_fill_infil") or {})
    return saved


def save_model_settings(plugin_id: str, values: Dict[str, Any]) -> None:
    plugin_id = _normalize_plugin_id(plugin_id)
    values = dict(values)

    def mutate(imagegen: dict) -> None:
        models = imagegen.get("models")
        if not isinstance(models, dict):
            models = {}
            imagegen["models"] = models
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
