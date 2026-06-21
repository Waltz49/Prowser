#!/usr/bin/env python3
"""Image extension sets and MIN_THUMBNAIL_SIZE (no Qt) — used by worker and thumbnail_constants."""

from functools import lru_cache
from typing import Set

MIN_THUMBNAIL_SIZE = 150

IMAGE_EXTENSIONS: Set[str] = {
    ".bmp",
    ".cr2",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}


@lru_cache(maxsize=1)
def get_image_extensions() -> Set[str]:
    try:
        from config import get_config

        config = get_config()
        settings = config.load_settings()
        extensions = settings.get("image_extensions", [".jpg", ".jpeg", ".png", ".webp"])
        if not isinstance(extensions, list):
            extensions = [".jpg", ".jpeg", ".png", ".webp"]
        return set(ext.lower() for ext in extensions if ext)
    except Exception:
        return {".jpg", ".jpeg", ".png", ".webp"}


def clear_image_extensions_cache() -> None:
    get_image_extensions.cache_clear()
