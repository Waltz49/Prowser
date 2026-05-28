#!/usr/bin/env python3
"""
PIL-only thumbnail loading for the non-Qt background worker.
Uses pil_image_io.open_pil_with_exif_correction (shared with exif_image_loader / face_engine).
SVG: not supported in background extraction (returns None).
"""

import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage


def _pil_rgba_to_rgb_thumbnail(pil_img: "PILImage.Image") -> "PILImage.Image":
    """Composite transparency onto solid gray (matches default UI transparency color roughly)."""
    from PIL import Image

    if pil_img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", pil_img.size, (98, 98, 98))
        if pil_img.mode == "RGBA":
            bg.paste(pil_img, mask=pil_img.split()[3])
        else:
            la = pil_img.convert("RGBA")
            bg.paste(la, mask=la.split()[3])
        return bg
    if pil_img.mode != "RGB":
        return pil_img.convert("RGB")
    return pil_img


def load_thumbnail_pil_with_exif_correction(
    image_path: str, size: int, ignore_exif: bool = False
) -> Optional["PILImage.Image"]:
    """
    Load a thumbnail as PIL Image with EXIF orientation applied (when ignore_exif is False).
    Returns None if loading fails. No Qt dependencies.
    """
    from PIL import Image

    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext == ".svg":
        return None

    from pil_image_io import open_pil_with_exif_correction

    pil_img = open_pil_with_exif_correction(
        image_path, ignore_exif=ignore_exif, cr2_half_size=True
    )
    if pil_img is None:
        return None
    pil_img = _pil_rgba_to_rgb_thumbnail(pil_img)
    pil_img.thumbnail((size, size), Image.Resampling.LANCZOS)
    return pil_img
