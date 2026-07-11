#!/usr/bin/env python3
"""Purge ephemeral chat data: temp images, in-memory history, and API log entries."""

from __future__ import annotations

import os
import re
import sys

from chat_plugins.chat_image_store import (
    ChatImageStore,
    cleanup_all_chat_storage,
    reset_image_store_session,
)

_CHAT_LOG_MARKERS = (
    "respond_stream",
    "chat_conversation",
    "chat_plugins.chat_lmstudio",
)


def _scrub_chat_blocks(content: str) -> str:
    parts = re.split(r"(?=\n\[\d{4}-\d{2}-\d{2})", content)
    if not parts and content.strip():
        parts = [content]
    kept: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        lower = part.lower()
        if any(marker in lower for marker in _CHAT_LOG_MARKERS):
            continue
        kept.append(part)
    return "".join(kept)


def scrub_chat_entries_from_print_log() -> None:
    """Drop LM Studio chat API blocks from the shared View log file."""
    try:
        from print_log_redirect import (
            PRINT_LOG_FILE_PATH,
            _StdoutToPrintLog,
            _print_log_lock,
            session_print_log_path,
        )
    except ImportError:
        return

    path = PRINT_LOG_FILE_PATH or session_print_log_path()
    if not path or not os.path.isfile(path):
        return

    def _rewrite_log_file() -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as log_file:
                content = log_file.read()
        except OSError:
            return
        new_content = _scrub_chat_blocks(content)
        if new_content == content:
            return
        try:
            with open(path, "w", encoding="utf-8") as log_file:
                log_file.write(new_content)
            os.chmod(path, 0o600)
        except OSError:
            pass

    out = sys.stdout
    if isinstance(out, _StdoutToPrintLog) and getattr(out, "_path", None) == path:
        with _print_log_lock:
            try:
                out._file.flush()
                out._file.close()
            except OSError:
                pass
            _rewrite_log_file()
            try:
                out._file = open(path, "a", buffering=1)
                os.chmod(path, 0o600)
            except OSError:
                pass
        return

    with _print_log_lock:
        _rewrite_log_file()


def purge_chat_disk_and_logs() -> None:
    cleanup_all_chat_storage()
    scrub_chat_entries_from_print_log()


def purge_all_chat_ephemeral_data(main_window=None) -> None:
    """Purge chat UI state when possible; always wipe disk and log remnants."""
    combined_sidebar = getattr(main_window, "combined_sidebar", None) if main_window else None
    chat_widget = (
        getattr(combined_sidebar, "chat_widget", None) if combined_sidebar else None
    )
    if chat_widget is not None and hasattr(chat_widget, "discard_all_data"):
        chat_widget.discard_all_data()
        return
    purge_chat_disk_and_logs()
