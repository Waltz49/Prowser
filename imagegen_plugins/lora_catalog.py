#!/usr/bin/env python3
"""Unified LoRA catalog facade (per-host curated entries)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, TYPE_CHECKING

from imagegen_plugins.lora_catalog_settings import (
    apply_entry_overrides,
    deleted_lora_ids_for_model,
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
from imagegen_plugins.lora_catalogs.sdxl import SDXL_LORAS
from imagegen_plugins.lora_catalogs.z_image_turbo import Z_IMAGE_TURBO_LORAS
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
    **SDXL_LORAS,
    **Z_IMAGE_TURBO_LORAS,
}

# Back-compat alias used across the codebase.
FLUX_LORA_CATALOG = LORA_CATALOG

MFLUX_LORA_GENERATE_PIPELINES: Tuple[str, ...] = (
    "flux_schnell_mflux_play",
    "mflux_z_image_turbo",
)
MFLUX_LORA_FILL_PIPELINES: Tuple[str, ...] = ("mflux_fill_expand", "mflux_fill_infill")
MFLUX_LORA_T2I_AND_FILL: Tuple[str, ...] = (
    MFLUX_LORA_GENERATE_PIPELINES + MFLUX_LORA_FILL_PIPELINES
)

LORA_LIFECYCLE_ACTIVE = "active"
LORA_LIFECYCLE_INSTALLED = "installed"
LORA_LIFECYCLE_UNINSTALLED = "uninstalled"
LORA_LIFECYCLE_DELETED = "deleted"


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


def local_lora_weights_path(
    lora_id: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    entry: Optional[FluxLoraEntry] = None,
) -> Optional[Path]:
    """Return on-disk weights path when present and valid; never downloads."""
    resolved = entry if entry is not None else get_lora_entry(lora_id, settings)
    if resolved is None:
        return None
    path = catalog_cache_path(resolved)
    if path is None:
        return None
    if lora_weights_file_is_valid(path):
        try:
            return path.expanduser().resolve()
        except OSError:
            return path.expanduser()
    if resolved.local_path:
        alt = _ALT_CACHE / "paper-cutout" / path.name
        if lora_weights_file_is_valid(alt):
            try:
                return alt.resolve()
            except OSError:
                return alt
    return None


def is_lora_installed(
    lora_id: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    entry: Optional[FluxLoraEntry] = None,
) -> bool:
    return local_lora_weights_path(lora_id, settings, entry=entry) is not None


def has_recovery_source(entry: FluxLoraEntry) -> bool:
    """True when weights can be reinstalled (HF, remote URL, local source file, or bundled path)."""
    if (entry.repo_id or "").strip() and (entry.filename or "").strip():
        return True
    for raw in (entry.source_path, entry.local_path):
        text = str(raw or "").strip()
        if not text:
            continue
        lower = text.lower()
        if lower.startswith(("http://", "https://")):
            if "civitai.com" in lower or "civit.red" in lower or "huggingface.co" in lower or "hf.co" in lower:
                return True
            continue
        if lora_weights_file_is_valid(Path(text).expanduser()):
            return True
    return False


def lora_install_source_url(entry: FluxLoraEntry) -> str:
    """Human-readable install source for progress UI."""
    repo_id = (entry.repo_id or "").strip()
    filename = (entry.filename or "").strip()
    if repo_id and filename:
        return f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    source = (entry.source_path or "").strip()
    if source.lower().startswith(("http://", "https://")):
        return source
    if repo_id:
        return f"https://huggingface.co/{repo_id}"
    if source:
        return source
    return (entry.local_path or "").strip()


def lora_install_progress_label(
    lora_id: str,
    *,
    model_key: str = "",
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    entry = get_lora_entry(lora_id, settings)
    if entry is None:
        return f"Downloading {lora_id}…"
    name = lora_base_display_name(entry, model_key=model_key) or entry.display_name
    url = lora_install_source_url(entry)
    if url:
        return f"Downloading {name} from\n{url}"
    return f"Downloading {name}…"


def lora_needs_compatibility_check(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    entry = get_lora_entry(lora_id, settings)
    if entry is None or entry.mflux_compatible is False:
        return False
    if not entry_matches_lora_model(entry, model_key, settings=settings):
        return False
    if entry.mflux_compatible is True:
        return False
    return not lora_probe_passed_for_model(lora_id, model_key, settings)


def lora_lifecycle_state(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> str:
    """Return active | installed | uninstalled | deleted for a library entry."""
    from imagegen_plugins.lora_user_entries import is_user_lora_id

    entry = get_lora_entry(lora_id, settings)
    if entry is None:
        return LORA_LIFECYCLE_DELETED
    if not is_user_lora_id(lora_id):
        if lora_id in deleted_lora_ids_for_model(
            model_key, settings, draft_by_model=draft_by_model
        ):
            return LORA_LIFECYCLE_DELETED
    if not is_lora_installed(lora_id, settings):
        return LORA_LIFECYCLE_UNINSTALLED
    if _lora_enabled_for_model(lora_id, model_key, settings, draft_by_model):
        return LORA_LIFECYCLE_ACTIVE
    return LORA_LIFECYCLE_INSTALLED


def lora_status_label(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> str:
    state = lora_lifecycle_state(
        lora_id, model_key, settings, draft_by_model=draft_by_model
    )
    if lora_needs_compatibility_check(lora_id, model_key, settings):
        return "needs check"
    if state == LORA_LIFECYCLE_ACTIVE:
        return "active"
    if state == LORA_LIFECYCLE_INSTALLED:
        return "installed"
    if state == LORA_LIFECYCLE_UNINSTALLED:
        return "uninstalled"
    return "deleted"


def lora_delete_is_uninstall(
    entry: FluxLoraEntry,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when delete should remove weights only (Uninstalled), not erase the entry."""
    if not is_lora_installed(entry.lora_id, settings):
        return False
    return has_recovery_source(entry)


