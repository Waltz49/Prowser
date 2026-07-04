#!/usr/bin/env python3
"""Unified LoRA catalog facade (per-host curated entries)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, TYPE_CHECKING

from imagegen_plugins.lora_catalog_settings import (
    all_hidden_lora_ids,
    enabled_lora_ids_for_host,
    enabled_lora_ids_for_model,
    hidden_lora_ids_for_host,
    hidden_lora_ids_for_model,
    lora_catalog_from_settings,
    migrate_lora_catalog,
)
from imagegen_plugins.lora_model_registry import (
    entry_matches_lora_model,
    klein_lora_model_aliases,
    lora_model_key_for_plugin,
    lora_model_key_from_values,
    lora_models_for_entry,
)
from imagegen_plugins.lora_catalogs.flux1_fill import FLUX1_FILL_LORAS
from imagegen_plugins.lora_catalogs.flux1_t2i import FLUX1_T2I_LORAS
from imagegen_plugins.lora_catalogs.flux2_klein import FLUX2_KLEIN_LORAS
from imagegen_plugins.lora_catalogs.sd15 import SD15_LORAS
from imagegen_plugins.lora_entry import (
    DEFAULT_CACHE,
    DEFAULT_ENABLED_LORA_IDS,
    DEFAULT_ENABLED_LORA_IDS_BY_HOST,
    FluxLoraEntry,
    LORA_MIN_STEPS,
    PAPER_CUTOUT_LORA_PATH,
    _ALT_CACHE,
)
from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    LORA_PROBE_MODEL_ORDER,
)

_MODEL_SIZE_TAG_BY_KEY: Dict[str, str] = {
    FLUX2_KLEIN_4B: "4B",
    FLUX2_KLEIN_9B: "9B",
    FLUX2_KLEIN_9B_KV: "9B KV",
}
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX2_KLEIN,
    LORA_HOST_ORDER,
    get_lora_host,
    lora_hosts_for_settings,
)

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

LORA_CATALOG: Dict[str, FluxLoraEntry] = {
    **FLUX1_T2I_LORAS,
    **FLUX1_FILL_LORAS,
    **FLUX2_KLEIN_LORAS,
    **SD15_LORAS,
}

# Back-compat alias used across the codebase.
FLUX_LORA_CATALOG = LORA_CATALOG

MFLUX_LORA_GENERATE_PIPELINES: Tuple[str, ...] = ("flux_schnell_mflux_play",)
MFLUX_LORA_FILL_PIPELINES: Tuple[str, ...] = ("mflux_fill_expand", "mflux_fill_infill")
MFLUX_LORA_T2I_AND_FILL: Tuple[str, ...] = (
    MFLUX_LORA_GENERATE_PIPELINES + MFLUX_LORA_FILL_PIPELINES
)


def klein_lora_mismatch_message(entry: FluxLoraEntry, active_hf_model_id: str) -> str:
    from imagegen_plugins.image_gen_model_availability import model_display_name

    want = model_display_name("mflux_flux2_klein_create", entry.base_hf_model_id)
    have = model_display_name("mflux_flux2_klein_create", active_hf_model_id)
    return (
        f"LoRA «{entry.display_name}» is trained for {want} only. "
        f"You are using {have} — switch the Klein model in the Create or Edit dialog "
        f"or pick a LoRA for {have}."
    )


def merged_lora_catalog(settings: Optional[Dict[str, Any]] = None) -> Dict[str, FluxLoraEntry]:
    from imagegen_plugins.lora_user_entries import user_lora_entries_from_settings

    merged = dict(LORA_CATALOG)
    merged.update(user_lora_entries_from_settings(settings))
    return merged


def entries_for_host(
    host_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[FluxLoraEntry, ...]:
    return tuple(
        sorted(
            (e for e in merged_lora_catalog(settings).values() if e.host_id == host_id),
            key=lambda x: x.display_name.lower(),
        )
    )


def catalog_entries_sorted(
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[FluxLoraEntry, ...]:
    return tuple(
        sorted(
            merged_lora_catalog(settings).values(),
            key=lambda e: e.display_name.lower(),
        )
    )


def get_lora_entry(
    lora_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Optional[FluxLoraEntry]:
    entry = LORA_CATALOG.get(lora_id)
    if entry is not None:
        return entry
    from imagegen_plugins.lora_user_entries import user_lora_entries_from_settings

    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    return user_lora_entries_from_settings(settings).get(lora_id)


def catalog_cache_path(entry: FluxLoraEntry) -> Optional[Path]:
    if entry.local_path:
        return Path(entry.local_path).expanduser()
    if not entry.repo_id or not entry.filename:
        return None
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__") / entry.filename


def is_lora_installed(
    lora_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    entry = get_lora_entry(lora_id, settings)
    if entry is None:
        return False
    path = catalog_cache_path(entry)
    if path is None:
        return False
    if path.is_file() and path.stat().st_size > 1024:
        return True
    if entry.local_path:
        alt = _ALT_CACHE / "paper-cutout" / path.name
        if alt.is_file() and alt.stat().st_size > 1024:
            return True
    return False


def installed_lora_ids(settings: Optional[Dict[str, Any]] = None) -> FrozenSet[str]:
    return frozenset(
        lid for lid in merged_lora_catalog(settings) if is_lora_installed(lid, settings)
    )


def lora_model_support(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, ...]]:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    lc = migrate_lora_catalog(dict((settings.get("imagegen") or {}).get("lora_catalog") or {}))
    raw = lc.get("model_support")
    if not isinstance(raw, dict):
        return {}
    catalog = merged_lora_catalog(settings)
    out: Dict[str, Tuple[str, ...]] = {}
    for lid, models in raw.items():
        lid_s = str(lid)
        if lid_s not in catalog:
            continue
        if not isinstance(models, list):
            continue
        supported = tuple(
            m for m in LORA_PROBE_MODEL_ORDER if str(m) in {str(x) for x in models}
        )
        out[lid_s] = supported
    return out


def lora_base_display_name(entry: FluxLoraEntry, *, model_key: str = "") -> str:
    """Display name without redundant model-size suffix when the UI already filters by model."""
    name = entry.display_name.strip()
    tag = _MODEL_SIZE_TAG_BY_KEY.get((model_key or "").strip())
    if not tag:
        return name
    stripped = re.sub(
        rf"\s*\({re.escape(tag)}(?:\s+[^)]*)?\)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return stripped or name


def lora_choice_label(entry: FluxLoraEntry, *, model_key: str = "") -> str:
    """Combo/menu label; appends trigger hint when the catalog entry defines one."""
    base = lora_base_display_name(entry, model_key=model_key)
    trigger = (entry.trigger_word or "").strip()
    if trigger:
        return f"{base} - Trigger: {trigger}"
    return base


def lora_probe_prompt(entry: FluxLoraEntry, *, fallback: str = "test") -> str:
    """Prompt for Check LoRAs probes; includes the catalog trigger when defined."""
    trigger = (entry.trigger_word or "").strip()
    if not trigger:
        return fallback
    if entry.host_id == HOST_FLUX2_KLEIN:
        return f"Transform into {trigger}"
    return f"{trigger}, {fallback}"


def format_lora_model_support_suffix(supported_models: Tuple[str, ...]) -> str:
    if not supported_models:
        return ""
    labels = [m for m in LORA_PROBE_MODEL_ORDER if m in supported_models]
    if not labels:
        return ""
    return f" ({', '.join(labels)})"


def lora_probe_passed_for_model(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Whether this LoRA may be shown for the base model.

    Catalog entries with mflux_compatible=True are always shown (curated for MFLUX).
    Other entries: after Check LoRAs, only those with a successful probe on model_key;
    before any check, only mflux_compatible=True (same as above).
    """
    entry = get_lora_entry(lora_id, settings)
    if entry is None or entry.mflux_compatible is False:
        return False
    if not entry_matches_lora_model(entry, model_key):
        return False
    if entry.mflux_compatible is True:
        return True
    support = lora_model_support(settings)
    if not support:
        return False
    passed = support.get(lora_id)
    if passed is None:
        return False
    return any(m in passed for m in klein_lora_model_aliases(model_key))


