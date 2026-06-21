#!/usr/bin/env python3
"""
Single entry for slideshow pixmap loads.

All slideshow modes must use this helper so EXIF/SVG/CR2 policy stays aligned with
exif_image_loader.load_image_with_exif_correction (one place to swap for native later).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QPixmap


def load_slideshow_pixmap(image_path: str, *, ignore_exif: bool = False) -> Optional[QPixmap]:
    """Load a full-size pixmap for slideshow display (EXIF-corrected unless ignore_exif)."""
    from exif.exif_image_loader import load_image_with_exif_correction

    return load_image_with_exif_correction(str(image_path), ignore_exif=ignore_exif)
