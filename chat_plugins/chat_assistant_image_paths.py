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


