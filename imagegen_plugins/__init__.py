#!/usr/bin/env python3
"""
Optional local image generation plugins for Prowser.
Missing dependencies or imports are skipped (no Create menu); failures log at debug.
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict, List, Optional, Tuple

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

_log = logging.getLogger(__name__)

_discovered_plugins: Optional[List[ImageGenModelPlugin]] = None
_plugins_by_function: Optional[Dict[str, List[ImageGenModelPlugin]]] = None
_plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None
_plugins_by_hf_model_id: Optional[Dict[str, List[ImageGenModelPlugin]]] = None

# module path -> plugin constant names exported by that module
_PLUGIN_REGISTRATIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("imagegen_plugins.flux_schnell_mflux", ("FLUX_SCHNELL_MFLUX_PLUGIN",)),
    ("imagegen_plugins.flux_sldr_nsfw_v2_lora", ("FLUX_SLDR_NSFW_V2_LORA_PLUGIN",)),
    ("imagegen_plugins.sana_sprint_600m", ("SANA_SPRINT_600M_PLUGIN",)),
    ("imagegen_plugins.z_image_turbo_sdnq", ("Z_IMAGE_TURBO_SDNQ_PLUGIN",)),
    ("imagegen_plugins.z_image_turbo_mflux_4bit", ("Z_IMAGE_TURBO_MFLUX_4BIT_PLUGIN",)),
    ("imagegen_plugins.realistic_vision_v4_sd15", ("REALISTIC_VISION_V4_SD15_PLUGIN",)),
    ("imagegen_plugins.anything_furry_sd15", ("ANYTHING_FURRY_SD15_PLUGIN",)),
    ("imagegen_plugins.sdxl_base_plugin", ("SDXL_BASE_1_0_PLUGIN",)),
    ("imagegen_plugins.flux_fill_expand", ("FLUX_FILL_EXPAND_PLUGIN",)),
    ("imagegen_plugins.flux_fill_infill", ("FLUX_FILL_INFILL_PLUGIN",)),
    (
        "imagegen_plugins.flux_klein_create",
        (
            "FLUX_KLEIN_4B_CREATE_PLUGIN",
            "FLUX_KLEIN_9B_CREATE_PLUGIN",
            "FLUX_KLEIN_9B_KV_CREATE_PLUGIN",
        ),
    ),
    (
        "imagegen_plugins.flux_klein_edit",
        (
            "FLUX_KLEIN_4B_EDIT_PLUGIN",
            "FLUX_KLEIN_9B_EDIT_PLUGIN",
            "FLUX_KLEIN_9B_KV_EDIT_PLUGIN",
        ),
    ),
    (
        "imagegen_plugins.flux_klein_expand",
        (
            "FLUX_KLEIN_4B_EXPAND_PLUGIN",
            "FLUX_KLEIN_9B_EXPAND_PLUGIN",
            "FLUX_KLEIN_9B_KV_EXPAND_PLUGIN",
        ),
    ),
    (
        "imagegen_plugins.flux_klein_sceneworks",
        (
            "SCENEWORKS_KLEIN_9B_KV_MLX_CREATE_PLUGIN",
            "SCENEWORKS_KLEIN_9B_KV_MLX_EDIT_PLUGIN",
            "SCENEWORKS_KLEIN_9B_KV_MLX_EXPAND_PLUGIN",
        ),
    ),
)


def _build_plugin_indexes(candidates: List[ImageGenModelPlugin]) -> None:
    global _plugins_by_function, _plugins_by_id, _plugins_by_hf_model_id
    from imagegen_plugins.image_gen_active_model import (
        FUNCTION_INFILL,
        FUNCTION_INFILL_PAINT,
    )

    by_function: Dict[str, List[ImageGenModelPlugin]] = {}
    by_id: Dict[str, ImageGenModelPlugin] = {}
    by_hf: Dict[str, List[ImageGenModelPlugin]] = {}
    for plugin in candidates:
        by_id[plugin.plugin_id] = plugin
        by_function.setdefault(plugin.function, []).append(plugin)
        hf = (getattr(plugin, "hf_model_id", None) or "").strip()
        if hf:
            by_hf.setdefault(hf, []).append(plugin)
    by_function[FUNCTION_INFILL_PAINT] = list(by_function.get(FUNCTION_INFILL, []))
    _plugins_by_function = by_function
    _plugins_by_id = by_id
    _plugins_by_hf_model_id = by_hf


def _load_registered_plugins() -> List[ImageGenModelPlugin]:
    candidates: List[ImageGenModelPlugin] = []
    for module_name, attr_names in _PLUGIN_REGISTRATIONS:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            _log.debug("Imagegen plugin module %s not loaded: %s", module_name, exc)
            continue
        for attr_name in attr_names:
            try:
                plugin = getattr(module, attr_name)
            except AttributeError as exc:
                _log.debug(
                    "Imagegen plugin %s.%s not found: %s",
                    module_name,
                    attr_name,
                    exc,
                )
                continue
            if not isinstance(plugin, ImageGenModelPlugin):
                _log.debug(
                    "Imagegen plugin %s.%s is not an ImageGenModelPlugin: %r",
                    module_name,
                    attr_name,
                    type(plugin),
                )
                continue
            candidates.append(plugin)
    return candidates


def discover_plugins() -> List[ImageGenModelPlugin]:
    """Return registered model plugins.

    Pipeline backends (e.g. mflux) may be missing; check ``ImageGenModelPlugin.is_available()``
    before starting generation.

    AI/dev: When adding a model, append its module and constant name(s) to
    ``_PLUGIN_REGISTRATIONS`` and set ``function`` on the plugin
    (create | edit | expand | infill). The Create menu lists functions; the user picks
    the model in each function's dialog dropdown.
    """
    global _discovered_plugins
    if _discovered_plugins is not None:
        return list(_discovered_plugins)

    candidates = _load_registered_plugins()
    _discovered_plugins = candidates
    _build_plugin_indexes(candidates)
    return list(candidates)


def plugin_by_id(plugin_id: str) -> ImageGenModelPlugin | None:
    """Lookup a registered plugin by id (empty when discovery has not run)."""
    discover_plugins()
    if _plugins_by_id is None:
        return None
    return _plugins_by_id.get(plugin_id)


def plugins_by_hf_model_id(hf_model_id: str) -> List[ImageGenModelPlugin]:
    """Registered plugins sharing a Hugging Face model id."""
    mk = (hf_model_id or "").strip()
    if not mk:
        return []
    discover_plugins()
    if _plugins_by_hf_model_id is None:
        return []
    return list(_plugins_by_hf_model_id.get(mk, ()))


def plugins_for_function(
    function: str,
    plugins: List[ImageGenModelPlugin] | None = None,
) -> List[ImageGenModelPlugin]:
    """Registered plugins eligible for a Create-menu function."""
    from imagegen_plugins.image_gen_active_model import FUNCTION_INFILL, FUNCTION_INFILL_PAINT

    if function == FUNCTION_INFILL_PAINT:
        function = FUNCTION_INFILL
    if plugins is not None:
        return [p for p in plugins if p.function == function]
    discover_plugins()
    if _plugins_by_function is None:
        return []
    return list(_plugins_by_function.get(function, ()))


def create_menu_plugins(
    plugins: List[ImageGenModelPlugin] | None = None,
) -> List[ImageGenModelPlugin]:
    """All registered model plugins (any function)."""
    return discover_plugins() if plugins is None else list(plugins)


def function_has_plugins(
    function: str,
    plugins: List[ImageGenModelPlugin] | None = None,
) -> bool:
    return bool(plugins_for_function(function, plugins))
