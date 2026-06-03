#!/usr/bin/env python3
"""Per-base-model LoRA catalog state in settings.json (load, migrate, defaults)."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from imagegen_plugins.lora_catalogs.flux1_fill import FLUX1_FILL_LORAS
from imagegen_plugins.lora_catalogs.flux1_t2i import FLUX1_T2I_LORAS
from imagegen_plugins.lora_catalogs.flux2_klein import FLUX2_KLEIN_LORAS
from imagegen_plugins.lora_entry import DEFAULT_ENABLED_LORA_IDS_BY_HOST
from imagegen_plugins.lora_host_registry import LORA_HOST_ORDER
from imagegen_plugins.lora_model_registry import (
    LORA_SETTINGS_MODEL_ORDER,
    entry_matches_lora_model,
    lora_models_for_entry,
)

LORA_CATALOG = {**FLUX1_T2I_LORAS, **FLUX1_FILL_LORAS, **FLUX2_KLEIN_LORAS}

_LEGACY_ENABLED_KEY = "enabled_ids"
_LEGACY_DELETED_KEY = "deleted_ids"
_BY_HOST_KEY = "by_host"
_BY_MODEL_KEY = "by_model"


def _empty_slice() -> Dict[str, List[str]]:
    return {"enabled_ids": [], "hidden_ids": []}


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
            "hidden_ids": [],
        }
    return out


def default_by_model() -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {}
    for model_key in LORA_SETTINGS_MODEL_ORDER:
        enabled = list(DEFAULT_ENABLED_LORA_IDS_BY_MODEL.get(model_key, ()))
        out[model_key] = {
            "enabled_ids": [x for x in enabled if x in LORA_CATALOG],
            "hidden_ids": [],
        }
    return out


def _normalize_host_slice(host_id: str, slice_: Dict[str, Any]) -> Dict[str, List[str]]:
    enabled = slice_.get("enabled_ids")
    hidden = slice_.get("hidden_ids")
    return {
        "enabled_ids": [
            str(x)
            for x in (enabled if isinstance(enabled, list) else [])
            if str(x) in LORA_CATALOG and LORA_CATALOG[str(x)].host_id == host_id
        ],
        "hidden_ids": [
            str(x)
            for x in (hidden if isinstance(hidden, list) else [])
            if str(x) in LORA_CATALOG and LORA_CATALOG[str(x)].host_id == host_id
        ],
    }


def _normalize_model_slice(model_key: str, slice_: Dict[str, Any]) -> Dict[str, List[str]]:
    enabled = slice_.get("enabled_ids")
    hidden = slice_.get("hidden_ids")
    return {
        "enabled_ids": [
            str(x)
            for x in (enabled if isinstance(enabled, list) else [])
            if str(x) in LORA_CATALOG
            and entry_matches_lora_model(LORA_CATALOG[str(x)], model_key)
        ],
        "hidden_ids": [
            str(x)
            for x in (hidden if isinstance(hidden, list) else [])
            if str(x) in LORA_CATALOG
            and entry_matches_lora_model(LORA_CATALOG[str(x)], model_key)
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
        for lid in slice_.get("hidden_ids") or []:
            entry = LORA_CATALOG.get(str(lid))
            if entry is None:
                continue
            for mk in lora_models_for_entry(entry):
                if str(lid) not in out[mk]["hidden_ids"]:
                    out[mk]["hidden_ids"].append(str(lid))
    return out


def _ensure_by_model(lc: Dict[str, Any], by_host: Dict[str, Dict[str, List[str]]]) -> None:
    if _BY_MODEL_KEY not in lc:
        lc[_BY_MODEL_KEY] = _by_model_from_by_host(by_host)
    by_model = dict(lc.get(_BY_MODEL_KEY) or {})
    for model_key in LORA_SETTINGS_MODEL_ORDER:
        slice_ = by_model.get(model_key)
        if not isinstance(slice_, dict):
            by_model[model_key] = _empty_slice()
        else:
            by_model[model_key] = _normalize_model_slice(model_key, slice_)
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
    legacy_deleted = lc.get(_LEGACY_DELETED_KEY)

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
            hidden = list(slice_.get("hidden_ids") or [])
            lid_s = str(lid)
            if lid_s not in hidden:
                hidden.append(lid_s)
            slice_["hidden_ids"] = hidden
            by_host[host] = slice_

    for host_id in LORA_HOST_ORDER:
        slice_ = by_host.get(host_id)
        if not isinstance(slice_, dict):
            by_host[host_id] = _empty_slice()
        else:
            by_host[host_id] = _normalize_host_slice(host_id, slice_)

    lc[_BY_HOST_KEY] = by_host
    _ensure_by_model(lc, by_host)
    return lc


def lora_catalog_from_settings(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    lc = dict(imagegen.get("lora_catalog") or {})
    return migrate_lora_catalog(lc)


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
        "hidden_ids": list(slice_.get("hidden_ids") or []),
    }


def host_state(
    settings: Optional[Dict[str, Any]] = None,
    host_id: str = "",
) -> Dict[str, List[str]]:
    lc = lora_catalog_from_settings(settings)
    by_host = lc.get(_BY_HOST_KEY) or {}
    slice_ = by_host.get(host_id)
    if not isinstance(slice_, dict):
        return _empty_slice()
    return {
        "enabled_ids": list(slice_.get("enabled_ids") or []),
        "hidden_ids": list(slice_.get("hidden_ids") or []),
    }


def hidden_lora_ids_for_model(
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> FrozenSet[str]:
    return frozenset(model_state(settings, model_key)["hidden_ids"])


def enabled_lora_ids_for_model(
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    st = model_state(settings, model_key)
    hidden = frozenset(st["hidden_ids"])
    return tuple(
        x
        for x in st["enabled_ids"]
        if x in LORA_CATALOG
        and x not in hidden
        and entry_matches_lora_model(LORA_CATALOG[x], model_key)
    )


def hidden_lora_ids_for_host(
    host_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> FrozenSet[str]:
    return frozenset(host_state(settings, host_id)["hidden_ids"])


def enabled_lora_ids_for_host(
    host_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    """Legacy host union (settings grid should use per-model APIs)."""
    st = host_state(settings, host_id)
    hidden = frozenset(st["hidden_ids"])
    raw = st["enabled_ids"]
    if raw:
        return tuple(x for x in raw if x in LORA_CATALOG and x not in hidden)
    defaults = DEFAULT_ENABLED_LORA_IDS_BY_HOST.get(host_id, ())
    return tuple(x for x in defaults if x in LORA_CATALOG and x not in hidden)


def all_hidden_lora_ids(settings: Optional[Dict[str, Any]] = None) -> FrozenSet[str]:
    lc = lora_catalog_from_settings(settings)
    by_model = lc.get(_BY_MODEL_KEY) or {}
    out: set[str] = set()
    for model_key in LORA_SETTINGS_MODEL_ORDER:
        slice_ = by_model.get(model_key)
        if isinstance(slice_, dict):
            for lid in slice_.get("hidden_ids") or []:
                if str(lid) in LORA_CATALOG:
                    out.add(str(lid))
    return frozenset(out)
