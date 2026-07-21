#!/usr/bin/env python3
"""Unified LoRA catalog facade (per-host curated entries)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, TYPE_CHECKING

from imagegen_plugins.lora_catalog_settings import (
    apply_entry_overrides,
    enabled_lora_ids_for_model,
    entry_overrides_from_lc,
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
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
)

_MODEL_SIZE_TAG_BY_KEY: Dict[str, str] = {
    FLUX2_KLEIN_4B: "4B",
    FLUX2_KLEIN_9B: "9B",
    FLUX2_KLEIN_9B_KV: "9B KV",
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX: "9B KV MLX",
}
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX2_KLEIN,
    LORA_HOST_ORDER,
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
    from imagegen_plugins.lora_user_entries import (
        is_user_lora_id,
        user_lora_entries_from_settings,
    )

    lc = lora_catalog_from_settings(settings)
    overrides = entry_overrides_from_lc(lc)
    merged = dict(LORA_CATALOG)
    merged.update(user_lora_entries_from_settings(settings))
    for lora_id, entry in merged.items():
        if is_user_lora_id(lora_id):
            continue
        override = overrides.get(lora_id)
        if override:
            merged[lora_id] = apply_entry_overrides(entry, override)
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
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    return merged_lora_catalog(settings).get(lora_id)


def catalog_cache_path(entry: FluxLoraEntry) -> Optional[Path]:
    if entry.local_path:
        return Path(entry.local_path).expanduser()
    if not entry.repo_id or not entry.filename:
        return None
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__") / entry.filename


def lora_weights_file_is_valid(path: Path) -> bool:
    """True when a LoRA weights file exists and can be opened (safetensors or legacy)."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if not resolved.is_file() or resolved.stat().st_size < 1024:
        return False
    if resolved.suffix.lower() != ".safetensors":
        return True
    try:
        from safetensors import safe_open

        with safe_open(str(resolved), framework="pt") as f:
            next(iter(f.keys()), None)
        return True
    except Exception:
        return False


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
    if lora_weights_file_is_valid(path):
        return True
    if entry.local_path:
        alt = _ALT_CACHE / "paper-cutout" / path.name
        if lora_weights_file_is_valid(alt):
            return True
    return False



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
    if not entry_matches_lora_model(entry, model_key, settings=settings):
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



def probe_models_for_lora_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Probe keys for Check LoRAs (full hf_model_id per base model)."""
    return lora_models_for_entry(entry)



def catalog_entries_for_model(
    settings: Optional[Dict[str, Any]] = None,
    model_key: str = "",
) -> Tuple[FluxLoraEntry, ...]:
    """Settings grid: LoRAs that match this base model and passed Check LoRAs (if run)."""
    return tuple(
        e
        for e in catalog_entries_sorted(settings)
        if lora_probe_passed_for_model(e.lora_id, model_key, settings)
    )


def catalog_entries_for_settings(
    settings: Optional[Dict[str, Any]] = None,
    host_id: Optional[str] = None,
    *,
    model_key: Optional[str] = None,
) -> Tuple[FluxLoraEntry, ...]:
    if model_key:
        return catalog_entries_for_model(settings, model_key)
    entries = (
        entries_for_host(host_id, settings)
        if host_id
        else catalog_entries_sorted(settings)
    )
    return tuple(e for e in entries if e.mflux_compatible is not False)



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
    if not entry_matches_lora_model(entry, model_key, settings=settings):
        return False
    if not lora_probe_passed_for_model(lora_id, model_key, settings):
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



def lora_entry_min_steps(lora_id: str, settings: Optional[Dict[str, Any]] = None) -> Optional[int]:
    entry = get_lora_entry(lora_id, settings)
    return entry.min_steps if entry is not None else None



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


def model_keys_for_lora_entry(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    """Base models in Settings → LoRA that use this catalog entry."""
    from imagegen_plugins.lora_model_registry import LORA_SETTINGS_MODEL_ORDER
    from imagegen_plugins.lora_user_entries import is_user_lora_id

    if is_user_lora_id(entry.lora_id):
        supported = lora_model_support(settings).get(entry.lora_id)
        if supported:
            order = set(LORA_SETTINGS_MODEL_ORDER)
            return tuple(str(m) for m in supported if str(m) in order)
        base = (entry.base_hf_model_id or "").strip()
        return (base,) if base else ()
    return tuple(
        mk
        for mk in LORA_SETTINGS_MODEL_ORDER
        if entry_matches_lora_model(entry, mk, settings=settings)
    )


def _lora_enabled_for_model(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]],
    draft_by_model: Optional[Dict[str, Any]],
) -> bool:
    if isinstance(draft_by_model, dict) and model_key in draft_by_model:
        slice_ = draft_by_model.get(model_key)
        if isinstance(slice_, dict):
            return lora_id in (slice_.get("enabled_ids") or [])
    from imagegen_plugins.lora_catalog_settings import model_state

    return lora_id in (model_state(settings, model_key).get("enabled_ids") or [])


def lora_shared_model_labels(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[str, ...]:
    """Display names for base models that share this LoRA weights file."""
    from imagegen_plugins.hf_model_ids import lora_model_display_name

    models = model_keys_for_lora_entry(entry, settings)
    if len(models) <= 1:
        return ()
    return tuple(lora_model_display_name(mk) for mk in models)


def lora_disk_delete_allowed(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Whether the trash control may delete this LoRA from disk.

    When multiple base models share one weights file, deletion is blocked while
    any of those models still has the LoRA enabled.
    """
    models = model_keys_for_lora_entry(entry, settings)
    if len(models) <= 1:
        return True
    for model_key in models:
        if _lora_enabled_for_model(entry.lora_id, model_key, settings, draft_by_model):
            return False
    return True


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    try:
        stop_resolved = stop_at.expanduser().resolve()
    except OSError:
        return
    cur = path
    while True:
        try:
            cur = cur.resolve()
        except OSError:
            break
        if cur == stop_resolved:
            break
        if not cur.is_dir():
            break
        try:
            if any(cur.iterdir()):
                break
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def delete_installed_lora_files(entry: FluxLoraEntry) -> None:
    """Remove downloaded LoRA weights from disk (and empty cache directories)."""
    import shutil

    from imagegen_plugins.lora_user_entries import is_user_lora_id

    if is_user_lora_id(entry.lora_id):
        from imagegen_plugins.image_gen_persistence import remove_user_lora

        remove_user_lora(entry.lora_id)
        return

    if entry.repo_id:
        dest_dir = _lora_download_local_dir(entry)
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir, ignore_errors=True)
            return

    path = catalog_cache_path(entry)
    if path is None:
        return
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return
    if resolved.is_file():
        parent = resolved.parent
        resolved.unlink(missing_ok=True)
        _remove_empty_parents(parent, stop_at=DEFAULT_CACHE)
        return
    if entry.local_path:
        local = Path(entry.local_path).expanduser()
        try:
            local = local.resolve()
        except OSError:
            return
        if local.is_file():
            parent = local.parent
            local.unlink(missing_ok=True)
            _remove_empty_parents(parent, stop_at=DEFAULT_CACHE)
