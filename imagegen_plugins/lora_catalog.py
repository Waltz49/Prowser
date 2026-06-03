#!/usr/bin/env python3
"""Unified LoRA catalog facade (per-host curated entries)."""

from __future__ import annotations

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
    lora_model_key_for_plugin,
    lora_model_key_from_values,
    lora_models_for_entry,
)
from imagegen_plugins.lora_catalogs.flux1_fill import FLUX1_FILL_LORAS
from imagegen_plugins.lora_catalogs.flux1_t2i import FLUX1_T2I_LORAS
from imagegen_plugins.lora_catalogs.flux2_klein import FLUX2_KLEIN_LORAS
from imagegen_plugins.lora_entry import (
    DEFAULT_CACHE,
    DEFAULT_ENABLED_LORA_IDS,
    DEFAULT_ENABLED_LORA_IDS_BY_HOST,
    FluxLoraEntry,
    LORA_MIN_STEPS,
    PAPER_CUTOUT_LORA_PATH,
    _ALT_CACHE,
)
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX2_KLEIN,
    LORA_HOST_ORDER,
    LORA_MODEL_ABBREV,
    LORA_PROBE_MODEL_ORDER,
    get_lora_host,
    lora_hosts_for_settings,
)

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

LORA_CATALOG: Dict[str, FluxLoraEntry] = {
    **FLUX1_T2I_LORAS,
    **FLUX1_FILL_LORAS,
    **FLUX2_KLEIN_LORAS,
}

# Back-compat alias used across the codebase.
FLUX_LORA_CATALOG = LORA_CATALOG

MFLUX_LORA_GENERATE_PIPELINES: Tuple[str, ...] = ("flux_schnell_mflux_play",)
MFLUX_LORA_FILL_PIPELINES: Tuple[str, ...] = ("mflux_fill_expand", "mflux_fill_infill")
MFLUX_LORA_T2I_AND_FILL: Tuple[str, ...] = (
    MFLUX_LORA_GENERATE_PIPELINES + MFLUX_LORA_FILL_PIPELINES
)


def klein_variant_from_model_name(model_name: str) -> Optional[str]:
    """Return '4b' or '9b' from mflux_model_name / hf_model_id, else None."""
    text = (model_name or "").strip().lower()
    if "9b" in text:
        return "9b"
    if "4b" in text:
        return "4b"
    return None


def klein_variant_for_plugin(plugin: "ImageGenModelPlugin") -> Optional[str]:
    if getattr(plugin, "lora_host_id", None) != HOST_FLUX2_KLEIN:
        return None
    defaults = getattr(plugin, "model_defaults", None) or {}
    name = str(defaults.get("mflux_model_name") or getattr(plugin, "hf_model_id", "") or "")
    return klein_variant_from_model_name(name)


def klein_variant_from_values(values: Dict[str, Any]) -> Optional[str]:
    name = str(
        values.get("mflux_model_name")
        or values.get("hf_model_id")
        or ""
    )
    return klein_variant_from_model_name(name)


def entry_matches_klein_variant(entry: FluxLoraEntry, variant: Optional[str]) -> bool:
    if not entry.klein_variant or not variant:
        return True
    return entry.klein_variant == variant


def klein_lora_mismatch_message(entry: FluxLoraEntry, variant: str) -> str:
    want = (entry.klein_variant or "?").upper()
    have = variant.upper()
    return (
        f"LoRA «{entry.display_name}» is trained for FLUX.2 Klein {want} only. "
        f"You are using Klein {have} edit — switch the model in the edit dialog "
        f"or pick a {have} LoRA."
    )


def entries_for_host(host_id: str) -> Tuple[FluxLoraEntry, ...]:
    return tuple(
        sorted(
            (e for e in LORA_CATALOG.values() if e.host_id == host_id),
            key=lambda x: x.display_name.lower(),
        )
    )


def catalog_entries_sorted() -> Tuple[FluxLoraEntry, ...]:
    return tuple(sorted(LORA_CATALOG.values(), key=lambda e: e.display_name.lower()))


def get_lora_entry(lora_id: str) -> Optional[FluxLoraEntry]:
    return LORA_CATALOG.get(lora_id)


def catalog_cache_path(entry: FluxLoraEntry) -> Optional[Path]:
    if entry.local_path:
        return Path(entry.local_path).expanduser()
    if not entry.repo_id or not entry.filename:
        return None
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__") / entry.filename


def is_lora_installed(lora_id: str) -> bool:
    entry = LORA_CATALOG.get(lora_id)
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


def installed_lora_ids() -> FrozenSet[str]:
    return frozenset(lid for lid in LORA_CATALOG if is_lora_installed(lid))


