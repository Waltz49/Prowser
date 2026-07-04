#!/usr/bin/env python3
"""User-imported LoRA entries persisted in settings (downloaded .safetensors files)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from imagegen_plugins.lora_entry import DEFAULT_CACHE, FluxLoraEntry, LORA_MIN_STEPS
from imagegen_plugins.lora_model_registry import host_id_for_lora_model

USER_ENTRIES_KEY = "user_entries"
USER_LORA_ID_PREFIX = "user_"
USER_LORA_CACHE_ROOT = DEFAULT_CACHE / "user"


def is_user_lora_id(lora_id: str) -> bool:
    return str(lora_id or "").startswith(USER_LORA_ID_PREFIX)


def _entry_to_dict(entry: FluxLoraEntry) -> Dict[str, Any]:
    return {
        "host_id": entry.host_id,
        "lora_id": entry.lora_id,
        "display_name": entry.display_name,
        "repo_id": entry.repo_id or "",
        "filename": entry.filename or "",
        "scale": float(entry.scale),
        "local_path": entry.local_path or "",
        "base_hf_model_id": entry.base_hf_model_id,
        "min_steps": int(entry.min_steps),
        "mflux_compatible": entry.mflux_compatible,
        "trigger_word": entry.trigger_word,
    }


def entry_from_dict(raw: Dict[str, Any]) -> Optional[FluxLoraEntry]:
    if not isinstance(raw, dict):
        return None
    lora_id = str(raw.get("lora_id") or "").strip()
    if not lora_id or not is_user_lora_id(lora_id):
        return None
    host_id = str(raw.get("host_id") or "").strip()
    display_name = str(raw.get("display_name") or lora_id).strip()
    local_path = str(raw.get("local_path") or "").strip()
    base_hf = str(raw.get("base_hf_model_id") or "").strip()
    if not host_id or not local_path or not base_hf:
        return None
    trigger = raw.get("trigger_word")
    trigger_word = str(trigger).strip() if trigger else None
    if trigger_word == "":
        trigger_word = None
    mflux_raw = raw.get("mflux_compatible")
    mflux_compatible = mflux_raw if isinstance(mflux_raw, bool) else None
    try:
        scale = float(raw.get("scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    try:
        min_steps = int(raw.get("min_steps", LORA_MIN_STEPS))
    except (TypeError, ValueError):
        min_steps = LORA_MIN_STEPS
    return FluxLoraEntry(
        host_id=host_id,
        lora_id=lora_id,
        display_name=display_name,
        repo_id=str(raw.get("repo_id") or ""),
        filename=str(raw.get("filename") or ""),
        scale=scale,
        local_path=local_path,
        base_hf_model_id=base_hf,
        min_steps=min_steps,
        mflux_compatible=mflux_compatible,
        trigger_word=trigger_word,
    )


def user_entries_raw(lc: Dict[str, Any]) -> Dict[str, Any]:
    raw = lc.get(USER_ENTRIES_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def user_lora_entries_from_lc(lc: Dict[str, Any]) -> Dict[str, FluxLoraEntry]:
    out: Dict[str, FluxLoraEntry] = {}
    for lid, raw in user_entries_raw(lc).items():
        entry = entry_from_dict(raw if isinstance(raw, dict) else {})
        if entry is not None:
            out[str(lid)] = entry
    return out


def user_lora_entries_from_settings(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, FluxLoraEntry]:
    from imagegen_plugins.lora_catalog_settings import lora_catalog_from_settings

    lc = lora_catalog_from_settings(settings)
    return user_lora_entries_from_lc(lc)


def merged_lora_catalog(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, FluxLoraEntry]:
    from imagegen_plugins.lora_catalog import LORA_CATALOG

    merged = dict(LORA_CATALOG)
    merged.update(user_lora_entries_from_settings(settings))
    return merged


def display_name_from_path(path: Path) -> str:
    name = path.stem.strip()
    return name or "Imported LoRA"


def slugify_lora_id(name: str) -> str:
    slug = re.sub(r"[^\w]+", "_", (name or "").lower()).strip("_")
    if not slug:
        slug = "import"
    lid = f"{USER_LORA_ID_PREFIX}{slug}"
    if len(lid) > 64:
        lid = lid[:64].rstrip("_")
    return lid


def unique_lora_id(base: str, existing: Dict[str, FluxLoraEntry]) -> str:
    lid = base
    n = 2
    while lid in existing:
        suffix = f"_{n}"
        lid = (base[: max(1, 64 - len(suffix))] + suffix) if len(base) + len(suffix) > 64 else base + suffix
        n += 1
    return lid


def copy_lora_to_user_cache(source: Path, lora_id: str) -> Path:
    dest_dir = USER_LORA_CACHE_ROOT / lora_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    return dest.resolve()


def build_user_lora_entry(
    *,
    source_path: Path,
    display_name: str,
    model_key: str,
    trigger_word: Optional[str] = None,
    scale: float = 1.0,
    settings: Optional[Dict[str, Any]] = None,
) -> FluxLoraEntry:
    host_id = host_id_for_lora_model(model_key)
    if not host_id:
        raise ValueError(f"LoRAs are not supported for model {model_key!r}.")
    existing = merged_lora_catalog(settings)
    base_id = slugify_lora_id(display_name or source_path.stem)
    lora_id = unique_lora_id(base_id, existing)
    dest = copy_lora_to_user_cache(source_path, lora_id)
    return FluxLoraEntry(
        host_id=host_id,
        lora_id=lora_id,
        display_name=(display_name or display_name_from_path(source_path)).strip(),
        local_path=str(dest),
        scale=float(scale),
        base_hf_model_id=model_key,
        min_steps=LORA_MIN_STEPS,
        mflux_compatible=None,
        trigger_word=(trigger_word or "").strip() or None,
    )


def remove_user_lora_files(entry: FluxLoraEntry) -> None:
    path = Path(entry.local_path or "").expanduser()
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
    parent = path.parent
    if parent.is_dir() and parent.name == entry.lora_id:
        try:
            if not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


def validate_safetensors_source(path: str) -> Path:
    p = Path(path or "").expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"LoRA file not found: {path}")
    if p.suffix.lower() != ".safetensors":
        raise ValueError("Only .safetensors LoRA files are supported.")
    if p.stat().st_size < 1024:
        raise ValueError("LoRA file is too small to be valid.")
    return p.resolve()
