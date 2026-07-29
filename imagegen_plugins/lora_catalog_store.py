#!/usr/bin/env python3
"""Persist user LoRA catalog state in ~/.prowser/data/lora_catalog.json."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

_lora_catalog_file_lock = threading.Lock()


def lora_catalog_file_path() -> Path:
    from config import get_config

    return get_config().lora_catalog_file


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp_file.replace(path)


def load_lora_catalog_file() -> Dict[str, Any]:
    """Load migrated LoRA catalog state from lora_catalog.json."""
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog

    path = lora_catalog_file_path()
    with _lora_catalog_file_lock:
        if path.is_file():
            data = _read_json(path)
            if data is not None:
                return migrate_lora_catalog(data)
        return migrate_lora_catalog({})


def save_lora_catalog_file(lc: Dict[str, Any]) -> None:
    """Write LoRA catalog state to lora_catalog.json."""
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog

    path = lora_catalog_file_path()
    payload = migrate_lora_catalog(copy.deepcopy(lc))
    with _lora_catalog_file_lock:
        _atomic_write_json(path, payload)


def migrate_embedded_lora_catalog_if_needed(settings: dict) -> bool:
    """Move imagegen.lora_catalog out of settings.json into lora_catalog.json."""
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog

    imagegen = settings.get("imagegen")
    if not isinstance(imagegen, dict):
        return False

    embedded = imagegen.get("lora_catalog")
    path = lora_catalog_file_path()
    changed = False

    with _lora_catalog_file_lock:
        if isinstance(embedded, dict) and embedded:
            if not path.is_file():
                _atomic_write_json(path, migrate_lora_catalog(dict(embedded)))
            del imagegen["lora_catalog"]
            changed = True
        elif "lora_catalog" in imagegen:
            del imagegen["lora_catalog"]
            changed = True

        if not path.is_file():
            _atomic_write_json(path, migrate_lora_catalog({}))
            changed = True

    return changed
