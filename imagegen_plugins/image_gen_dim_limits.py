#!/usr/bin/env python3
"""App-wide image generation settings and per-model dimension limits."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

APP_MAX_GENERATION_DIMENSION_DEFAULT = 1024
APP_MAX_GENERATION_DIMENSION_MIN = 256
APP_MAX_GENERATION_DIMENSION_CEILING = 2048
APP_MAX_GENERATION_DIMENSION_STEP = 16

APP_SERIES_COOLDOWN_SECONDS_DEFAULT = 60
APP_SERIES_COOLDOWN_SECONDS_MIN = 0
APP_SERIES_COOLDOWN_SECONDS_MAX = 120

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin


def align_generation_dimension(value: int) -> int:
    """Snap a max-edge value to the configured step and clamp range."""
    step = APP_MAX_GENERATION_DIMENSION_STEP
    v = int(value)
    v = max(APP_MAX_GENERATION_DIMENSION_MIN, min(APP_MAX_GENERATION_DIMENSION_CEILING, v))
    v = v - (v % step)
    return max(APP_MAX_GENERATION_DIMENSION_MIN, v)


def app_series_cooldown_seconds(settings: Optional[Dict[str, Any]] = None) -> int:
    """Seconds to wait between images in a multi-copy generation series."""
    raw = APP_SERIES_COOLDOWN_SECONDS_DEFAULT
    if settings is not None:
        try:
            raw = int(settings.get("imagegen_series_cooldown_seconds", raw))
        except (TypeError, ValueError):
            raw = APP_SERIES_COOLDOWN_SECONDS_DEFAULT
    return max(
        APP_SERIES_COOLDOWN_SECONDS_MIN,
        min(APP_SERIES_COOLDOWN_SECONDS_MAX, raw),
    )


def app_max_generation_dimension(settings: Optional[Dict[str, Any]] = None) -> int:
    """Read the app-wide max generation edge from settings."""
    raw = APP_MAX_GENERATION_DIMENSION_DEFAULT
    if settings is not None:
        try:
            raw = int(settings.get("imagegen_max_generation_dimension", raw))
        except (TypeError, ValueError):
            raw = APP_MAX_GENERATION_DIMENSION_DEFAULT
    return align_generation_dimension(raw)


def effective_max_generation_dimension(
    plugin_max: int,
    settings: Optional[Dict[str, Any]] = None,
) -> int:
    """Lesser of per-model max and app-wide max."""
    try:
        model_max = align_generation_dimension(int(plugin_max))
    except (TypeError, ValueError):
        model_max = APP_MAX_GENERATION_DIMENSION_DEFAULT
    app_max = app_max_generation_dimension(settings)
    return min(model_max, app_max)


def effective_max_for_plugin(plugin: ImageGenModelPlugin) -> int:
    from config import get_config

    return effective_max_generation_dimension(
        plugin.max_generation_dimension,
        get_config().load_settings(),
    )


def payload_max_generation_dimension(payload: Dict[str, Any]) -> int:
    """Max edge from worker payload; fallback to app default."""
    try:
        raw = int(payload.get("max_generation_dimension", APP_MAX_GENERATION_DIMENSION_DEFAULT))
    except (TypeError, ValueError):
        raw = APP_MAX_GENERATION_DIMENSION_DEFAULT
    return align_generation_dimension(raw)
