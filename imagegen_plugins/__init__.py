#!/usr/bin/env python3
"""
Optional local image generation plugins for Prowser.
Missing dependencies or imports fail silently (no Create menu).
"""

from __future__ import annotations

from typing import List

from imagegen_plugins.image_gen_registry import ImageGenModelPlugin


def discover_plugins() -> List[ImageGenModelPlugin]:
    """Return registered model plugins.

    Pipeline backends (e.g. mflux) may be missing; check ``ImageGenModelPlugin.is_available()``
    before starting generation.

    AI/dev: When adding a model, register it here and set ``function`` on the plugin
    (create | edit | expand | infill). The Create menu lists functions; the user picks
    the model in each function's dialog dropdown.
    """
    candidates: List[ImageGenModelPlugin] = []
    try:
        from imagegen_plugins.flux_schnell_mflux import FLUX_SCHNELL_MFLUX_PLUGIN

        candidates.append(FLUX_SCHNELL_MFLUX_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_sldr_nsfw_v2_lora import FLUX_SLDR_NSFW_V2_LORA_PLUGIN

        candidates.append(FLUX_SLDR_NSFW_V2_LORA_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.sana_sprint_600m import SANA_SPRINT_600M_PLUGIN

        candidates.append(SANA_SPRINT_600M_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.z_image_turbo_sdnq import Z_IMAGE_TURBO_SDNQ_PLUGIN

        candidates.append(Z_IMAGE_TURBO_SDNQ_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.realistic_vision_v4_sd15 import (
            REALISTIC_VISION_V4_SD15_PLUGIN,
        )

        candidates.append(REALISTIC_VISION_V4_SD15_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.anything_furry_sd15 import ANYTHING_FURRY_SD15_PLUGIN

        candidates.append(ANYTHING_FURRY_SD15_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_fill_expand import FLUX_FILL_EXPAND_PLUGIN

        candidates.append(FLUX_FILL_EXPAND_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_fill_infill import FLUX_FILL_INFILL_PLUGIN

        candidates.append(FLUX_FILL_INFILL_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_klein_create import (
            FLUX_KLEIN_4B_CREATE_PLUGIN,
            FLUX_KLEIN_9B_CREATE_PLUGIN,
            FLUX_KLEIN_9B_KV_CREATE_PLUGIN,
        )

        candidates.append(FLUX_KLEIN_4B_CREATE_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_CREATE_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_KV_CREATE_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_klein_edit import (
            FLUX_KLEIN_4B_EDIT_PLUGIN,
            FLUX_KLEIN_9B_EDIT_PLUGIN,
            FLUX_KLEIN_9B_KV_EDIT_PLUGIN,
        )

        candidates.append(FLUX_KLEIN_4B_EDIT_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_EDIT_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_KV_EDIT_PLUGIN)
    except ImportError:
        pass
    try:
        from imagegen_plugins.flux_klein_expand import (
            FLUX_KLEIN_4B_EXPAND_PLUGIN,
            FLUX_KLEIN_9B_EXPAND_PLUGIN,
            FLUX_KLEIN_9B_KV_EXPAND_PLUGIN,
        )

        candidates.append(FLUX_KLEIN_4B_EXPAND_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_EXPAND_PLUGIN)
        candidates.append(FLUX_KLEIN_9B_KV_EXPAND_PLUGIN)
    except ImportError:
        pass

    return candidates


def plugins_for_function(
    function: str,
    plugins: List[ImageGenModelPlugin] | None = None,
) -> List[ImageGenModelPlugin]:
    """Registered plugins eligible for a Create-menu function."""
    from imagegen_plugins.image_gen_active_model import FUNCTION_INFILL, FUNCTION_INFILL_PAINT

    if function == FUNCTION_INFILL_PAINT:
        function = FUNCTION_INFILL
    all_plugins = discover_plugins() if plugins is None else list(plugins)
    return [p for p in all_plugins if p.function == function]


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
