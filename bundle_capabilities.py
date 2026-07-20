#!/usr/bin/env python3
"""Runtime flags for minimal (--min) PyInstaller bundles."""

from __future__ import annotations

import importlib.util
import os
import sys

_MIN_BUNDLE_ENV = "PROWSER_MIN_BUNDLE"
_min_bundle_cached: bool | None = None


def _frozen_min_bundle_without_imagegen() -> bool:
    """True when a frozen app was built without imagegen_plugins (e.g. --min)."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return importlib.util.find_spec("imagegen_plugins") is None
    except (ImportError, ModuleNotFoundError, ValueError):
        return True


def is_min_bundle() -> bool:
    """True for pyInstallerBuild.sh --min bundles or when ``prowser.py --min`` is used."""
    global _min_bundle_cached
    if _min_bundle_cached is not None:
        return _min_bundle_cached
    if os.environ.get(_MIN_BUNDLE_ENV, "").strip() == "1":
        _min_bundle_cached = True
        return True
    if _frozen_min_bundle_without_imagegen():
        os.environ.setdefault(_MIN_BUNDLE_ENV, "1")
        _min_bundle_cached = True
        return True
    _min_bundle_cached = False
    return False


def imagegen_ui_enabled() -> bool:
    """Create / edit / expand / infill menus, job queue, and related settings."""
    return not is_min_bundle()


def lmstudio_ui_enabled() -> bool:
    """LM Studio SDK captions, recaption, and Open LM Studio."""
    return not is_min_bundle()


def voice_input_ui_enabled() -> bool:
    """Microphone dictation (faster-whisper) in text fields."""
    return not is_min_bundle()


def audio_output_ui_enabled() -> bool:
    """Read-aloud (macOS say) controls in the UI."""
    return not is_min_bundle()


def model_jobs_ui_enabled() -> bool:
    """Jobs sidebar pane, View > Jobs, and generation/caption job UI."""
    return not is_min_bundle()


def chat_ui_enabled() -> bool:
    """Chat sidebar pane and LM Studio conversation UI."""
    return not is_min_bundle()


def faces_ui_enabled() -> bool:
    """Face recognition search, cache faces, and Faces settings tab."""
    return not is_min_bundle()
