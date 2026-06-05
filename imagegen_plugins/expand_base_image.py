#!/usr/bin/env python3
"""Prepare the expand fill base image (source placed on canvas) in a temp file."""

from __future__ import annotations

import os
from typing import Any, Dict

from prowser_temp_files import prowser_mkstemp_path

from PIL import Image

from imagegen_plugins.outpaint_mask import clamp_outpaint_dims, prepare_image_and_mask_at_rect


def create_expand_base_temp_path() -> str:
    """Unique expand fill input path under the configured temp directory."""
    return prowser_mkstemp_path(
        prefix="imagegen-expand-base-",
        suffix=".png",
    )


def remove_expand_base_temp(path: str) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def prepare_and_save_expand_base(values: Dict[str, Any], output_path: str) -> str:
    """Build the fill input image and save it to a private temp file."""
    _ = output_path  # caller API; temp path uses configured Prowser temp directory
    source_path = str(values.get("source_image_path") or "")
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("source_image_path is required and must exist")

    w, h = clamp_outpaint_dims(int(values["width"]), int(values["height"]))
    px = int(values.get("placement_x", 0))
    py = int(values.get("placement_y", 0))
    pw = int(values.get("placement_w", w))
    ph = int(values.get("placement_h", h))
    overlap = max(0, min(20, int(values.get("overlap_percentage", 2))))

    image = Image.open(source_path).convert("RGB")
    try:
        background, _mask = prepare_image_and_mask_at_rect(
            image, w, h, px, py, pw, ph, overlap
        )
    finally:
        image.close()

    base_path = create_expand_base_temp_path()
    background.save(base_path)
    os.chmod(base_path, 0o600)
    return base_path
