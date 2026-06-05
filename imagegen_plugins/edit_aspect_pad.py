#!/usr/bin/env python3
"""Fit edit sources to the first image's exact size (white borders, centered)."""

from __future__ import annotations

import os
from typing import List, Tuple

from prowser_temp_files import prowser_mkstemp_path

from PIL import Image

SCREEN_SIZE_EXPERIMENTAL_PROMPT_SUFFIX = (
    " Fill all white borders with generated image expansion."
)


def _fit_dimensions(w: int, h: int, ref_w: int, ref_h: int) -> tuple[int, int]:
    """Scale down if needed so w×h fits inside ref_w×ref_h; never upscale."""
    scale = min(ref_w / w, ref_h / h, 1.0)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def create_edit_aspect_pad_temp_path() -> str:
    return prowser_mkstemp_path(
        prefix="imagegen-edit-aspect-pad-",
        suffix=".png",
    )


EXPANSION_TEMPLATE_ASSET = "expansion_template.webp"


def create_screen_size_expansion_template_temp_path() -> str:
    return prowser_mkstemp_path(
        prefix="imagegen-edit-screen-size-",
        suffix=".webp",
    )


def save_screen_size_expansion_template_webp() -> str:
    """Resize bundled expansion template to primary display size."""
    from screen_size_copy import get_physical_screen_size
    from theme_base import asset_path

    template_path = asset_path(EXPANSION_TEMPLATE_ASSET)
    if not os.path.isfile(template_path):
        raise FileNotFoundError(
            f"Expansion template not found: {template_path}"
        )
    screen_size = get_physical_screen_size()
    ref_w = max(1, int(screen_size.width()))
    ref_h = max(1, int(screen_size.height()))
    image = Image.open(template_path)
    try:
        rgb = image.convert("RGB")
        if rgb.size != (ref_w, ref_h):
            rgb = rgb.resize((ref_w, ref_h), Image.Resampling.LANCZOS)
        out_path = create_screen_size_expansion_template_temp_path()
        rgb.save(out_path, "WEBP", quality=95, method=6)
        os.chmod(out_path, 0o600)
        return out_path
    finally:
        image.close()


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
    source_path: str, ref_w: int, ref_h: int
) -> str:
    """Place source on a ref_w×ref_h white canvas (fit inside, centered)."""
    image = Image.open(source_path)
    try:
        rgb = image.convert("RGB")
        w, h = rgb.size
        fit_w, fit_h = _fit_dimensions(w, h, ref_w, ref_h)
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
) -> Tuple[List[str], List[str]]:
    """Prepend screen-sized expansion template; return (paths, temp_paths_to_delete)."""
    if not source_paths:
        return [], []
    template_path = save_screen_size_expansion_template_webp()
    return [template_path, *source_paths], [template_path]


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
