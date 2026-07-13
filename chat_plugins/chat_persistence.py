#!/usr/bin/env python3
"""Persist chat session settings and conversation data under ~/.prowser/data/."""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from chat_plugins.chat_session import ChatMessage, ImageGenAutoMode
from config import get_config
from utils import validate_image_file

_SETTINGS_FILE_NAME = "chat_session_settings.json"
_DATA_FILE_NAME = "chat_session_data.json"
_IMAGES_DIR_NAME = "chat_session_images"

_lock = threading.Lock()


def _settings_path() -> Path:
    return get_config().data_dir / _SETTINGS_FILE_NAME


def _data_path() -> Path:
    return get_config().data_dir / _DATA_FILE_NAME


def session_images_dir() -> Path:
    path = get_config().data_dir / _IMAGES_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(".json.tmp")
    payload = copy.deepcopy(data)
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp_file.replace(path)


def _load_chat_settings() -> dict[str, Any]:
    with _lock:
        parsed = _parse_json_file(_settings_path())
        return dict(parsed) if parsed is not None else {}


def _save_chat_settings(data: dict[str, Any]) -> None:
    with _lock:
        _save_json_file(_settings_path(), data)


def is_preserve_chat_across_sessions() -> bool:
    """Return whether chat text/images should survive app restarts."""
    return bool(_load_chat_settings().get("preserve_across_sessions", False))


def set_preserve_chat_across_sessions(enabled: bool) -> None:
    """Persist the preserve-across-sessions preference."""
    data = _load_chat_settings()
    data["preserve_across_sessions"] = bool(enabled)
    _save_chat_settings(data)


def is_copy_images_to_assistant() -> bool:
    """When true, user attachments are copied onto assistant replies for /create edit jobs."""
    data = _load_chat_settings()
    if "copy_images_to_assistant" in data:
        return bool(data.get("copy_images_to_assistant", False))
    return bool(data.get("show_assistant_images", False))


def set_copy_images_to_assistant(enabled: bool) -> None:
    """Persist the copy-images-to-assistant preference."""
    data = _load_chat_settings()
    data["copy_images_to_assistant"] = bool(enabled)
    data.pop("show_assistant_images", None)
    _save_chat_settings(data)


def is_automatic_create() -> bool:
    """When true, every user message behaves as if it includes /create."""
    return bool(_load_chat_settings().get("automatic_create", False))


def set_automatic_create(enabled: bool) -> None:
    """Persist the automatic-/create preference."""
    data = _load_chat_settings()
    data["automatic_create"] = bool(enabled)
    _save_chat_settings(data)


def clear_persisted_chat_files() -> None:
    """Remove saved conversation JSON and profile chat image copies."""
    with _lock:
        try:
            _data_path().unlink(missing_ok=True)
        except OSError:
            pass
        images = get_config().data_dir / _IMAGES_DIR_NAME
        try:
            if images.is_dir():
                shutil.rmtree(images, ignore_errors=True)
        except OSError:
            pass


def _message_to_dict(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "text": message.text,
        "message_id": message.message_id,
        "image_paths": list(message.image_paths or []),
    }
    sources = list(message.source_image_paths or [])
    if sources:
        payload["source_image_paths"] = sources
    if message.image_gen_auto is not None:
        payload["image_gen_auto"] = message.image_gen_auto
    return payload


def _message_from_dict(raw: dict[str, Any]) -> ChatMessage | None:
    role = raw.get("role")
    if role not in ("user", "assistant"):
        return None
    message_id = raw.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return None
    text = raw.get("text")
    if not isinstance(text, str):
        text = ""
    raw_paths = raw.get("image_paths")
    image_paths = (
        [str(p) for p in raw_paths if isinstance(p, str) and p.strip()]
        if isinstance(raw_paths, list)
        else []
    )
    raw_sources = raw.get("source_image_paths")
    source_image_paths = (
        [str(p) for p in raw_sources if isinstance(p, str) and p.strip()]
        if isinstance(raw_sources, list)
        else list(image_paths)
    )
    image_gen_auto: ImageGenAutoMode | None = None
    auto = raw.get("image_gen_auto")
    if auto in ("create", "edit"):
        image_gen_auto = auto
    return ChatMessage(
        role=role,
        text=text,
        message_id=message_id,
        image_paths=image_paths,
        source_image_paths=source_image_paths,
        image_gen_auto=image_gen_auto,
    )


def save_chat_session_messages(messages: list[ChatMessage]) -> None:
    """Write the current conversation to ~/.prowser/data/chat_session_data.json."""
    payload = {
        "messages": [_message_to_dict(msg) for msg in messages],
    }
    with _lock:
        _save_json_file(_data_path(), payload)


def load_chat_session_messages() -> list[ChatMessage]:
    """Load a previously saved conversation, dropping invalid entries."""
    with _lock:
        parsed = _parse_json_file(_data_path())
    if parsed is None:
        return []
    raw_messages = parsed.get("messages")
    if not isinstance(raw_messages, list):
        return []
    messages: list[ChatMessage] = []
    images_root = session_images_dir().resolve()
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        msg = _message_from_dict(raw)
        if msg is None:
            continue
        kept_paths: list[str] = []
        for path in msg.image_paths:
            try:
                ap = Path(path).resolve()
            except OSError:
                continue
            if not ap.is_file() or not validate_image_file(str(ap)):
                continue
            ap_str = str(ap)
            if msg.role == "assistant":
                kept_paths.append(ap_str)
            elif ap_str.startswith(str(images_root) + os.sep):
                kept_paths.append(ap_str)
        msg.image_paths = kept_paths
        if msg.role == "user":
            from chat_plugins.chat_image_paths import align_source_image_paths

            sources = list(msg.source_image_paths or kept_paths)
            if len(sources) != len(kept_paths):
                sources = sources[: len(kept_paths)] if sources else list(kept_paths)
            msg.source_image_paths = align_source_image_paths(kept_paths, sources)
        messages.append(msg)
    return messages
