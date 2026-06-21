#!/usr/bin/env python3
"""
Face gathering coordinator: ensures background and foreground face gathering never run concurrently.
Foreground has priority. Buffers must be flushed before either can start.
Uses a file in data_dir for cross-process coordination (background runs in separate process).
"""

import os
from pathlib import Path


def _marker_path() -> Path:
    """Path to marker file indicating foreground face scan is active."""
    from config import get_config
    return get_config().data_dir / "foreground_face_scan_active"


def set_foreground_face_scan_active(active: bool) -> None:
    """Set or clear the foreground face scan active marker.
    Call with True when foreground scan starts, False when it completes."""
    path = _marker_path()
    if active:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        except OSError:
            pass
    else:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def is_foreground_face_scan_active() -> bool:
    """Return True if foreground face scan is currently active.
    Used by background worker to skip face extraction when foreground has priority."""
    try:
        return _marker_path().exists()
    except Exception:
        return False
