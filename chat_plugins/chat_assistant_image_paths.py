#!/usr/bin/env python3
"""Normalize image paths stored on assistant chat messages."""

from __future__ import annotations

import os

from chat_plugins.chat_image_store import MAX_CHAT_IMAGES
from utils import validate_image_file


def normalize_assistant_message_image_paths(paths: list[str]) -> list[str]:
    """Absolute on-disk image paths stored on assistant messages."""
    out: list[str] = []
    for path in paths:
        if not path or not os.path.isfile(path) or not validate_image_file(path):
            continue
        ap = os.path.abspath(path)
        if ap in out:
            continue
        out.append(ap)
        if len(out) >= MAX_CHAT_IMAGES:
            break
    return out


def expand_edit_source_paths_from_user_images(user_image_paths: list[str]) -> list[str]:
    """Import Rest equivalent: prefer original source paths plus EXIF references."""
    if not user_image_paths:
        return []
    try:
        from imagegen_plugins.image_gen_edit_dialog import (
            MAX_EDIT_SOURCE_IMAGES,
            _merge_imported_edit_source_paths,
        )
        from search.reference_graph import valid_exif_reference_paths_for_image
    except ImportError:
        return [
            os.path.abspath(p)
            for p in user_image_paths
            if p and os.path.isfile(p)
        ][:4]

    merged: list[str] = []
    for path in user_image_paths:
        if not path or not os.path.isfile(path):
            continue
        refs = valid_exif_reference_paths_for_image(
            path, max_count=MAX_EDIT_SOURCE_IMAGES
        )
        merged = _merge_imported_edit_source_paths(
            merged, refs, max_total=MAX_EDIT_SOURCE_IMAGES
        )
        if len(merged) >= MAX_EDIT_SOURCE_IMAGES:
            break
    return merged[:MAX_EDIT_SOURCE_IMAGES]
