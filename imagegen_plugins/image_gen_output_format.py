#!/usr/bin/env python3
"""Output format helpers for image generation (PNG / WebP)."""

from __future__ import annotations

import os
from typing import Any, Dict

OUTPUT_FORMAT_CHOICES = ("png", "webp")
DEFAULT_OUTPUT_FORMAT = "png"


def normalize_output_format(value: Any) -> str:
    fmt = str(value or DEFAULT_OUTPUT_FORMAT).lstrip(".").lower()
    if fmt in OUTPUT_FORMAT_CHOICES:
        return fmt
    return DEFAULT_OUTPUT_FORMAT


def load_output_format(settings: dict[str, Any] | None = None) -> str:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    return normalize_output_format(settings.get("imagegen_output_format"))


def output_extension_from_settings(settings: dict[str, Any] | None = None) -> str:
    return f".{load_output_format(settings)}"


def mflux_temp_suffix_for_output_path(output_path: str) -> str:
    return os.path.splitext(output_path)[1] or ".png"


def pil_save_kwargs_for_path(path: str) -> Dict[str, Any]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".webp":
        return {"quality": 95, "method": 6}
    return {}


def save_generation_image(image: Any, output_path: str) -> None:
    """Save a PIL image to the generation output path with format-appropriate kwargs."""
    image.save(output_path, **pil_save_kwargs_for_path(output_path))