def lora_model_support(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, ...]]:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    lc = migrate_lora_catalog(dict((settings.get("imagegen") or {}).get("lora_catalog") or {}))
    raw = lc.get("model_support")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Tuple[str, ...]] = {}
    for lid, models in raw.items():
        lid_s = str(lid)
        if lid_s not in LORA_CATALOG:
            continue
        if not isinstance(models, list):
            continue
        supported = tuple(
            m for m in LORA_PROBE_MODEL_ORDER if str(m) in {str(x) for x in models}
        )
        out[lid_s] = supported
    return out


def format_lora_model_support_suffix(supported_models: Tuple[str, ...]) -> str:
    if not supported_models:
        return ""
    labels = [
        LORA_MODEL_ABBREV[m]
        for m in LORA_PROBE_MODEL_ORDER
        if m in supported_models
    ]
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
    entry = LORA_CATALOG.get(lora_id)
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
    return model_key in passed


def lora_settings_display_name(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    support = lora_model_support(settings).get(entry.lora_id)
    if support is None:
        return entry.display_name
    return entry.display_name + format_lora_model_support_suffix(support)


def probe_models_for_lora_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Probe keys for Check LoRAs (per host; Klein uses entry.klein_variant)."""
    from imagegen_plugins.lora_host_registry import PROBE_KLEIN_4B, PROBE_KLEIN_9B

    host = get_lora_host(entry.host_id)
    if host is None:
        return ()
    if entry.host_id == HOST_FLUX2_KLEIN:
        if entry.klein_variant == "4b":
            return (PROBE_KLEIN_4B,)
        if entry.klein_variant == "9b":
            return (PROBE_KLEIN_9B,)
        return (PROBE_KLEIN_4B, PROBE_KLEIN_9B)
    return host.probe_targets


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
        for e in catalog_entries_sorted()
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
    entries = entries_for_host(host_id) if host_id else catalog_entries_sorted()
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
    klein_variant: Optional[str] = None,
) -> bool:
    if entry.mflux_compatible is False:
        return False
    if not entry_matches_lora_model(entry, model_key):
        return False
    if host_id == HOST_FLUX2_KLEIN and not entry_matches_klein_variant(entry, klein_variant):
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
    kv = klein_variant_for_plugin(plugin)
    choices: List[Tuple[str, str]] = [("None", "none")]
    for entry in entries_for_host(host_id):
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
            klein_variant=kv,
        ):
            choices.append((entry.display_name, entry.lora_id))
    return tuple(choices)


def lora_choices_for_pipeline(
    pipeline_id: str,
    plugin_hf_model_id: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    lora_host_id: Optional[str] = None,
    klein_variant: Optional[str] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Back-compat: resolve host from pipeline or explicit lora_host_id."""
    from imagegen_plugins.lora_host_registry import lora_host_for_pipeline

    host_id = lora_host_id or lora_host_for_pipeline(pipeline_id)
    if not host_id:
        return (("None", "none"),)
    if host_id == HOST_FLUX2_KLEIN and klein_variant is None:
        klein_variant = klein_variant_from_model_name(plugin_hf_model_id)
    values = {
        "hf_model_id": plugin_hf_model_id,
        "pipeline_id": pipeline_id,
        "mflux_model_name": plugin_hf_model_id,
    }
    if klein_variant:
        values["mflux_model_name"] = (
            "flux2-klein-9b" if klein_variant == "9b" else "flux2-klein-4b"
        )
    model_key = lora_model_key_from_values(values)
    if not model_key:
        return (("None", "none"),)
    choices: List[Tuple[str, str]] = [("None", "none")]
    for entry in entries_for_host(host_id):
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
            klein_variant=klein_variant,
        ):
            choices.append((entry.display_name, entry.lora_id))
    return tuple(choices)


def resolve_plugin_base_model(hf_model_id: str, pipeline_id: str) -> str:
    """Deprecated: use lora_host_id on plugins. Kept for legacy callers."""
    hf = (hf_model_id or "").strip().lower()
    if pipeline_id in MFLUX_LORA_FILL_PIPELINES or "fill" in hf:
        return "fill"
    if hf in ("schnell",):
        return "schnell"
    if hf in ("dev",):
        return "dev"
    return "dev"


def lora_entry_min_steps(lora_id: str) -> Optional[int]:
    entry = LORA_CATALOG.get(lora_id)
    return entry.min_steps if entry is not None else None


def manual_download_help(lora_id: str) -> str:
    entry = LORA_CATALOG.get(lora_id)
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


def sample_flux_lora_download_entries() -> Tuple[FluxLoraEntry, ...]:
    return tuple(
        e
        for e in catalog_entries_sorted()
        if e.mflux_compatible is True and e.repo_id and e.filename
    )


def _lora_download_local_dir(entry: FluxLoraEntry) -> Path:
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__")
