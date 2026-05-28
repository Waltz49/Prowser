#!/usr/bin/env python3
"""
Canon CR2 (RAW) decode via LibRaw (rawpy). Optional dependency: if rawpy is missing,
CR2 files are treated as unsupported at decode sites that check rawpy_available().
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from PIL import Image


def is_cr2_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".cr2"


def rawpy_available() -> bool:
    try:
        import rawpy  # noqa: F401
        return True
    except ImportError:
        return False


def decode_cr2_to_pil(path: str, *, half_size: bool = False) -> Optional[Image.Image]:
    """Decode CR2 to RGB PIL Image. Returns None on failure or if rawpy is not installed."""
    if not rawpy_available():
        return None
    import rawpy

    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=half_size,
                no_auto_bright=False,
                output_bps=8,
            )
        return Image.fromarray(rgb)
    except Exception:
        return None


def get_cr2_dimensions_from_raw(path: str) -> Optional[Tuple[int, int]]:
    """Return (width, height) from LibRaw header without full postprocess."""
    if not rawpy_available():
        return None
    import rawpy

    try:
        with rawpy.imread(path) as raw:
            w = int(raw.sizes.width)
            h = int(raw.sizes.height)
            if w > 0 and h > 0:
                return (w, h)
    except Exception:
        pass
    return None
