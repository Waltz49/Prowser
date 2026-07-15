#!/usr/bin/env python3
"""Persist chat system/user prompt libraries in ~/.prowser/data/*.json."""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from config import CHAT_DEFAULTS, get_config
from utils import validate_image_file

_SYSTEM_FILE_NAME = "chat_system_prompts.json"
_USER_FILE_NAME = "chat_user_prompts.json"
_PREFIX_POSTFIX_FILE_NAME = "chat_prefix_postfix.json"
_FAVORITE_IMAGES_DIR_NAME = "chat_favorite_images"
_LEGACY_SETTINGS_KEYS = (
    "chat_system_prompt",
    "chat_named_system_prompts",
    "chat_active_named_prompt_id",
    "chat_favorite_user_prompts",
)

_system_prompt_lock = threading.Lock()
_user_prompt_lock = threading.Lock()
_prefix_postfix_lock = threading.Lock()


def _system_prompts_path() -> Path:
    return get_config().data_dir / _SYSTEM_FILE_NAME


def _user_prompts_path() -> Path:
    return get_config().data_dir / _USER_FILE_NAME


def _prefix_postfix_path() -> Path:
    return get_config().data_dir / _PREFIX_POSTFIX_FILE_NAME


def favorite_images_dir() -> Path:
    path = get_config().data_dir / _FAVORITE_IMAGES_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_managed_favorite_image(path: str) -> bool:
    try:
        ap = Path(path).resolve()
        root = favorite_images_dir().resolve()
        return str(ap).startswith(str(root) + os.sep)
    except OSError:
        return False


def remove_favorite_image_files(paths: list[str]) -> None:
    for path in paths:
        if not path or not _is_managed_favorite_image(path):
            continue
        try:
            Path(path).resolve().unlink(missing_ok=True)
        except OSError:
            pass


def persist_favorite_image_paths(
    favorite_id: str,
    source_paths: list[str],
    *,
    max_images: int = 4,
) -> list[str]:
    """Copy images into ~/.prowser/data/chat_favorite_images/ for durable favorites."""
    from chat_plugins.chat_image_store import MAX_CHAT_IMAGES

    limit = min(max_images, MAX_CHAT_IMAGES)
    dest_dir = favorite_images_dir()
    stored: list[str] = []
    fav_root = dest_dir.resolve()
    for idx, src in enumerate(source_paths[:limit]):
        if not src:
            continue
        abs_src = os.path.abspath(src)
        if abs_src.startswith(str(fav_root) + os.sep) and os.path.isfile(abs_src):
            if validate_image_file(abs_src):
                stored.append(abs_src)
            continue
        if not os.path.isfile(abs_src) or not validate_image_file(abs_src):
            continue
        ext = os.path.splitext(abs_src)[1] or ".png"
        dest = dest_dir / f"{favorite_id}_{idx}{ext.lower()}"
        shutil.copy2(abs_src, dest)
        stored.append(str(dest.resolve()))
    return stored


def _cleanup_legacy_chat_prompt_settings_keys() -> None:
    """Drop prompt-library keys from settings.json after dedicated files own them."""
    config = get_config()
    settings = config.load_settings()
    changed = False
    for key in _LEGACY_SETTINGS_KEYS:
        if key in settings:
            del settings[key]
            changed = True
    if changed:
        config.save_settings(settings)


def _default_system_prompt_config() -> dict[str, Any]:
    return {
        "system_prompt": str(CHAT_DEFAULTS["chat_system_prompt"]),
        "active_named_prompt_id": "",
        "named_prompts": [],
    }


def _default_user_prompt_config() -> dict[str, Any]:
    return {
        "selected_favorite_prompt_id": "",
        "favorite_prompts": [],
    }


def _default_prefix_postfix_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "entries": [],
    }


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


def _normalize_named_prompts(raw: Any) -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return prompts
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        prompts.append(
            {
                "id": str(item["id"]),
                "name": str(item.get("name", "Untitled")),
                "text": str(item.get("text", "")),
            }
        )
    return prompts


