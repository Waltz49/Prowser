#!/usr/bin/env python3
"""Fit edit sources to the first image's exact size (white borders, centered)."""

from __future__ import annotations

import os
from typing import List, Tuple

from prowser_temp_files import prowser_mkstemp_path

from PIL import Image

SCREEN_SIZE_EXPERIMENTAL_PROMPT_SUFFIX = (
    ""
)


def _fit_dimensions(
    w: int, h: int, ref_w: int, ref_h: int, *, allow_upscale: bool = False
) -> tuple[int, int]:
    """Aspect-preserving size so w×h fits inside ref_w×ref_h (contain).

    When allow_upscale is False, only shrinks (multi-image aspect padding).
    When True, matches screen-size copy / wallpaper contain (may enlarge).
    """
    if w <= 0 or h <= 0:
        return max(1, ref_w), max(1, ref_h)
    scale = min(ref_w / w, ref_h / h)
    if not allow_upscale:
        scale = min(scale, 1.0)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def create_edit_aspect_pad_temp_path() -> str:
    return prowser_mkstemp_path(
        prefix="imagegen-edit-aspect-pad-",
        suffix=".png",
    )


def screen_size_edit_target_dimensions() -> tuple[int, int]:
    """Target canvas for Screen Size (Experimental).

    Uses the primary display size today; callers can later pass explicit width/height.
    """
    from screen_size_copy import get_physical_screen_size

    screen_size = get_physical_screen_size()
    return max(1, int(screen_size.width())), max(1, int(screen_size.height()))


def remove_edit_aspect_pad_temp(path: str) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def remove_edit_aspect_pad_temps(paths: List[str]) -> None:
    for path in paths:
        remove_edit_aspect_pad_temp(path)


def save_fitted_to_reference_size(
    source_path: str,
    ref_w: int,
    ref_h: int,
    *,
    allow_upscale: bool = False,
) -> str:
    """Place source on a ref_w×ref_h white canvas (contain: fit inside, centered)."""
    image = Image.open(source_path)
    try:
        rgb = image.convert("RGB")
        w, h = rgb.size
        fit_w, fit_h = _fit_dimensions(w, h, ref_w, ref_h, allow_upscale=allow_upscale)
        if fit_w != w or fit_h != h:
            rgb = rgb.resize((fit_w, fit_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (ref_w, ref_h), (255, 255, 255))
        canvas.paste(rgb, ((ref_w - fit_w) // 2, (ref_h - fit_h) // 2))
        out_path = create_edit_aspect_pad_temp_path()
        canvas.save(out_path)
        os.chmod(out_path, 0o600)
        return out_path
    finally:
        image.close()


def generator_paths_with_screen_size_expansion(
    source_paths: List[str],
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> Tuple[List[str], List[str]]:
    """Replace index 0 with a contain-fit temp at the target canvas size.

    The generator receives the temp file; callers should keep the original
    source_paths for EXIF references.

    Returns (generator_paths, temp_paths_to_delete).
    """
    if not source_paths:
        return [], []
    originals = [os.path.normpath(os.path.abspath(p)) for p in source_paths]
    if target_width is not None and target_height is not None:
        ref_w = max(1, int(target_width))
        ref_h = max(1, int(target_height))
    else:
        ref_w, ref_h = screen_size_edit_target_dimensions()

    with Image.open(originals[0]) as ref_im:
        w, h = ref_im.size
    if w == ref_w and h == ref_h:
        return list(originals), []

    fitted = save_fitted_to_reference_size(
        originals[0], ref_w, ref_h, allow_upscale=True
    )
    return [fitted, *originals[1:]], [fitted]


def generator_paths_with_aspect_padding(
    source_paths: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Paths for the image generator (index 0 unchanged; later images fitted to its size).

    Returns (generator_paths, temp_paths_to_delete).
    """
    if not source_paths:
        return [], []
    originals = [os.path.normpath(os.path.abspath(p)) for p in source_paths]
    if len(originals) == 1:
        return list(originals), []

    with Image.open(originals[0]) as ref_im:
        ref_w, ref_h = ref_im.size

    out: List[str] = [originals[0]]
    temps: List[str] = []
    for path in originals[1:]:
        with Image.open(path) as im:
            w, h = im.size
        if w == ref_w and h == ref_h:
            out.append(path)
            continue
        fitted = save_fitted_to_reference_size(path, ref_w, ref_h)
        out.append(fitted)
        temps.append(fitted)
    return out, temps