def lora_settings_display_name(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
    *,
    model_key: str = "",
) -> str:
    """Settings grid label (no probe-model suffix; model is chosen in the page combo)."""
    _ = settings
    return lora_choice_label(entry, model_key=model_key)


def probe_models_for_lora_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Probe keys for Check LoRAs (full hf_model_id per base model)."""
    return lora_models_for_entry(entry)


def deleted_lora_ids(settings: Optional[Dict[str, Any]] = None) -> FrozenSet[str]:
    """All hidden LoRA ids (any host). Back-compat name."""
    return all_hidden_lora_ids(settings)


def catalog_entries_for_model(
    settings: Optional[Dict[str, Any]] = None,
    model_key: str = "",
) -> Tuple[FluxLoraEntry, ...]:
    """Settings grid: LoRAs that match this base model and passed Check LoRAs (if run)."""
    hidden = hidden_lora_ids_for_model(model_key, settings)
    return tuple(
        e
        for e in catalog_entries_sorted(settings)
        if lora_probe_passed_for_model(e.lora_id, model_key, settings)
        and e.lora_id not in hidden
    )


def catalog_entries_for_settings(
    settings: Optional[Dict[str, Any]] = None,
    host_id: Optional[str] = None,
    *,
    model_key: Optional[str] = None,
) -> Tuple[FluxLoraEntry, ...]:
    if model_key:
        return catalog_entries_for_model(settings, model_key)
    hidden = (
        hidden_lora_ids_for_host(host_id, settings)
        if host_id
        else all_hidden_lora_ids(settings)
    )
    entries = (
        entries_for_host(host_id, settings)
        if host_id
        else catalog_entries_sorted(settings)
    )
    return tuple(
        e for e in entries if e.mflux_compatible is not False and e.lora_id not in hidden
    )


def enabled_lora_ids(
    settings: Optional[Dict[str, Any]] = None,
    host_id: Optional[str] = None,
) -> Tuple[str, ...]:
    if host_id:
        return enabled_lora_ids_for_host(host_id, settings)
    # Legacy: union across flux1_t2i only for flat callers.
    return enabled_lora_ids_for_host("flux1_t2i", settings)


def lora_visible_for_run(
    lora_id: str,
    entry: FluxLoraEntry,
    *,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    host_id: Optional[str] = None,
) -> bool:
    _ = host_id
    if entry.mflux_compatible is False:
        return False
    if not entry_matches_lora_model(entry, model_key):
        return False
    if not lora_probe_passed_for_model(lora_id, model_key, settings):
        return False
    if lora_id in hidden_lora_ids_for_model(model_key, settings):
        return False
    if lora_id not in enabled_lora_ids_for_model(model_key, settings):
        return False
    return is_lora_installed(lora_id)


def lora_choices_for_plugin(
    plugin: "ImageGenModelPlugin",
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Run-dialog LoRA choices: enabled + installed for the active base model only."""
    host_id = getattr(plugin, "lora_host_id", None)
    model_key = lora_model_key_for_plugin(plugin)
    if not host_id or not model_key:
        return (("None", "none"),)
    choices: List[Tuple[str, str]] = [("None", "none")]
    for entry in entries_for_host(host_id, settings):
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
        ):
            choices.append((lora_choice_label(entry, model_key=model_key), entry.lora_id))
    return tuple(choices)