def _normalize_prefix_postfix_entries(raw: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return entries
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        entries.append(
            {
                "id": str(item["id"]),
                "text": str(item.get("text", "")),
                "use_with_text": bool(item.get("use_with_text")),
                "use_with_images": bool(item.get("use_with_images")),
                "is_prefix": bool(item.get("is_prefix")),
                "is_postfix": bool(item.get("is_postfix")),
            }
        )
    return entries


def _normalize_favorite_prompts(raw: Any) -> list[dict[str, Any]]:
    prompts: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return prompts
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        raw_paths = item.get("image_paths")
        image_paths = (
            [str(p) for p in raw_paths if p]
            if isinstance(raw_paths, list)
            else []
        )
        prompts.append(
            {
                "id": str(item["id"]),
                "name": str(item.get("name", "Untitled")),
                "text": str(item.get("text", "")),
                "image_paths": image_paths,
            }
        )
    return prompts


def _migrate_system_prompt_config_from_settings() -> dict[str, Any]:
    settings = get_config().load_settings()
    config = _default_system_prompt_config()
    prompt = settings.get("chat_system_prompt")
    if isinstance(prompt, str) and prompt.strip():
        config["system_prompt"] = prompt
    active_id = settings.get("chat_active_named_prompt_id")
    if isinstance(active_id, str):
        config["active_named_prompt_id"] = active_id
    config["named_prompts"] = _normalize_named_prompts(
        settings.get("chat_named_system_prompts")
    )
    return config


def _migrate_user_prompt_config_from_settings() -> dict[str, Any]:
    settings = get_config().load_settings()
    return {
        "favorite_prompts": _normalize_favorite_prompts(
            settings.get("chat_favorite_user_prompts")
        ),
    }


def _normalize_system_prompt_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = _default_system_prompt_config()
    prompt = raw.get("system_prompt")
    if isinstance(prompt, str):
        config["system_prompt"] = prompt
    active_id = raw.get("active_named_prompt_id")
    if isinstance(active_id, str):
        config["active_named_prompt_id"] = active_id
    config["named_prompts"] = _normalize_named_prompts(raw.get("named_prompts"))
    return config


def _normalize_user_prompt_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = _default_user_prompt_config()
    selected_id = raw.get("selected_favorite_prompt_id")
    if isinstance(selected_id, str):
        config["selected_favorite_prompt_id"] = selected_id
    config["favorite_prompts"] = _normalize_favorite_prompts(raw.get("favorite_prompts"))
    return config


def _normalize_prefix_postfix_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = _default_prefix_postfix_config()
    enabled = raw.get("enabled")
    if isinstance(enabled, bool):
        config["enabled"] = enabled
    config["entries"] = _normalize_prefix_postfix_entries(raw.get("entries"))
    return config


def load_system_prompt_config() -> dict[str, Any]:
    """Load ~/.prowser/data/chat_system_prompts.json (migrate from settings once)."""
    path = _system_prompts_path()
    with _system_prompt_lock:
        parsed = _parse_json_file(path)
        if parsed is not None:
            _cleanup_legacy_chat_prompt_settings_keys()
            return _normalize_system_prompt_config(parsed)
        migrated = _migrate_system_prompt_config_from_settings()
        _save_json_file(path, migrated)
        _cleanup_legacy_chat_prompt_settings_keys()
        return migrated


def save_system_prompt_config(config: dict[str, Any]) -> None:
    """Save ~/.prowser/data/chat_system_prompts.json."""
    normalized = _normalize_system_prompt_config(config)
    path = _system_prompts_path()
    with _system_prompt_lock:
        _save_json_file(path, normalized)


def load_user_prompt_config() -> dict[str, Any]:
    """Load ~/.prowser/data/chat_user_prompts.json (migrate from settings once)."""
    path = _user_prompts_path()
    with _user_prompt_lock:
        parsed = _parse_json_file(path)
        if parsed is not None:
            _cleanup_legacy_chat_prompt_settings_keys()
            return _normalize_user_prompt_config(parsed)
        migrated = _migrate_user_prompt_config_from_settings()
        _save_json_file(path, migrated)
        _cleanup_legacy_chat_prompt_settings_keys()
        return migrated


def save_user_prompt_config(config: dict[str, Any]) -> None:
    """Save ~/.prowser/data/chat_user_prompts.json."""
    normalized = _normalize_user_prompt_config(config)
    path = _user_prompts_path()
    with _user_prompt_lock:
        _save_json_file(path, normalized)


def load_prefix_postfix_config() -> dict[str, Any]:
    """Load ~/.prowser/data/chat_prefix_postfix.json."""
    path = _prefix_postfix_path()
    with _prefix_postfix_lock:
        parsed = _parse_json_file(path)
        if parsed is not None:
            return _normalize_prefix_postfix_config(parsed)
        default = _default_prefix_postfix_config()
        _save_json_file(path, default)
        return default


def save_prefix_postfix_config(config: dict[str, Any]) -> None:
    """Save ~/.prowser/data/chat_prefix_postfix.json."""
    normalized = _normalize_prefix_postfix_config(config)
    path = _prefix_postfix_path()
    with _prefix_postfix_lock:
        _save_json_file(path, normalized)
