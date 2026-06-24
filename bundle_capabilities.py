#!/usr/bin/env python3
"""Runtime flags for minimal (--min) PyInstaller bundles."""

from __future__ import annotations

import os

_MIN_BUNDLE_ENV = "PROWSER_MIN_BUNDLE"


def is_min_bundle() -> bool:
    """True for pyInstallerBuild.sh --min bundles or when ``main.py --min`` is used."""
    return os.environ.get(_MIN_BUNDLE_ENV, "").strip() == "1"


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
