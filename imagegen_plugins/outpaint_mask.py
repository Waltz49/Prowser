#!/usr/bin/env python3
"""
Canvas + mask preparation for graphical outfill placement.

Mask convention: white = generate, black = keep (PIL mode L).
"""

from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageDraw


def clamp_outpaint_dims(width: int, height: int, *, max_side: int = 1024) -> Tuple[int, int]:
    """Round to 32px and cap for 16GB-class Macs."""
    w = max(128, min(max_side, round(width / 32) * 32))
    h = max(128, min(max_side, round(height / 32) * 32))
    return w, h


def fit_infill_paint_dims(width: int, height: int, *, max_side: int = 1024) -> Tuple[int, int]:
    """Working size for infill-by-painting canvas and exports (aspect-preserving)."""
    return fit_edit_output_dims(
        width,
        height,
        max_side=max_side,
        step=16,
        min_side=256,
    )


def fit_edit_output_dims(
    width: int,
    height: int,
    *,
    max_side: int = 1024,
    step: int = 16,
    min_side: int = 128,
) -> Tuple[int, int]:
    """Preserve aspect ratio; align to step; scale down if either side exceeds max_side."""
    w, h = int(width), int(height)
    if w <= 0 or h <= 0:
        side = max(min_side, min(max_side, step * 64))
        return side, side
    scale = min(1.0, max_side / max(w, h))
    w = max(min_side, int(round(w * scale)))
    h = max(min_side, int(round(h * scale)))
    w = max(min_side, w - (w % step))
    h = max(min_side, h - (h % step))
    return w, h


def compute_fit_placed_size(
    image: Image.Image,
    target_width: int,
    target_height: int,
) -> Tuple[int, int]:
    """Size of source after fit-to-canvas at 100% (before explicit placement)."""
    scale_factor = min(target_width / image.width, target_height / image.height)
    new_width = max(128, int(image.width * scale_factor))
    new_height = max(128, int(image.height * scale_factor))
    return new_width, new_height


def prepare_image_and_mask_at_rect(
    image: Image.Image,
    canvas_w: int,
    canvas_h: int,
    x: int,
    y: int,
    w: int,
    h: int,
    overlap_percentage: int,
) -> Tuple[Image.Image, Image.Image]:
    """Place resized source at (x,y,w,h) on target canvas; return (background RGB, mask L)."""
    target_size = (canvas_w, canvas_h)
    x = max(0, min(int(x), canvas_w - 1))
    y = max(0, min(int(y), canvas_h - 1))
    w = max(128, min(int(w), canvas_w - x))
    h = max(128, min(int(h), canvas_h - y))

    source = image.resize((w, h), Image.LANCZOS)
    background = Image.new("RGB", target_size, (255, 255, 255))
    background.paste(source, (x, y))

    overlap_x = max(1, int(w * (overlap_percentage / 100)))
    overlap_y = max(1, int(h * (overlap_percentage / 100)))
    white_gaps_patch = 2

    left_overlap = x + overlap_x
    right_overlap = x + w - overlap_x
    top_overlap = y + overlap_y
    bottom_overlap = y + h - overlap_y

    left_overlap = max(x + white_gaps_patch, left_overlap)
    right_overlap = min(x + w - white_gaps_patch, right_overlap)
    top_overlap = max(y + white_gaps_patch, top_overlap)
    bottom_overlap = min(y + h - white_gaps_patch, bottom_overlap)

    mask = Image.new("L", target_size, 255)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rectangle(
        [(left_overlap, top_overlap), (right_overlap, bottom_overlap)],
        fill=0,
    )
    return background, mask


def composite_masked_regions_for_klein_edit(
    background: Image.Image,
    mask: Image.Image,
    *,
    fill_rgb: tuple[int, int, int] = (128, 128, 128),
) -> Image.Image:
    """RGB composite for Klein edit: white mask regions → neutral fill, black → keep."""
    bg = background.convert("RGB")
    m = mask.convert("L")
    if m.size != bg.size:
        m = m.resize(bg.size, Image.Resampling.LANCZOS)
    fill = Image.new("RGB", bg.size, fill_rgb)
    return Image.composite(fill, bg, m)
