#!/usr/bin/env python3
"""Active image-gen model per function (Create menu) + last-used function for ⌥/."""

from __future__ import annotations

from typing import Dict, List, Optional

from config import get_config
from imagegen_plugins.image_gen_persistence import _mutate_imagegen_settings
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

FUNCTION_CREATE = "create"
FUNCTION_EDIT = "edit"
FUNCTION_EXPAND = "expand"
FUNCTION_INFILL = "infill"
FUNCTION_INFILL_PAINT = "infill_paint"

IMAGEGEN_FUNCTIONS = (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)

_ACTIVE_BY_FUNCTION_KEY = "active_plugin_by_function"
_LAST_FUNCTION_KEY = "last_function"
_LEGACY_ACTIVE_KEY = "active_plugin_id"


def _plugins_by_id(plugins: List[ImageGenModelPlugin]) -> Dict[str, ImageGenModelPlugin]:
    return {p.plugin_id: p for p in plugins}


def _normalize_plugin_id(plugin_id: str) -> str:
    if plugin_id == "flux_fill_infil":
        return "flux_fill_infill"
    return plugin_id


def _imagegen_settings() -> dict:
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen")
    if not isinstance(imagegen, dict):
        imagegen = {}
        settings["imagegen"] = imagegen
    return imagegen


def _active_by_function_raw(imagegen: dict) -> dict:
    raw = imagegen.get(_ACTIVE_BY_FUNCTION_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    legacy = imagegen.get(_LEGACY_ACTIVE_KEY)
    if isinstance(legacy, str):
        return {FUNCTION_CREATE: _normalize_plugin_id(legacy)}
    return {}


def load_active_plugin_id_for_function(
    function: str,
    plugins: List[ImageGenModelPlugin],
) -> Optional[str]:
    """Return persisted active plugin id for a function if still registered and available."""
    if not plugins:
        return None
    known = _plugins_by_id(plugins)
    by_fn = _active_by_function_raw(_imagegen_settings())
    plugin_id = by_fn.get(function)
    if isinstance(plugin_id, str):
        plugin_id = _normalize_plugin_id(plugin_id)
        plugin = known.get(plugin_id)
        if plugin is not None and plugin.is_available():
            return plugin_id
    for plugin in plugins:
        if plugin.function == function and plugin.is_available():
            return plugin.plugin_id
    for plugin in plugins:
        if plugin.function == function:
            return plugin.plugin_id
    return None


def apply_active_plugin_to_imagegen(
    imagegen: dict, function: str, plugin_id: str
) -> None:
    """Update active plugin id for a function inside an in-memory imagegen dict."""
    plugin_id = _normalize_plugin_id(plugin_id)
    by_fn = _active_by_function_raw(imagegen)
    by_fn[function] = plugin_id
    imagegen[_ACTIVE_BY_FUNCTION_KEY] = by_fn


def save_active_plugin_id_for_function(function: str, plugin_id: str) -> None:
    def mutate(imagegen: dict) -> None:
        apply_active_plugin_to_imagegen(imagegen, function, plugin_id)

    _mutate_imagegen_settings(mutate)


def load_last_function() -> str:
    imagegen = _imagegen_settings()
    fn = imagegen.get(_LAST_FUNCTION_KEY)
    if isinstance(fn, str) and fn in IMAGEGEN_FUNCTIONS:
        return fn
    return FUNCTION_EDIT


def save_last_function(function: str) -> None:
    if function not in IMAGEGEN_FUNCTIONS:
        return

    def mutate(imagegen: dict) -> None:
        imagegen[_LAST_FUNCTION_KEY] = function

    _mutate_imagegen_settings(mutate)


def remember_last_function(main_window, function: str) -> None:
    """Persist and cache the last image-gen function (⌥/ target)."""
    if function not in IMAGEGEN_FUNCTIONS:
        return
    save_last_function(function)
    if main_window is not None:
        main_window._imagegen_last_function = function


def effective_last_function(main_window=None) -> str:
    """Last function for ⌥/: in-memory cache first, then settings."""
    if main_window is not None:
        cached = getattr(main_window, "_imagegen_last_function", None)
        if isinstance(cached, str) and cached in IMAGEGEN_FUNCTIONS:
            return cached
    return load_last_function()



def set_active_plugin_for_function(
    main_window,
    function: str,
    plugin: ImageGenModelPlugin,
) -> None:
    by_fn = getattr(main_window, "imagegen_active_plugin_by_function", None)
    if not isinstance(by_fn, dict):
        by_fn = {}
        main_window.imagegen_active_plugin_by_function = by_fn
    by_fn[function] = plugin.plugin_id
    save_active_plugin_id_for_function(function, plugin.plugin_id)