def lora_delete_is_remove_from_library(
    entry: FluxLoraEntry,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when delete should hide/remove the library entry (Deleted state)."""
    from imagegen_plugins.lora_user_entries import is_user_lora_id

    state = lora_lifecycle_state(
        entry.lora_id, model_key, settings, draft_by_model=draft_by_model
    )
    if state == LORA_LIFECYCLE_UNINSTALLED:
        return True
    if is_user_lora_id(entry.lora_id) and not has_recovery_source(entry):
        return True
    if not is_user_lora_id(entry.lora_id) and not has_recovery_source(entry):
        return True
    return False



def lora_model_support(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, ...]]:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    lc = lora_catalog_from_settings(settings)
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


def lora_cross_family_models(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Tuple[str, ...]]:
    """Per-LoRA model keys where Check LoRAs passed outside the entry's host family."""
    from imagegen_plugins.lora_catalog_settings import CROSS_FAMILY_MODELS_KEY

    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    lc = lora_catalog_from_settings(settings)
    raw = lc.get(CROSS_FAMILY_MODELS_KEY)
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
        cross = tuple(
            m for m in LORA_PROBE_MODEL_ORDER if str(m) in {str(x) for x in models}
        )
        if cross:
            out[lid_s] = cross
    return out


def lora_model_is_cross_family(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    entry: Optional[FluxLoraEntry] = None,
    cross_family: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when model_key is a cross-family association for this LoRA."""
    mk = (model_key or "").strip()
    if not mk:
        return False
    if cross_family is not None:
        raw_cf = cross_family.get(lora_id, ())
    else:
        raw_cf = lora_cross_family_models(settings).get(lora_id, ())
    if isinstance(raw_cf, (list, tuple)) and raw_cf:
        return mk in {str(x) for x in raw_cf}
    resolved = entry if entry is not None else get_lora_entry(lora_id, settings)
    if resolved is None:
        return False
    ms = lora_model_support(settings).get(lora_id, ())
    if mk not in {str(x) for x in ms}:
        return False
    from imagegen_plugins.lora_model_registry import is_cross_family_lora_model

    return is_cross_family_lora_model(resolved, mk)


def lora_probe_history(
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    from imagegen_plugins.lora_catalog_settings import probe_history_from_lc

    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    lc = lora_catalog_from_settings(settings)
    return probe_history_from_lc(lc)


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
    from imagegen_plugins.lora_catalog_settings import lora_catalog_from_settings

    base = lora_base_display_name(entry, model_key=model_key)
    if model_key and lora_model_is_cross_family(entry.lora_id, model_key):
        base = f"{base} *"
    trigger = (entry.trigger_word or "").strip()
    if trigger:
        return f"{base} - Trigger: {trigger}"
    return base


def lora_probe_prompt(
    entry: FluxLoraEntry,
    *,
    fallback: str = "test",
    weights_path: Optional[str | Path] = None,
    allow_online: bool = False,
) -> str:
    """Prompt for Check LoRAs probes; prepends a known trigger only (never guessed)."""
    from imagegen_plugins.lora_trigger_resolve import lora_probe_prompt_with_resolved_trigger

    return lora_probe_prompt_with_resolved_trigger(
        entry,
        fallback=fallback,
        weights_path=weights_path,
        allow_online=allow_online,
    )



def lora_probe_passed_for_model(
    lora_id: str,
    model_key: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    entry: Optional[FluxLoraEntry] = None,
    model_support: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Whether this LoRA may be shown for the base model.

    Catalog entries with mflux_compatible=True are always shown (curated for MFLUX).
    Other entries: after Check LoRAs, only those with a successful probe on model_key;
    before any check, only mflux_compatible=True (same as above).
    """
    resolved = entry if entry is not None else get_lora_entry(lora_id, settings)
    if resolved is None or resolved.mflux_compatible is False:
        return False
    if not entry_matches_lora_model(
        resolved,
        model_key,
        model_support=model_support,
        settings=None if model_support is not None else settings,
    ):
        return False
    if resolved.mflux_compatible is True:
        return True
    if model_support is not None:
        from imagegen_plugins.lora_model_registry import _probe_supported_on_model

        return _probe_supported_on_model(resolved, model_key, model_support)
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
    *,
    draft_by_model: Optional[Dict[str, Any]] = None,
) -> Tuple[FluxLoraEntry, ...]:
    """Settings grid: LoRAs that match this base model and passed Check LoRAs (if run)."""
    from imagegen_plugins.lora_user_entries import is_user_lora_id

    deleted = deleted_lora_ids_for_model(
        model_key, settings, draft_by_model=draft_by_model
    )
    lc = lora_catalog_from_settings(settings)
    raw = lc.get("model_support")
    support = raw if isinstance(raw, dict) else None
    return tuple(
        e
        for e in catalog_entries_sorted(settings)
        if lora_probe_passed_for_model(
            e.lora_id, model_key, settings, entry=e, model_support=support
        )
        and (is_user_lora_id(e.lora_id) or e.lora_id not in deleted)
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
    enabled_ids: Optional[FrozenSet[str]] = None,
    model_support: Optional[Dict[str, Any]] = None,
) -> bool:
    _ = host_id
    if entry.mflux_compatible is False:
        return False
    enabled = (
        enabled_ids
        if enabled_ids is not None
        else frozenset(enabled_lora_ids_for_model(model_key, settings))
    )
    if lora_id not in enabled:
        return False
    if not lora_probe_passed_for_model(
        lora_id,
        model_key,
        settings,
        entry=entry,
        model_support=model_support,
    ):
        return False
    weights_path = local_lora_weights_path(lora_id, settings, entry=entry)
    if weights_path is None:
        return False
    try:
        from imagegen_plugins.mflux_lora_presets import assert_lora_compatible_for_model

        assert_lora_compatible_for_model(
            str(weights_path),
            model_key,
            catalog_host_id=entry.host_id,
        )
    except RuntimeError:
        return False
    return True


def _lora_choice_context(
    settings: Optional[Dict[str, Any]],
    model_key: str,
) -> Tuple[
    Dict[str, Any],
    FrozenSet[str],
    Optional[Dict[str, Any]],
    Tuple[FluxLoraEntry, ...],
]:
    """Load catalog once for building run-dialog LoRA choices."""
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    # Prefer one migrated load via settings embedding so callers avoid repeated file I/O.
    imagegen = settings.get("imagegen")
    if not isinstance(imagegen, dict) or not isinstance(imagegen.get("lora_catalog"), dict):
        lc = lora_catalog_from_settings(settings)
        settings = dict(settings)
        settings["imagegen"] = dict(imagegen or {})
        settings["imagegen"]["lora_catalog"] = lc
    enabled = frozenset(enabled_lora_ids_for_model(model_key, settings))
    lc = lora_catalog_from_settings(settings)
    raw = lc.get("model_support")
    support = raw if isinstance(raw, dict) else None
    return settings, enabled, support, catalog_entries_sorted(settings)


def lora_choices_for_plugin(
    plugin: "ImageGenModelPlugin",
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Run-dialog LoRA choices: enabled + installed for the active base model only."""
    host_id = getattr(plugin, "lora_host_id", None)
    model_key = lora_model_key_for_plugin(plugin)
    if not host_id or not model_key:
        return (("None", "none"),)
    settings, enabled, support, entries = _lora_choice_context(settings, model_key)
    choices: List[Tuple[str, str]] = [("None", "none")]
    if not enabled:
        return tuple(choices)
    for entry in entries:
        if entry.lora_id not in enabled:
            continue
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
            enabled_ids=enabled,
            model_support=support,
        ):
            choices.append((lora_choice_label(entry, model_key=model_key), entry.lora_id))
    return tuple(choices)


_EXIF_LORA_TRIGGER_SUFFIX_RE = re.compile(
    r"\s*-\s*trigger\s*:\s*.+$", re.IGNORECASE
)


def _normalize_exif_lora_token(name: str) -> str:
    from imagegen_plugins.image_gen_naming import strip_exif_lora_weight_suffix

    text = strip_exif_lora_weight_suffix(str(name or ""))
    text = _EXIF_LORA_TRIGGER_SUFFIX_RE.sub("", text).strip()
    return text.lower()


def _exif_lora_match_keys(
    entry: FluxLoraEntry,
    *,
    model_key: str = "",
) -> set[str]:
    keys: set[str] = set()
    for raw in (
        entry.display_name,
        lora_base_display_name(entry, model_key=model_key),
        entry.lora_id,
    ):
        token = _normalize_exif_lora_token(raw)
        if token:
            keys.add(token)
    repo_id = str(entry.repo_id or "").strip()
    if repo_id:
        keys.add(_normalize_exif_lora_token(repo_id))
        if "/" in repo_id:
            keys.add(_normalize_exif_lora_token(repo_id.rsplit("/", 1)[-1]))
    filename = str(entry.filename or "").strip()
    if filename:
        stem = os.path.splitext(filename)[0]
        token = _normalize_exif_lora_token(stem)
        if token:
            keys.add(token)
    return keys


def match_exif_lora_names_to_ids_and_scales(
    lora_text: str,
    plugin: "ImageGenModelPlugin",
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], Dict[str, float]]:
    """Map EXIF LoRA name(s) to installed catalog ids and optional per-id weights.

    Matches installed catalog entries by EXIF display name (including user-imported
    LoRAs whose host_id may differ from the active plugin). Weights are included only
    when present in EXIF (``name [0.9]``).
    """
    from imagegen_plugins.debug_exif_lora_trace import agent_exif_lora_dbg
    from imagegen_plugins.image_gen_naming import parse_exif_lora_name_and_weight

    target = str(lora_text or "").strip()
    if not target or target.lower() == "none":
        return [], {}
    from config import get_config

    if settings is None:
        settings = get_config().load_settings()
    model_key = lora_model_key_for_plugin(plugin) or ""
    entries = catalog_entries_sorted(settings)
    parts = [p.strip() for p in re.split(r"\s*\+\s*", target) if p.strip()]
    if len(parts) <= 1:
        parts = [target]
    matched_ids: List[str] = []
    scales_by_id: Dict[str, float] = {}
    for part in parts:
        _name, weight = parse_exif_lora_name_and_weight(part)
        part_token = _normalize_exif_lora_token(_name or part)
        if not part_token:
            continue
        found_id: Optional[str] = None
        model_match_id: Optional[str] = None
        for entry in entries:
            if not is_lora_installed(entry.lora_id, settings, entry=entry):
                continue
            if part_token not in _exif_lora_match_keys(entry, model_key=model_key):
                continue
            if entry_matches_lora_model(entry, model_key, settings=settings):
                found_id = entry.lora_id
                break
            if model_match_id is None:
                model_match_id = entry.lora_id
        if found_id is None:
            found_id = model_match_id
        if found_id is not None and found_id not in matched_ids:
            matched_ids.append(found_id)
            if weight is not None:
                scales_by_id[found_id] = float(weight)
    agent_exif_lora_dbg(
        "H3",
        "lora_catalog:match_exif_lora",
        "done",
        {
            "target": target,
            "model_key": model_key,
            "matched_ids": matched_ids,
            "catalog_entries": len(entries),
        },
    )
    return matched_ids, scales_by_id


def match_exif_lora_names_to_ids(
    lora_text: str,
    plugin: "ImageGenModelPlugin",
    settings: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Map EXIF LoRA name(s) to installed catalog ids for the active plugin."""
    matched_ids, _scales = match_exif_lora_names_to_ids_and_scales(
        lora_text, plugin, settings
    )
    return matched_ids



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
    settings, enabled, support, entries = _lora_choice_context(settings, model_key)
    choices: List[Tuple[str, str]] = [("None", "none")]
    if not enabled:
        return tuple(choices)
    for entry in entries:
        if entry.lora_id not in enabled:
            continue
        if lora_visible_for_run(
            entry.lora_id,
            entry,
            model_key=model_key,
            host_id=host_id,
            settings=settings,
            enabled_ids=enabled,
            model_support=support,
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


def remove_lora_weights_from_disk(entry: FluxLoraEntry) -> None:
    """Remove LoRA weight files from disk only (no settings mutation)."""
    import shutil

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


def delete_installed_lora_files(entry: FluxLoraEntry) -> None:
    """Remove downloaded LoRA weights from disk (and empty cache directories)."""
    from imagegen_plugins.lora_user_entries import is_user_lora_id, remove_user_lora_files

    if is_user_lora_id(entry.lora_id):
        remove_user_lora_files(entry)
        return

    remove_lora_weights_from_disk(entry)
