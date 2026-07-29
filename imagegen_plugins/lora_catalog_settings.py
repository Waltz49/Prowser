#!/usr/bin/env python3
"""Per-base-model LoRA catalog state (load, migrate, defaults).

User catalog state is persisted in ~/.prowser/data/lora_catalog.json via
lora_catalog_store.py so it can be backed up separately from settings.json.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from imagegen_plugins.lora_entry import FluxLoraEntry

from imagegen_plugins.lora_catalogs.flux1_fill import FLUX1_FILL_LORAS
from imagegen_plugins.lora_catalogs.flux1_t2i import FLUX1_T2I_LORAS
from imagegen_plugins.lora_catalogs.flux2_klein import FLUX2_KLEIN_LORAS
from imagegen_plugins.lora_catalogs.sd15 import SD15_LORAS
from imagegen_plugins.lora_catalogs.z_image_turbo import Z_IMAGE_TURBO_LORAS
from imagegen_plugins.lora_entry import DEFAULT_ENABLED_LORA_IDS_BY_HOST
from imagegen_plugins.lora_host_registry import LORA_HOST_ORDER
from imagegen_plugins.lora_model_registry import (
    LORA_SETTINGS_MODEL_ORDER,
    entry_matches_lora_model,
    lora_models_for_entry,
)

from imagegen_plugins.lora_user_entries import USER_ENTRIES_KEY, user_lora_entries_from_lc

LORA_CATALOG = {
    **FLUX1_T2I_LORAS,
    **FLUX1_FILL_LORAS,
    **FLUX2_KLEIN_LORAS,
    **SD15_LORAS,
    **Z_IMAGE_TURBO_LORAS,
}

_LEGACY_ENABLED_KEY = "enabled_ids"
_LEGACY_FLAT_DELETED_KEY = "deleted_ids"
_LEGACY_HIDDEN_KEY = "hidden_ids"
_BY_HOST_KEY = "by_host"
_BY_MODEL_KEY = "by_model"
ENTRY_OVERRIDES_KEY = "entry_overrides"
USER_PRESET_KEY = "lora_user_preset"
DELETED_IDS_KEY = "deleted_ids"


def _empty_slice() -> Dict[str, List[str]]:
    return {"enabled_ids": [], DELETED_IDS_KEY: []}


def _slice_deleted_ids(slice_: Dict[str, Any]) -> List[str]:
    """Read deleted ids from a model/host slice, migrating legacy hidden_ids."""
    deleted = slice_.get(DELETED_IDS_KEY)
    if isinstance(deleted, list) and deleted:
        return [str(x) for x in deleted]
    hidden = slice_.get(_LEGACY_HIDDEN_KEY)
    if isinstance(hidden, list):
        return [str(x) for x in hidden]
    return []


def entry_overrides_from_lc(lc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = lc.get(ENTRY_OVERRIDES_KEY)
    if not isinstance(raw, dict):
        return {}
    return {
        str(lid): dict(raw_slice)
        for lid, raw_slice in raw.items()
        if isinstance(raw_slice, dict)
    }


def apply_entry_overrides(
    entry: FluxLoraEntry,
    overrides: Optional[Dict[str, Any]],
) -> FluxLoraEntry:
    if not overrides:
        return entry
    kwargs: Dict[str, Any] = {}
    if "display_name" in overrides:
        name = str(overrides.get("display_name") or "").strip()
        if name:
            kwargs["display_name"] = name
    if "trigger_word" in overrides:
        trigger = overrides.get("trigger_word")
        trigger_word = str(trigger).strip() if trigger else None
        kwargs["trigger_word"] = trigger_word or None
    if "scale" in overrides:
        try:
            kwargs["scale"] = float(overrides["scale"])
        except (TypeError, ValueError):
            pass
    if "comment" in overrides:
        comment = overrides.get("comment")
        kwargs["comment"] = str(comment).strip() if comment else None
    if not kwargs:
        return entry
    return replace(entry, **kwargs)


def default_enabled_lora_ids_by_model() -> Dict[str, Tuple[str, ...]]:
    out: Dict[str, list[str]] = {k: [] for k in LORA_SETTINGS_MODEL_ORDER}
    for host_id, ids in DEFAULT_ENABLED_LORA_IDS_BY_HOST.items():
        for lid in ids:
            entry = LORA_CATALOG.get(lid)
            if entry is None:
                continue
            for mk in lora_models_for_entry(entry):
                if lid not in out[mk]:
                    out[mk].append(lid)
    return {k: tuple(v) for k, v in out.items()}


DEFAULT_ENABLED_LORA_IDS_BY_MODEL = default_enabled_lora_ids_by_model()


def default_by_host() -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {}
    for host_id in LORA_HOST_ORDER:
        enabled = list(DEFAULT_ENABLED_LORA_IDS_BY_HOST.get(host_id, ()))
        out[host_id] = {
            "enabled_ids": [x for x in enabled if x in LORA_CATALOG],
            DELETED_IDS_KEY: [],
        }
    return out


def default_by_model() -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {}
    for model_key in LORA_SETTINGS_MODEL_ORDER:
        enabled = list(DEFAULT_ENABLED_LORA_IDS_BY_MODEL.get(model_key, ()))
        out[model_key] = {
            "enabled_ids": [x for x in enabled if x in LORA_CATALOG],
            DELETED_IDS_KEY: [],
        }
    return out


def _catalog_for_lc(lc: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(LORA_CATALOG)
    merged.update(user_lora_entries_from_lc(lc))
    return merged


def _normalize_host_slice(
    host_id: str,
    slice_: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, List[str]]:
    enabled = slice_.get("enabled_ids")
    return {
        "enabled_ids": [
            str(x)
            for x in (enabled if isinstance(enabled, list) else [])
            if str(x) in catalog and catalog[str(x)].host_id == host_id
        ],
        DELETED_IDS_KEY: _slice_deleted_ids(slice_),
    }


def _normalize_model_slice(
    model_key: str,
    slice_: Dict[str, Any],
    catalog: Dict[str, Any],
    model_support: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    ms = model_support if isinstance(model_support, dict) else {}
    enabled = slice_.get("enabled_ids")
    deleted_raw = _slice_deleted_ids(slice_)
    return {
        "enabled_ids": [
            str(x)
            for x in (enabled if isinstance(enabled, list) else [])
            if str(x) in catalog
            and entry_matches_lora_model(
                catalog[str(x)], model_key, model_support=ms
            )
        ],
        DELETED_IDS_KEY: [
            str(x)
            for x in deleted_raw
            if str(x) in catalog
            and entry_matches_lora_model(
                catalog[str(x)], model_key, model_support=ms
            )
        ],
    }


def _by_model_from_by_host(by_host: Dict[str, Dict[str, List[str]]]) -> Dict[str, Dict[str, List[str]]]:
    """One-time migration: host enabled/hidden → per-target-model slices."""
    out = default_by_model()
    for host_id, slice_ in by_host.items():
        if not isinstance(slice_, dict):
            continue
        for lid in slice_.get("enabled_ids") or []:
            entry = LORA_CATALOG.get(str(lid))
            if entry is None:
                continue
            for mk in lora_models_for_entry(entry):
                if str(lid) not in out[mk]["enabled_ids"]:
                    out[mk]["enabled_ids"].append(str(lid))
        for lid in _slice_deleted_ids(slice_):
            entry = LORA_CATALOG.get(str(lid))
            if entry is None:
                continue
            for mk in lora_models_for_entry(entry):
                if str(lid) not in out[mk][DELETED_IDS_KEY]:
                    out[mk][DELETED_IDS_KEY].append(str(lid))
    return out


def _ensure_by_model(lc: Dict[str, Any], by_host: Dict[str, Dict[str, List[str]]]) -> None:
    catalog = _catalog_for_lc(lc)
    ms = lc.get("model_support") if isinstance(lc.get("model_support"), dict) else {}
    if _BY_MODEL_KEY not in lc:
        lc[_BY_MODEL_KEY] = _by_model_from_by_host(by_host)
    by_model = dict(lc.get(_BY_MODEL_KEY) or {})
    for model_key in LORA_SETTINGS_MODEL_ORDER:
        slice_ = by_model.get(model_key)
        if not isinstance(slice_, dict):
            by_model[model_key] = {
                "enabled_ids": [
                    str(x)
                    for x in DEFAULT_ENABLED_LORA_IDS_BY_MODEL.get(model_key, ())
                    if str(x) in LORA_CATALOG
                ],
                DELETED_IDS_KEY: [],
            }
        else:
            by_model[model_key] = _normalize_model_slice(
                model_key, slice_, catalog, model_support=ms
            )
    lc[_BY_MODEL_KEY] = by_model


def migrate_lora_catalog(lc: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure by_host + by_model exist; migrate legacy flat keys once."""
    if not isinstance(lc, dict):
        lc = {}

    had_by_host = _BY_HOST_KEY in lc and isinstance(lc.get(_BY_HOST_KEY), dict)
    if had_by_host:
        by_host = dict(lc[_BY_HOST_KEY])
    else:
        by_host = default_by_host()

    legacy_enabled = lc.get(_LEGACY_ENABLED_KEY)
    legacy_deleted = lc.get(_LEGACY_FLAT_DELETED_KEY)

    if isinstance(legacy_enabled, list) and legacy_enabled:
        if had_by_host:
            t2i = dict(by_host.get("flux1_t2i") or _empty_slice())
            if not t2i.get("enabled_ids"):
                t2i["enabled_ids"] = [
                    str(x)
                    for x in legacy_enabled
                    if str(x) in LORA_CATALOG and LORA_CATALOG[str(x)].host_id == "flux1_t2i"
                ]
                by_host["flux1_t2i"] = t2i
        else:
            for lid in legacy_enabled:
                lid_s = str(lid)
                entry = LORA_CATALOG.get(lid_s)
                if entry is None:
                    continue
                host = entry.host_id
                if host not in by_host:
                    continue
                enabled_list = by_host[host]["enabled_ids"]
                if lid_s not in enabled_list:
                    enabled_list.append(lid_s)

    if isinstance(legacy_deleted, list):
        for lid in legacy_deleted:
            entry = LORA_CATALOG.get(str(lid))
            if entry is None:
                continue
            host = entry.host_id
            slice_ = dict(by_host.get(host) or _empty_slice())
            deleted = list(_slice_deleted_ids(slice_))
            lid_s = str(lid)
            if lid_s not in deleted:
                deleted.append(lid_s)
            slice_[DELETED_IDS_KEY] = deleted
            by_host[host] = slice_

    for host_id in LORA_HOST_ORDER:
        slice_ = by_host.get(host_id)
        if not isinstance(slice_, dict):
            by_host[host_id] = dict(default_by_host().get(host_id, _empty_slice()))
        else:
            by_host[host_id] = _normalize_host_slice(host_id, slice_, _catalog_for_lc(lc))

    lc[_BY_HOST_KEY] = by_host
    _ensure_by_model(lc, by_host)
    if USER_ENTRIES_KEY not in lc:
        lc[USER_ENTRIES_KEY] = {}
    elif not isinstance(lc.get(USER_ENTRIES_KEY), dict):
        lc[USER_ENTRIES_KEY] = {}
    if ENTRY_OVERRIDES_KEY not in lc:
        lc[ENTRY_OVERRIDES_KEY] = {}
    elif not isinstance(lc.get(ENTRY_OVERRIDES_KEY), dict):
        lc[ENTRY_OVERRIDES_KEY] = {}
    return lc


