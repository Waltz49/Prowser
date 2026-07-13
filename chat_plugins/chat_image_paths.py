#!/usr/bin/env python3
"""Resolve chat attachment copies vs original source paths for models and jobs."""

from __future__ import annotations

import os

from chat_plugins.chat_session import ChatMessage


def chat_paths_referenced_by_messages(
    messages,
    *,
    except_message_id: str | None = None,
) -> set[str]:
    """Absolute paths still attached to any message (chat copies for display)."""
    refs: set[str] = set()
    for msg in messages:
        if except_message_id and msg.message_id == except_message_id:
            continue
        for path in msg.image_paths or []:
            if not path:
                continue
            try:
                refs.add(os.path.abspath(path))
            except OSError:
                continue
    return refs


def align_source_image_paths(
    stored_paths: list[str],
    source_paths: list[str],
) -> list[str]:
    """Pair stored chat copies with originals (same length as *stored_paths*)."""
    aligned: list[str] = []
    for idx, stored in enumerate(stored_paths):
        src = source_paths[idx] if idx < len(source_paths) else stored
        aligned.append(_prefer_existing_source(src, stored))
    return aligned


def sources_for_new_attachments(
    new_paths: list[str],
    *,
    old_stored_paths: list[str] | None = None,
    old_source_paths: list[str] | None = None,
) -> list[str]:
    """Original path for each attachment the user just set (before copying)."""
    if not old_stored_paths:
        return [
            os.path.abspath(p)
            for p in new_paths
            if p and os.path.isfile(p)
        ]
    copy_to_source: dict[str, str] = {}
    for stored, source in zip(old_stored_paths, old_source_paths):
        if not stored:
            continue
        try:
            copy_to_source[os.path.abspath(stored)] = _prefer_existing_source(
                source, stored
            )
        except OSError:
            continue
    out: list[str] = []
    for path in new_paths:
        if not path:
            continue
        try:
            ap = os.path.abspath(path)
        except OSError:
            continue
        if ap in copy_to_source:
            out.append(copy_to_source[ap])
        elif os.path.isfile(ap):
            out.append(ap)
        else:
            out.append(ap)
    return out


def paths_for_vision_model(message: ChatMessage) -> list[str]:
    """Prefer original sources for LM vision; fall back to chat copies."""
    return _resolved_paths(message)


def paths_for_image_gen(message: ChatMessage) -> list[str]:
    """Prefer original sources for edit /create and job submission."""
    return _resolved_paths(message)


def _resolved_paths(message: ChatMessage) -> list[str]:
    copies = list(message.image_paths or [])
    sources = list(message.source_image_paths or [])
    if not copies:
        return []
    if len(sources) != len(copies):
        return [p for p in copies if p and os.path.isfile(p)]
    out: list[str] = []
    for src, copy in zip(sources, copies):
        path = _prefer_existing_source(src, copy)
        if path and os.path.isfile(path):
            out.append(path)
    return out


def _prefer_existing_source(source: str, stored_copy: str) -> str:
    if source:
        try:
            ap = os.path.abspath(source)
            if os.path.isfile(ap):
                return ap
        except OSError:
            pass
    if stored_copy:
        try:
            return os.path.abspath(stored_copy)
        except OSError:
            return stored_copy
    return source or stored_copy