def lora_choices_for_pipeline(
    pipeline_id: str,
    plugin_hf_model_id: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    lora_host_id: Optional[str] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Back-compat: resolve host from pipeline or explicit lora_host_id."""
    from imagegen_plugins.lora_host_registry import lora_host_for_pipeline

    host_id = lora_host_id or lora_host_for_pipeline(pipeline_id)
    if not host_id:
        return (("None", "none"),)
    values = {
        "hf_model_id": plugin_hf_model_id,
        "pipeline_id": pipeline_id,
    }
    model_key = lora_model_key_from_values(values)
    if not model_key:
        return (("None", "none"),)
    choices: List[Tuple[str, str]] = [("None", "none")]
    for entry in entries_for_host(host_id, settings):
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
        ):
            choices.append((lora_choice_label(entry, model_key=model_key), entry.lora_id))
    return tuple(choices)


def resolve_plugin_base_model(hf_model_id: str, pipeline_id: str) -> str:
    """Deprecated: use lora_host_id on plugins. Kept for legacy callers."""
    hf = (hf_model_id or "").strip()
    if pipeline_id in MFLUX_LORA_FILL_PIPELINES or FLUX1_FILL_DEV in hf:
        return FLUX1_FILL_DEV
    if FLUX1_SCHNELL in hf.lower() or hf == FLUX1_SCHNELL:
        return FLUX1_SCHNELL
    return FLUX1_DEV


def lora_entry_min_steps(lora_id: str, settings: Optional[Dict[str, Any]] = None) -> Optional[int]:
    entry = get_lora_entry(lora_id, settings)
    return entry.min_steps if entry is not None else None


def manual_download_help(lora_id: str, settings: Optional[Dict[str, Any]] = None) -> str:
    entry = get_lora_entry(lora_id, settings)
    if entry is None:
        return "Unknown LoRA."
    if entry.local_path:
        return f"Local LoRA ({lora_id}): {entry.local_path}"
    dest = catalog_cache_path(entry)
    if dest is None:
        return "Unknown LoRA."
    return (
        f"Manual download ({lora_id}):\n"
        f"  URL: https://huggingface.co/{entry.repo_id}/resolve/main/{entry.filename}\n"
        f"  Save to: {dest}\n"
        f"Or: hf download {entry.repo_id} {entry.filename} --local-dir {dest.parent}"
    )


def sample_lora_download_entries() -> Tuple[FluxLoraEntry, ...]:
    return tuple(
        e
        for e in catalog_entries_sorted(None)
        if e.mflux_compatible is True and e.repo_id and e.filename
    )


def sample_flux_lora_download_entries() -> Tuple[FluxLoraEntry, ...]:
    """Back-compat alias; includes SD 1.5 LoRAs enabled by default."""
    return sample_lora_download_entries()


def _lora_download_local_dir(entry: FluxLoraEntry) -> Path:
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__")