def lora_catalog_from_settings(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if settings is not None:
        imagegen = settings.get("imagegen") or {}
        lc = imagegen.get("lora_catalog")
        if isinstance(lc, dict) and lc:
            return migrate_lora_catalog(dict(lc))
    from imagegen_plugins.lora_catalog_store import load_lora_catalog_file

    return load_lora_catalog_file()


def model_state(
    settings: Optional[Dict[str, Any]] = None,
    model_key: str = "",
) -> Dict[str, List[str]]:
    lc = lora_catalog_from_settings(settings)
    by_model = lc.get(_BY_MODEL_KEY) or {}
    slice_ = by_model.get(model_key)
    if not isinstance(slice_, dict):
        return _empty_slice()
    return {
        "enabled_ids": list(slice_.get("enabled_ids") or []),
        DELETED_IDS_KEY: list(_slice_deleted_ids(slice_)),
    }


def deleted_lora_ids_for_model(
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> FrozenSet[str]:
    if isinstance(draft_by_model, dict) and model_key in draft_by_model:
        slice_ = draft_by_model.get(model_key)
        if isinstance(slice_, dict):
            return frozenset(_slice_deleted_ids(slice_))
    return frozenset(model_state(settings, model_key)[DELETED_IDS_KEY])


def hidden_lora_ids_for_model(
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> FrozenSet[str]:
    """Back-compat alias for deleted_lora_ids_for_model."""
    return deleted_lora_ids_for_model(model_key, settings)


def enabled_lora_ids_for_model(
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    st = model_state(settings, model_key)
    catalog = _catalog_for_lc(lora_catalog_from_settings(settings))
    return tuple(
        x
        for x in st["enabled_ids"]
        if x in catalog
        and entry_matches_lora_model(catalog[x], model_key, settings=settings)
    )




