#!/usr/bin/env python3
"""Per-function session snapshots for the unified image-generation dialog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage


@dataclass
class FunctionSessionState:
    values: Dict[str, Any]
    plugin_id: str
    source_path: Optional[str] = None
    source_paths: Optional[List[str]] = None
    placement: Optional[Tuple[int, int, int, int]] = None
    mask_png_bytes: Optional[bytes] = None

    def equals(self, other: Optional["FunctionSessionState"]) -> bool:
        if other is None:
            return False
        if self.plugin_id != other.plugin_id:
            return False
        if self.source_path != other.source_path:
            return False
        if self.source_paths != other.source_paths:
            return False
        if self.placement != other.placement:
            return False
        if self.mask_png_bytes != other.mask_png_bytes:
            return False
        return _values_equal(self.values, other.values)


def _values_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = set(a) | set(b)
    for key in keys:
        if a.get(key) != b.get(key):
            return False
    return True


def mask_to_png_bytes(mask: QImage) -> Optional[bytes]:
    if mask is None or mask.isNull():
        return None
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not mask.save(buf, "PNG"):
        return None
    return bytes(buf.data())


def mask_from_png_bytes(data: Optional[bytes]) -> Optional[QImage]:
    if not data:
        return None
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        return None
    return image
