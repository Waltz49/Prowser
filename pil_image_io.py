#!/usr/bin/env python3
"""
Shared PIL open + EXIF orientation logic for Qt loaders, background workers, and face/ML code.

SVG: PIL cannot open SVG; open_pil_with_exif_correction returns None — callers using Qt handle .svg separately.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from PIL import Image as PILImage

_MODULE_HEIF_REGISTERED = False


def register_heif_opener() -> None:
    """Register pillow_heif once so PIL can open HEIC/HEIF."""
    global _MODULE_HEIF_REGISTERED
    if _MODULE_HEIF_REGISTERED:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass
    _MODULE_HEIF_REGISTERED = True


def apply_pil_exif_orientation(
    pil_img: "PILImage.Image", *, ignore_exif: bool = False
) -> "PILImage.Image":
    """
    Apply EXIF orientation to an already-open PIL image (same rules as exif_image_loader / worker).

    When ignore_exif is True, only loads pixel data and returns the same image object.
    """
    from PIL import ImageOps

    if ignore_exif:
        pil_img.load()
        return pil_img

    orientation = None
    try:
        from exif.exif_utils import get_exif_orientation_from_pil

        orientation = get_exif_orientation_from_pil(pil_img)
    except Exception:
        orientation = None

    needs_orientation = orientation is not None and orientation != 1
    if needs_orientation:
        return ImageOps.exif_transpose(pil_img)
    pil_img.load()
    return pil_img


def open_pil_with_exif_correction(
    image_path: str,
    *,
    ignore_exif: bool = False,
    cr2_half_size: bool = False,
) -> Optional["PILImage.Image"]:
    """
    Open a file as PIL Image with optional EXIF orientation correction.

    Returns None if the path cannot be decoded as PIL (including .svg), or on error.
    CR2: uses rawpy when available; returns None if rawpy missing or decode fails (caller may Qt-fallback).
    """
    from PIL import Image

    register_heif_opener()

    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext == ".svg":
        return None

    try:
        from files.cr2_raw_loader import is_cr2_path, decode_cr2_to_pil, rawpy_available

        if is_cr2_path(image_path):
            if not rawpy_available():
                return None
            pil_img = decode_cr2_to_pil(image_path, half_size=cr2_half_size)
            if pil_img is None:
                return None
            if not ignore_exif:
                from exif.exif_utils import get_exif_orientation_from_path, apply_exif_orientation_to_pil

                orientation = get_exif_orientation_from_path(image_path)
                if orientation is not None and orientation != 1:
                    pil_img = apply_exif_orientation_to_pil(pil_img, orientation)
            pil_img.load()
            return pil_img.copy()

        with Image.open(image_path) as pil_img:
            if ignore_exif:
                pil_img.load()
                return pil_img.copy()
            oriented = apply_pil_exif_orientation(pil_img, ignore_exif=False)
            return oriented.copy()

    except Exception:
        return None
