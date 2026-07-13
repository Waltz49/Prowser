#!/usr/bin/env python3
"""Cross-process flag: chat pane LM Studio streaming is in progress."""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_active = False
_FLAG_NAME = ".__chat_lmstudio_prediction_active__"


def _flag_path() -> str:
    from prowser_temp_files import ensure_temporary_files_directory

    return os.path.join(ensure_temporary_files_directory(), _FLAG_NAME)


def set_chat_lmstudio_prediction_active(active: bool) -> None:
    """Mark whether the chat pane is streaming an LM Studio response."""
    global _active
    with _lock:
        _active = active
    path = _flag_path()
    try:
        if active:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as flag_file:
                flag_file.write("1\n")
        elif os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def is_chat_lmstudio_prediction_active() -> bool:
    """True while the chat pane holds an active LM Studio prediction."""
    with _lock:
        if _active:
            return True
    try:
        return os.path.isfile(_flag_path())
    except OSError:
        return False
