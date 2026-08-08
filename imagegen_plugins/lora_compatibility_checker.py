#!/usr/bin/env python3
"""Probe LoRA compatibility against all installed base models (512x512 generation)."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from prowser_temp_files import ensure_temporary_files_directory
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    LORA_PROBE_MODEL_ORDER,
    REALISTIC_VISION_V4_NOVAE,
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    SD15_DEFAULT_VAE,
    SD15_LORA_MODEL_KEYS,
    SDXL_BASE_1_0,
    Z_IMAGE_TURBO_MFLUX_4BIT,
    lora_model_display_name,
)
from imagegen_plugins.lora_catalog import (
    FluxLoraEntry,
    catalog_entries_sorted,
    get_lora_entry,
    local_lora_weights_path,
    lora_choice_label,
    lora_model_support,
    lora_probe_history,
    lora_weights_file_is_valid,
)
from imagegen_plugins.lora_catalog_settings import model_state
from imagegen_plugins.lora_entry import DEFAULT_CACHE, _ALT_CACHE
from imagegen_plugins.lora_host_registry import HOST_FLUX1_T2I

from imagegen_plugins.lora_model_registry import (
    klein_lora_model_aliases,
    lora_models_for_entry,
    lora_probe_default_steps,
    lora_probe_model_is_local,
)
from imagegen_plugins.lora_probe_effect import LoraProbeBaselineCache

DOWNLOADS_LORA_DIR = Path.home() / "Downloads"
_PENDING_DOWNLOAD_LORA_ID = "__pending_download__"
# Check LoRAs always renders at this square size with each model's default steps.
LORA_PROBE_SIZE = 512

MODEL_SCOPE_ALL = "all"
MODEL_SCOPE_SELECTED = "selected"
LORA_SCOPE_ALL = "all"
LORA_SCOPE_SELECTED = "selected"
REGISTRATION_IGNORE_PREVIOUS = "ignore_previous"
REGISTRATION_SKIP_REGISTERED = "skip_registered"
REGISTRATION_ONLY_REGISTERED = "only_registered"


@dataclass
class CheckLorasOptions:
    model_scope: str = MODEL_SCOPE_ALL
    selected_model_keys: List[str] = field(default_factory=list)
    lora_scope: str = LORA_SCOPE_ALL
    selected_lora_keys: List[str] = field(default_factory=list)
    registration_mode: str = REGISTRATION_IGNORE_PREVIOUS
    probe_prompt: str = "test"
    skip_unchanged: bool = True
    check_cross_families: bool = True

    def resolved_model_keys(self) -> List[str]:
        installed = installed_probeable_models()
        installed_set = set(installed)
        if self.model_scope == MODEL_SCOPE_SELECTED and self.selected_model_keys:
            return [m for m in self.selected_model_keys if m in installed_set]
        return list(installed)


@dataclass(frozen=True)
class LoraProbeChoice:
    """One on-disk LoRA weight file for Check LoRAs options or Add LoRA → Find."""

    key: str
    label: str
    from_downloads: bool = False
    # Fill-in metadata for Add LoRA → Find.
    weights_path: str = ""
    display_name: str = ""
    trigger_word: Optional[str] = None
    scale: float = 1.0
    comment: Optional[str] = None
    repo_id: str = ""
    filename: str = ""
    source_path: Optional[str] = None

# Models probe_lora_on_model can exercise (T2I only — Fill is excluded).
_PROBEABLE_MODEL_KEYS = frozenset(
    {
        FLUX1_SCHNELL,
        FLUX1_DEV,
        FLUX2_KLEIN_4B,
        FLUX2_KLEIN_9B,
        FLUX2_KLEIN_9B_KV,
        SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        Z_IMAGE_TURBO_MFLUX_4BIT,
        SDXL_BASE_1_0,
        *SD15_LORA_MODEL_KEYS,
    }
)


@dataclass
class LoraCheckStats:
    loras_total: int = 0
    loras_done: int = 0
    lora_index: int = 0  # 1-based current LoRA among those being probed
    models_total: int = 0  # unique installed probeable models in plan
    models_for_lora: int = 0
    model_index_for_lora: int = 0  # 1-based within current LoRA
    probes_done: int = 0
    probes_total: int = 0
    gpu_probes_done: int = 0
    probe_current: int = 0  # 1-based in-flight / just-finished probe
    supported_loras: int = 0
    removed_loras: int = 0
    skipped_loras: int = 0
    skipped_not_on_disk: int = 0
    skipped_model_probes: int = 0
    newly_enabled_count: int = 0
    newly_supported_count: int = 0
    passed_probe_count: int = 0
    failed_probe_count: int = 0
    skipped_hidden_count: int = 0
    downloads_scanned: int = 0
    downloads_deduped: int = 0
    downloads_registered: int = 0
    downloads_failed: int = 0
    skipped_registered_probes: int = 0
    files_discovered: int = 0
    files_deduped: int = 0
    skipped_unchanged: int = 0
    skipped_unchanged_probes: int = 0
    # All (lora, model) pairs visited in the run loop (GPU + history + reg skips).
    progress_pairs_total: int = 0
    current_lora_label: str = ""
    last_result: str = ""  # pass | fail | skip | ""
    # Short in-flight status for the progress dialog (baseline / render / compare).
    probe_activity: str = ""
    # Shared probe prompt shown in the progress dialog (may include triggers).
    probe_prompt: str = ""


@dataclass
class LoraFileFingerprint:
    md5: str
    mtime: float
    size: int
    path: str


@dataclass
class LoraProbePlanItem:
    entry: FluxLoraEntry
    models: List[str]
    weights_path: Path
    from_downloads: bool = False
    fingerprint: Optional[LoraFileFingerprint] = None
    history_key: str = ""
    probed_models_from_history: frozenset[str] = field(default_factory=frozenset)
    cached_support: List[str] = field(default_factory=list)


@dataclass
class _LoraProbeState:
    plan_item: LoraProbePlanItem
    entry: FluxLoraEntry
    lora_id: str
    lora_label: str
    lora_path: str
    prev_models: Set[str]
    supported: List[str]
    probed: bool = False
    fingerprint: Optional[LoraFileFingerprint] = None
    history_key: str = ""
    models_completed: Set[str] = field(default_factory=set)


@dataclass
class PreparedLoraProbePlan:
    candidates: List[FluxLoraEntry]
    plan: List[LoraProbePlanItem]
    stats: LoraCheckStats


@dataclass
class LoraCheckChange:
    kind: str  # newly_supported | lost_support | newly_enabled | skipped_hidden | failed | passed | skipped_not_on_disk | downloads_deduped | downloads_registered | downloads_failed
    lora_id: str
    lora_label: str
    model_key: str = ""
    model_label: str = ""


@dataclass
class LoraCheckResult:
    model_support: Dict[str, List[str]] = field(default_factory=dict)
    cross_family_models: Dict[str, List[str]] = field(default_factory=dict)
    by_model: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    changes: List[LoraCheckChange] = field(default_factory=list)
    hidden_by_host: Dict[str, List[str]] = field(default_factory=dict)
    stats: LoraCheckStats = field(default_factory=LoraCheckStats)
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    probe_history: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    previous_support: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    registration_mode: str = REGISTRATION_IGNORE_PREVIOUS

    @property
    def deleted_ids(self) -> List[str]:
        """Flat list of hidden ids (all hosts) for back-compat."""
        out: List[str] = []
        for ids in self.hidden_by_host.values():
            out.extend(ids)
        return sorted(set(out))


def lora_check_work_total(stats: LoraCheckStats) -> int:
    """Denominator for progress: every (lora, model) pair the run loop visits."""
    if stats.progress_pairs_total > 0:
        return stats.progress_pairs_total
    return stats.probes_total + stats.skipped_unchanged_probes


def installed_probeable_models() -> List[str]:
    """Installed base models that Check LoRAs can probe."""
    return [
        m
        for m in LORA_PROBE_MODEL_ORDER
        if m in _PROBEABLE_MODEL_KEYS and lora_probe_model_is_local(m)
    ]


def check_loras_options_from_settings(
    settings: Optional[Dict[str, Any]] = None,
) -> CheckLorasOptions:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    raw = (settings.get("imagegen") or {}).get("check_loras") or {}
    installed_set = set(installed_probeable_models())

    scope = str(raw.get("model_scope") or MODEL_SCOPE_ALL)
    if scope not in (MODEL_SCOPE_ALL, MODEL_SCOPE_SELECTED):
        scope = MODEL_SCOPE_ALL

    selected = [
        str(m) for m in (raw.get("selected_model_keys") or []) if str(m) in installed_set
    ]
    if scope == MODEL_SCOPE_SELECTED and not selected:
        scope = MODEL_SCOPE_ALL

    mode = str(raw.get("registration_mode") or REGISTRATION_IGNORE_PREVIOUS)
    if mode not in (
        REGISTRATION_IGNORE_PREVIOUS,
        REGISTRATION_SKIP_REGISTERED,
        REGISTRATION_ONLY_REGISTERED,
    ):
        mode = REGISTRATION_IGNORE_PREVIOUS

    probe_prompt = str(raw.get("probe_prompt") or "test").strip() or "test"
    skip_unchanged = bool(raw.get("skip_unchanged", True))
    check_cross_families = bool(raw.get("check_cross_families", True))

    lora_scope = str(raw.get("lora_scope") or LORA_SCOPE_ALL)
    if lora_scope not in (LORA_SCOPE_ALL, LORA_SCOPE_SELECTED):
        lora_scope = LORA_SCOPE_ALL
    selected_lora_keys = [str(k) for k in (raw.get("selected_lora_keys") or []) if str(k)]
    if lora_scope == LORA_SCOPE_SELECTED and not selected_lora_keys:
        lora_scope = LORA_SCOPE_ALL

    return CheckLorasOptions(
        model_scope=scope,
        selected_model_keys=selected,
        lora_scope=lora_scope,
        selected_lora_keys=selected_lora_keys,
        registration_mode=mode,
        probe_prompt=probe_prompt,
        skip_unchanged=skip_unchanged,
        check_cross_families=check_cross_families,
    )


def persist_check_loras_options(options: CheckLorasOptions) -> None:
    from config import get_config

    settings = get_config().load_settings()
    imagegen = dict(settings.get("imagegen") or {})
    imagegen["check_loras"] = {
        "model_scope": options.model_scope,
        "selected_model_keys": list(options.selected_model_keys),
        "lora_scope": options.lora_scope,
        "selected_lora_keys": list(options.selected_lora_keys),
        "registration_mode": options.registration_mode,
        "probe_prompt": options.probe_prompt,
        "skip_unchanged": bool(options.skip_unchanged),
        "check_cross_families": bool(options.check_cross_families),
    }
    settings["imagegen"] = imagegen
    get_config().save_settings(settings)


def _probe_should_run(
    lora_id: str,
    model_key: str,
    previous_support: Dict[str, Tuple[str, ...]],
    registration_mode: str,
) -> bool:
    if registration_mode == REGISTRATION_IGNORE_PREVIOUS:
        return True
    prev = set(previous_support.get(lora_id, ()))
    registered = model_key in prev
    if registration_mode == REGISTRATION_SKIP_REGISTERED:
        return not registered
    if registration_mode == REGISTRATION_ONLY_REGISTERED:
        return registered
    return True


def _count_probes_in_plan(
    plan: List[LoraProbePlanItem],
    previous_support: Dict[str, Tuple[str, ...]],
    registration_mode: str,
) -> int:
    total = 0
    for item in plan:
        for model_key in item.models:
            if model_key in item.probed_models_from_history:
                continue
            if _probe_should_run(
                item.entry.lora_id,
                model_key,
                previous_support,
                registration_mode,
            ):
                total += 1
    return total


def _probeable_local_models(_entry: FluxLoraEntry) -> List[str]:
    return installed_probeable_models()


def _probe_models_for_entry(
    entry: FluxLoraEntry,
    local_models: List[str],
    *,
    check_cross_families: bool = True,
) -> List[str]:
    """
    Which selected base models to probe for this LoRA.

    Curated ``mflux_compatible=True`` entries and orphan Downloads files keep
    cross-host discovery (every selected installed model). Other entries probe
    their host family; when ``check_cross_families`` is set, other installed
    host families are included as well.
    """
    if (
        entry.mflux_compatible is True
        or entry.lora_id == _PENDING_DOWNLOAD_LORA_ID
    ):
        return list(local_models)
    from imagegen_plugins.lora_model_registry import host_id_for_lora_model

    host = (entry.host_id or "").strip()
    same_host: List[str] = []
    if host:
        same_host = [m for m in local_models if host_id_for_lora_model(m) == host]
    if not same_host:
        intended = lora_models_for_entry(entry)
        if not intended:
            return list(local_models)
        allowed: Set[str] = set()
        for model_key in intended:
            allowed.update(klein_lora_model_aliases(model_key))
        same_host = [m for m in local_models if m in allowed]
    if not check_cross_families:
        return same_host if same_host else list(local_models)
    cross_host = (
        [m for m in local_models if host_id_for_lora_model(m) != host]
        if host
        else []
    )
    out: List[str] = []
    seen: Set[str] = set()
    for model_key in same_host + cross_host:
        if model_key not in seen:
            seen.add(model_key)
            out.append(model_key)
    return out if out else list(local_models)


def _md5_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _size_conflict_set(paths: Iterable[Path]) -> Set[int]:
    """Sizes that appear on more than one path (only these need MD5)."""
    counts: Dict[int, int] = {}
    for path in paths:
        try:
            size = int(path.stat().st_size)
        except OSError:
            continue
        counts[size] = counts.get(size, 0) + 1
    return {size for size, count in counts.items() if count > 1}


def _content_digest_for_path(
    path: Path,
    digest_cache: Dict[Path, str],
    *,
    size: Optional[int] = None,
    hash_sizes: Optional[Set[int]] = None,
) -> Optional[str]:
    """
    Content id for dedupe/history: MD5 only when ``size`` is in ``hash_sizes``.

    Unique sizes use ``size:<bytes>`` — files of different length cannot share an MD5.
    """
    try:
        if size is None:
            size = int(path.stat().st_size)
        if hash_sizes is not None and size not in hash_sizes:
            return f"size:{size}"
        digest = digest_cache.get(path)
        if digest is None:
            digest = _md5_file(path)
            digest_cache[path] = digest
        return digest
    except OSError:
        return None


def _downloads_safetensors_paths() -> List[Path]:
    """Top-level ~/Downloads/*.safetensors only (not recursive)."""
    root = DOWNLOADS_LORA_DIR.expanduser()
    if not root.is_dir():
        return []
    paths: List[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_file() or child.suffix.lower() != ".safetensors":
            continue
        try:
            paths.append(child.resolve())
        except OSError:
            paths.append(child)
    return paths


def _cache_safetensors_paths(root: Path) -> List[Path]:
    expanded = root.expanduser()
    if not expanded.is_dir():
        return []
    paths: List[Path] = []
    for path in sorted(expanded.rglob("*.safetensors")):
        if not path.is_file():
            continue
        try:
            paths.append(path.resolve())
        except OSError:
            paths.append(path)
    return paths


def _discover_safetensors_paths() -> List[Path]:
    paths: List[Path] = []
    seen: Set[Path] = set()
    for root in (DEFAULT_CACHE, _ALT_CACHE):
        for path in _cache_safetensors_paths(root):
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    for path in _downloads_safetensors_paths():
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _fingerprint_for_path(
    path: Path,
    digest_cache: Dict[Path, str],
    *,
    hash_sizes: Optional[Set[int]] = None,
) -> Optional[LoraFileFingerprint]:
    try:
        st = path.stat()
        size = int(st.st_size)
        digest = _content_digest_for_path(
            path,
            digest_cache,
            size=size,
            hash_sizes=hash_sizes,
        )
        if digest is None:
            return None
        return LoraFileFingerprint(
            md5=digest,
            mtime=float(st.st_mtime),
            size=size,
            path=str(path),
        )
    except OSError:
        return None


def _probe_history_key(lora_id: str, fingerprint: LoraFileFingerprint) -> str:
    if lora_id and lora_id != _PENDING_DOWNLOAD_LORA_ID:
        return lora_id
    return f"md5:{fingerprint.md5}"


def _fingerprint_unchanged(
    fingerprint: LoraFileFingerprint,
    history_slice: Optional[Dict[str, Any]],
) -> bool:
    if not history_slice:
        return False
    try:
        return (
            str(history_slice.get("md5") or "").lower() == fingerprint.md5.lower()
            and float(history_slice.get("mtime")) == fingerprint.mtime
            and int(history_slice.get("size")) == fingerprint.size
        )
    except (TypeError, ValueError):
        return False


def _history_models_probed(
    history_slice: Optional[Dict[str, Any]],
    local_models: Optional[List[str]] = None,
) -> Set[str]:
    if not history_slice:
        return set()
    raw = history_slice.get("models_probed")
    if isinstance(raw, (list, tuple)) and raw:
        return {str(m) for m in raw if str(m)}
    if history_slice.get("complete") is True and local_models:
        return set(local_models)
    return set()


def _plan_item_from_history(
    *,
    fingerprint: LoraFileFingerprint,
    history_key: str,
    hist: Optional[Dict[str, Any]],
    local_models: List[str],
    skip_unchanged: bool,
) -> Tuple[frozenset[str], List[str], bool]:
    """Return (probed_models, cached_support, all_models_reused)."""
    if not skip_unchanged or hist is None:
        return frozenset(), [], False
    if not _fingerprint_unchanged(fingerprint, hist):
        return frozenset(), [], False
    probed = frozenset(
        m for m in _history_models_probed(hist, local_models) if m in local_models
    )
    cached = _history_support_models(hist, local_models) if probed else []
    all_reused = probed.issuperset(set(local_models))
    return probed, cached, all_reused


def _history_support_models(
    history_slice: Optional[Dict[str, Any]],
    local_models: List[str],
) -> List[str]:
    if not history_slice:
        return []
    models_raw = history_slice.get("model_support")
    if not isinstance(models_raw, (list, tuple)):
        return []
    allowed = set(local_models)
    return [str(m) for m in models_raw if str(m) in allowed]


def _resolve_catalog_weight_path(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]],
) -> Optional[Path]:
    path = local_lora_weights_path(entry.lora_id, settings, entry=entry)
    if path is not None:
        return path
    for raw in (entry.source_path, entry.local_path):
        text = str(raw or "").strip()
        if not text:
            continue
        candidate = Path(text).expanduser()
        if lora_weights_file_is_valid(candidate):
            try:
                return candidate.resolve()
            except OSError:
                return candidate
    return None


def _catalog_weight_paths(settings: Optional[Dict[str, Any]]) -> List[Path]:
    paths: List[Path] = []
    seen: Set[Path] = set()
    for entry in catalog_entries_sorted(settings):
        path = _resolve_catalog_weight_path(entry, settings)
        if path is None or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _catalog_md5_index(
    settings: Optional[Dict[str, Any]],
    digest_cache: Dict[Path, str],
    *,
    hash_sizes: Optional[Set[int]] = None,
) -> Dict[str, str]:
    """Map content digest -> catalog lora_id (first match)."""
    out: Dict[str, str] = {}
    for entry in catalog_entries_sorted(settings):
        path = _resolve_catalog_weight_path(entry, settings)
        if path is None:
            continue
        digest = _content_digest_for_path(path, digest_cache, hash_sizes=hash_sizes)
        if digest is None:
            continue
        out.setdefault(digest, entry.lora_id)
    return out


def _path_is_registered(
    path: Path,
    settings: Optional[Dict[str, Any]],
) -> bool:
    from imagegen_plugins.lora_host_registry import LORA_HOSTS
    from imagegen_plugins.lora_user_entries import find_user_lora_for_source

    for host_id in LORA_HOSTS:
        if find_user_lora_for_source(path, host_id=host_id, settings=settings) is not None:
            return True
    return False


def _installed_lora_md5_index(
    settings: Optional[Dict[str, Any]],
    *,
    cache: Optional[Dict[Path, str]] = None,
    hash_sizes: Optional[Set[int]] = None,
) -> Dict[str, Path]:
    """Map content digest -> installed LoRA weights path."""
    digest_cache = cache if cache is not None else {}
    out: Dict[str, Path] = {}
    for entry in catalog_entries_sorted(settings):
        path = local_lora_weights_path(entry.lora_id, settings)
        if path is None:
            continue
        digest = _content_digest_for_path(path, digest_cache, hash_sizes=hash_sizes)
        if digest is None:
            continue
        out.setdefault(digest, path)
    return out


def _primary_model_key(supported: List[str]) -> str:
    order = {m: i for i, m in enumerate(LORA_PROBE_MODEL_ORDER)}
    return sorted(supported, key=lambda m: order.get(m, 999))[0]


def dedupe_downloads_loras(
    settings: Optional[Dict[str, Any]],
    *,
    changes: Optional[List[LoraCheckChange]] = None,
) -> Tuple[int, int]:
    """
    Delete duplicate .safetensors in ~/Downloads that match installed LoRAs
    (size-first; MD5 only when sizes collide).
    Returns (scanned_count, deleted_count).
    """
    paths = _downloads_safetensors_paths()
    if not paths:
        return 0, 0
    digest_cache: Dict[Path, str] = {}
    installed_paths = [
        path
        for entry in catalog_entries_sorted(settings)
        for path in (local_lora_weights_path(entry.lora_id, settings),)
        if path is not None
    ]
    hash_sizes = _size_conflict_set([*installed_paths, *paths])
    installed_by_md5 = _installed_lora_md5_index(
        settings,
        cache=digest_cache,
        hash_sizes=hash_sizes,
    )
    seen_download_md5: Set[str] = set()
    deleted = 0
    for path in paths:
        digest = _content_digest_for_path(path, digest_cache, hash_sizes=hash_sizes)
        if digest is None:
            continue
        duplicate = digest in installed_by_md5 or digest in seen_download_md5
        seen_download_md5.add(digest)
        if not duplicate:
            continue
        try:
            path.unlink()
            deleted += 1
            if changes is not None:
                changes.append(
                    LoraCheckChange(
                        kind="downloads_deduped",
                        lora_id="",
                        lora_label=path.name,
                    )
                )
            print(f"[Check LoRAs] Deleted duplicate download: {path}")
        except OSError as exc:
            print(f"[Check LoRAs] Could not delete duplicate download {path}: {exc}")
    return len(paths), deleted


def _downloads_probe_candidates(
    settings: Optional[Dict[str, Any]],
    *,
    planned_paths: Set[Path],
    planned_md5: Set[str],
    digest_cache: Dict[Path, str],
    catalog_md5: Dict[str, str],
    stats: LoraCheckStats,
    hash_sizes: Optional[Set[int]] = None,
    allowed_lora_keys: Optional[Set[str]] = None,
) -> List[Path]:
    remaining: List[Path] = []
    seen_md5 = set(planned_md5)
    for path in _discover_safetensors_paths():
        if path in planned_paths:
            continue
        if _path_is_registered(path, settings):
            continue
        if (
            allowed_lora_keys is not None
            and not (_orphan_path_selection_keys(path) & allowed_lora_keys)
        ):
            continue
        digest = _content_digest_for_path(path, digest_cache, hash_sizes=hash_sizes)
        if digest is None:
            continue
        if digest in catalog_md5:
            continue
        if digest in seen_md5:
            stats.files_deduped += 1
            continue
        seen_md5.add(digest)
        remaining.append(path)
    return remaining


def count_local_lora_probes(entries: List[FluxLoraEntry]) -> int:
    """Probe count for progress UI (installed, probeable base models only)."""
    local_models = installed_probeable_models()
    if not local_models:
        return 0
    return len(entries) * len(local_models)


def _probe_plan_item_choice_key(item: LoraProbePlanItem) -> str:
    if item.history_key:
        return item.history_key
    if item.fingerprint is not None:
        return _probe_history_key(item.entry.lora_id, item.fingerprint)
    return str(item.entry.lora_id or "")


def _probe_plan_item_selection_keys(item: LoraProbePlanItem) -> Set[str]:
    """Keys that may appear in Check LoRAs options (legacy history keys + find keys)."""
    keys: Set[str] = set()
    primary = _probe_plan_item_choice_key(item)
    if primary:
        keys.add(primary)
    lora_id = str(item.entry.lora_id or "")
    if lora_id and lora_id != _PENDING_DOWNLOAD_LORA_ID:
        keys.add(lora_id)
    path = str(item.weights_path or "")
    if path:
        keys.add(path)
        keys.add(f"path:{path}")
    return keys


def _probe_plan_item_choice_label(item: LoraProbePlanItem) -> str:
    if item.from_downloads:
        return (item.entry.display_name or "").strip() or item.entry.lora_id
    return lora_choice_label(item.entry)


def _selected_lora_key_set(options: CheckLorasOptions) -> Optional[Set[str]]:
    """Return allowed LoRA option keys, or None when every discovered LoRA is in scope."""
    if options.lora_scope != LORA_SCOPE_SELECTED or not options.selected_lora_keys:
        return None
    allowed = {str(k) for k in options.selected_lora_keys if str(k)}
    return allowed or None


def _catalog_entry_selection_keys(
    entry: FluxLoraEntry,
    path: Optional[Path],
) -> Set[str]:
    keys: Set[str] = set()
    lora_id = str(entry.lora_id or "")
    if lora_id and lora_id != _PENDING_DOWNLOAD_LORA_ID:
        keys.add(lora_id)
    if path is not None:
        text = str(path)
        keys.add(text)
        keys.add(f"path:{text}")
    return keys


def _orphan_path_selection_keys(path: Path) -> Set[str]:
    text = str(path)
    return {text, f"path:{text}"}


def _filter_plan_by_lora_scope(
    plan: List[LoraProbePlanItem],
    options: CheckLorasOptions,
) -> List[LoraProbePlanItem]:
    allowed = _selected_lora_key_set(options)
    if allowed is None:
        return plan
    return [
        item
        for item in plan
        if _probe_plan_item_selection_keys(item) & allowed
    ]


def discover_check_lora_choices(
    settings: Optional[Dict[str, Any]],
    *,
    dedupe_downloads: bool = False,
) -> List[LoraProbeChoice]:
    """
    Prescan on-disk LoRA weights for the Check LoRAs options dialog.

    Uses the same lightweight path scan as Add LoRA → Find (no MD5 / probe plan).
    ``dedupe_downloads`` is accepted for call-site compatibility and ignored here.
    """
    del dedupe_downloads  # options listing does not delete or hash Downloads
    choices = discover_find_lora_choices(settings)
    # Catalog entries first, then orphans — matches prior Check LoRAs ordering.
    choices.sort(key=lambda c: (c.from_downloads, (c.label or "").lower()))
    return choices


def discover_find_lora_choices(
    settings: Optional[Dict[str, Any]],
) -> List[LoraProbeChoice]:
    """
    Fast Add LoRA → Find listing: catalog entries with local weights plus orphan
    .safetensors under cache/Downloads. Path-based only — no MD5 or probe plan.

    Collapses same-name + same-size copies (catalog preferred over orphans).
    """
    from imagegen_plugins.lora_user_entries import display_name_from_path

    choices: List[LoraProbeChoice] = []
    planned_paths: Set[Path] = set()
    seen_keys: Set[str] = set()
    # (display_name.lower(), size) — duplicate imports often share both.
    seen_name_size: Set[Tuple[str, int]] = set()

    def _remember_name_size(name: str, path: Path) -> bool:
        """Return True if this name+size is new and should be listed."""
        text = (name or "").strip().lower()
        if not text:
            return True
        try:
            key = (text, int(path.stat().st_size))
        except OSError:
            return True
        if key in seen_name_size:
            return False
        seen_name_size.add(key)
        return True

    for entry in catalog_entries_sorted(settings):
        if entry.mflux_compatible is False:
            continue
        path = local_lora_weights_path(entry.lora_id, settings, entry=entry)
        if path is None:
            continue
        planned_paths.add(path)
        key = str(entry.lora_id or path)
        if key in seen_keys:
            continue
        name = (entry.display_name or "").strip() or display_name_from_path(path)
        if not _remember_name_size(name, path):
            continue
        seen_keys.add(key)
        choices.append(
            LoraProbeChoice(
                key=key,
                label=lora_choice_label(entry),
                from_downloads=False,
                weights_path=str(path),
                display_name=name,
                trigger_word=entry.trigger_word,
                scale=float(entry.scale),
                comment=entry.comment,
                repo_id=entry.repo_id or "",
                filename=entry.filename or "",
                source_path=entry.source_path,
            )
        )

    for path in _discover_safetensors_paths():
        if path in planned_paths:
            continue
        if _path_is_registered(path, settings):
            continue
        key = f"path:{path}"
        if key in seen_keys:
            continue
        name = display_name_from_path(path)
        if not _remember_name_size(name, path):
            continue
        seen_keys.add(key)
        choices.append(
            LoraProbeChoice(
                key=key,
                label=name,
                from_downloads=True,
                weights_path=str(path),
                display_name=name,
                source_path=str(path),
            )
        )

    choices.sort(key=lambda c: (c.display_name or c.label or "").lower())
    return choices


def plan_disk_lora_probes(
    settings: Optional[Dict[str, Any]],
    *,
    dedupe: bool = True,
    dedupe_changes: Optional[List[LoraCheckChange]] = None,
    options: Optional[CheckLorasOptions] = None,
) -> Tuple[List[FluxLoraEntry], List[LoraProbePlanItem], LoraCheckStats]:
    """
    On-disk catalog LoRAs and discovered .safetensors (cache + Downloads) against
    installed probeable base models (all or a selected subset).
    Returns (all_catalog_candidates, probe_plan, initial_stats).
    """
    stats = LoraCheckStats()
    opts = options or CheckLorasOptions()
    allowed_loras = _selected_lora_key_set(opts)
    digest_cache: Dict[Path, str] = {}
    discovered = _discover_safetensors_paths()
    stats.files_discovered = len(discovered)
    catalog_paths = _catalog_weight_paths(settings)
    hash_sizes = _size_conflict_set([*catalog_paths, *discovered])

    if dedupe:
        stats.downloads_scanned, stats.downloads_deduped = dedupe_downloads_loras(
            settings,
            changes=dedupe_changes,
        )
    else:
        stats.downloads_scanned = len(_downloads_safetensors_paths())

    candidates: List[FluxLoraEntry] = []
    for entry in catalog_entries_sorted(settings):
        if entry.mflux_compatible is False:
            continue
        candidates.append(entry)

    installed = installed_probeable_models()
    local_models = [m for m in opts.resolved_model_keys() if m in installed]
    not_installed = [
        m
        for m in LORA_PROBE_MODEL_ORDER
        if m in _PROBEABLE_MODEL_KEYS and not lora_probe_model_is_local(m)
    ]
    stats.skipped_model_probes = len(not_installed)

    probe_history = lora_probe_history(settings)
    catalog_md5 = _catalog_md5_index(settings, digest_cache, hash_sizes=hash_sizes)
    plan: List[LoraProbePlanItem] = []
    planned_paths: Set[Path] = set()
    planned_md5: Set[str] = set()
    planned_catalog_ids: Set[str] = set()

    if local_models:
        for entry in candidates:
            path = local_lora_weights_path(entry.lora_id, settings)
            if (
                allowed_loras is not None
                and not (_catalog_entry_selection_keys(entry, path) & allowed_loras)
            ):
                continue
            if path is None:
                stats.skipped_not_on_disk += 1
                continue
            fingerprint = _fingerprint_for_path(
                path, digest_cache, hash_sizes=hash_sizes
            )
            if fingerprint is None:
                stats.skipped_not_on_disk += 1
                continue
            if fingerprint.md5 in planned_md5:
                stats.files_deduped += 1
                continue
            probe_models = _probe_models_for_entry(
                entry, local_models, check_cross_families=opts.check_cross_families,
            )
            if not probe_models:
                continue
            planned_md5.add(fingerprint.md5)
            planned_paths.add(path)
            planned_catalog_ids.add(entry.lora_id)
            history_key = _probe_history_key(entry.lora_id, fingerprint)
            hist = probe_history.get(history_key)
            probed_models, cached, all_reused = _plan_item_from_history(
                fingerprint=fingerprint,
                history_key=history_key,
                hist=hist,
                local_models=probe_models,
                skip_unchanged=opts.skip_unchanged,
            )
            if all_reused:
                stats.skipped_unchanged += 1
            plan.append(
                LoraProbePlanItem(
                    entry=entry,
                    models=probe_models,
                    weights_path=path,
                    from_downloads=False,
                    fingerprint=fingerprint,
                    history_key=history_key,
                    probed_models_from_history=probed_models,
                    cached_support=cached,
                )
            )

        from imagegen_plugins.lora_user_entries import display_name_from_path

        orphan_paths = _downloads_probe_candidates(
            settings,
            planned_paths=planned_paths,
            planned_md5=planned_md5,
            digest_cache=digest_cache,
            catalog_md5=catalog_md5,
            stats=stats,
            hash_sizes=hash_sizes,
            allowed_lora_keys=allowed_loras,
        )
        for path in orphan_paths:
            fingerprint = _fingerprint_for_path(
                path, digest_cache, hash_sizes=hash_sizes
            )
            if fingerprint is None:
                continue
            catalog_id = catalog_md5.get(fingerprint.md5)
            if catalog_id and catalog_id not in planned_catalog_ids:
                entry = get_lora_entry(catalog_id, settings)
                if entry is not None:
                    probe_models = _probe_models_for_entry(
                        entry,
                        local_models,
                        check_cross_families=opts.check_cross_families,
                    )
                    if not probe_models:
                        continue
                    planned_catalog_ids.add(catalog_id)
                    planned_paths.add(path)
                    planned_md5.add(fingerprint.md5)
                    history_key = _probe_history_key(catalog_id, fingerprint)
                    hist = probe_history.get(history_key)
                    probed_models, cached, all_reused = _plan_item_from_history(
                        fingerprint=fingerprint,
                        history_key=history_key,
                        hist=hist,
                        local_models=probe_models,
                        skip_unchanged=opts.skip_unchanged,
                    )
                    if all_reused:
                        stats.skipped_unchanged += 1
                    plan.append(
                        LoraProbePlanItem(
                            entry=entry,
                            models=probe_models,
                            weights_path=path,
                            from_downloads=False,
                            fingerprint=fingerprint,
                            history_key=history_key,
                            probed_models_from_history=probed_models,
                            cached_support=cached,
                        )
                    )
                    continue

            planned_paths.add(path)
            planned_md5.add(fingerprint.md5)
            pending_entry = FluxLoraEntry(
                host_id=HOST_FLUX1_T2I,
                lora_id=_PENDING_DOWNLOAD_LORA_ID,
                display_name=display_name_from_path(path),
                local_path=str(path),
                source_path=str(path),
            )
            probe_models = _probe_models_for_entry(
                pending_entry,
                local_models,
                check_cross_families=opts.check_cross_families,
            )
            history_key = _probe_history_key(_PENDING_DOWNLOAD_LORA_ID, fingerprint)
            hist = probe_history.get(history_key)
            probed_models, cached, all_reused = _plan_item_from_history(
                fingerprint=fingerprint,
                history_key=history_key,
                hist=hist,
                local_models=probe_models,
                skip_unchanged=opts.skip_unchanged,
            )
            if all_reused:
                stats.skipped_unchanged += 1
            plan.append(
                LoraProbePlanItem(
                    entry=pending_entry,
                    models=probe_models,
                    weights_path=path,
                    from_downloads=True,
                    fingerprint=fingerprint,
                    history_key=history_key,
                    probed_models_from_history=probed_models,
                    cached_support=cached,
                )
            )

    plan = _filter_plan_by_lora_scope(plan, opts)
    plan = [item for item in plan if item.models]

    stats.loras_total = len(plan)
    stats.models_total = len(local_models)
    previous_support = lora_model_support(settings)
    stats.probes_total = _count_probes_in_plan(
        plan,
        previous_support,
        opts.registration_mode,
    )
    stats.progress_pairs_total = sum(len(item.models) for item in plan)
    if opts.skip_unchanged:
        for item in plan:
            for model_key in item.models:
                if model_key not in item.probed_models_from_history:
                    continue
                if _probe_should_run(
                    item.entry.lora_id,
                    model_key,
                    previous_support,
                    opts.registration_mode,
                ):
                    stats.skipped_unchanged_probes += 1
    return candidates, plan, stats


def is_lora_incompatibility_error(exc: BaseException) -> bool:
    """True when failure is likely LoRA/model mismatch (not OOM, etc.)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "not compatible with mflux",
        "wrong key layout",
        "xflabs-style",
        "could not find target path",
        "lora_unet_",
        "lora likely incompatible",
        "diffusion_model.",
        "double_blocks.",
    )
    if any(n in msg for n in needles):
        return True
    if "broadcast_shapes" in msg and ("3072" in msg or "4096" in msg):
        return True
    if "lora" in msg and (
        "matmul" in msg
        or "shape" in msg
        or "incompatible" in msg
        or "unexpected" in msg
        or "broadcast" in msg
    ):
        return True
    return False


def _retain_probe_temps(*paths: Optional[str]) -> None:
    from imagegen_plugins.lora_probe_effect import retain_lora_probe_temp

    for path in paths:
        retain_lora_probe_temp(path)


def _prepare_mflux_output_path(path: Optional[str]) -> None:
    """MFLUX refuses to overwrite; mkstemp leaves an empty placeholder file."""
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def _write_probe_image_exif(
    path: Optional[str],
    *,
    model_key: str,
    prompt: str,
    steps: int,
    seed: int = 42,
    lora: Optional[str] = None,
    quantization: Optional[int] = None,
    guidance: Optional[float] = None,
) -> None:
    """Write app-standard Image Model / Prompt / LoRA EXIF on a Check LoRAs probe PNG."""
    if not path or not os.path.isfile(path) or os.path.getsize(path) < 64:
        return
    try:
        from imagegen_plugins.image_gen_naming import (
            format_image_exif_prompt,
            menu_label_for_hf_model_id,
            write_exif_user_comment,
        )

        model_name = menu_label_for_hf_model_id(model_key) or lora_model_display_name(
            model_key
        )
        comment = format_image_exif_prompt(
            model_name,
            prompt,
            seed=seed,
            steps=steps,
            quantization=quantization,
            lora=lora,
            guidance=guidance,
        )
        if not write_exif_user_comment(path, comment):
            print(f"[Check LoRAs] Probe EXIF write returned False for {path}")
    except Exception as exc:
        print(f"[Check LoRAs] Could not write probe EXIF for {path}: {exc}")


def _probe_activity_pair(model_key: str, lora_label: str) -> str:
    model = lora_model_display_name(model_key)
    lora = (lora_label or "").strip() or "—"
    return f"{model}/{lora}"


def _ensure_probe_baseline(
    cache: LoraProbeBaselineCache,
    *,
    model_key: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    cancel_check: Callable[[], bool],
    render_baseline: Callable[[str], None],
    activity_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[Optional[str], bool]:
    """
    Return (baseline_path, generated_new).

    Renders a no-LoRA image once per (model, prompt, size, steps) and caches it
    for the rest of the Check LoRAs run.
    """
    existing = cache.lookup(
        model_key=model_key,
        prompt=prompt,
        width=width,
        height=height,
        steps=steps,
    )
    if existing is not None:
        return existing, False
    if cancel_check():
        return None, False
    baseline_path = _probe_temp_path(model_key, "", role="baseline")
    _prepare_mflux_output_path(baseline_path)
    model_name = lora_model_display_name(model_key)
    if activity_callback is not None:
        activity_callback(f"Creating base image for {model_name}…")
    print(
        f"[Check LoRAs] Baseline render {model_name} "
        f"(prompt={prompt!r}, no LoRA)"
    )
    render_baseline(baseline_path)
    cache.store(
        model_key=model_key,
        prompt=prompt,
        width=width,
        height=height,
        steps=steps,
        path=baseline_path,
    )
    print(f"[Check LoRAs] Baseline cached -> {baseline_path}")
    return baseline_path, True


def _lora_probe_has_effect(
    *,
    baseline_path: str,
    out_path: str,
    label: str,
    model_key: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    generated_baseline: bool,
) -> bool:
    """True when with-LoRA render differs from baseline (LoRA had an effect)."""
    from imagegen_plugins.lora_probe_effect import (
        _probe_cnn_identical_min_cosine,
        measure_probe_image_delta,
        probe_images_effectively_identical,
    )

    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 64:
        return False
    delta = measure_probe_image_delta(baseline_path, out_path)
    cnn_threshold = _probe_cnn_identical_min_cosine()
    if probe_images_effectively_identical(delta):
        print(
            f"[Check LoRAs] Probe: no effect for {label!r} on "
            f"{lora_model_display_name(model_key)} "
            f"(prompt={prompt!r} size={width}x{height} steps={steps} "
            f"baseline_reused={not generated_baseline} "
            f"mean={delta.mean_diff:.3f} max={delta.max_diff} "
            f"phash={delta.phash_distance} "
            f"cnn_cosine={delta.cnn_cosine} "
            f"cnn_threshold={cnn_threshold})"
        )
        return False
    return True


def _run_baseline_vs_lora_probe(
    *,
    model_key: str,
    lora_label: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    cancel_check: Callable[[], bool],
    baseline_cache: Optional[LoraProbeBaselineCache],
    generate: Callable[[str, bool], None],
    seed: int = 42,
    quantization: Optional[int] = None,
    guidance: Optional[float] = None,
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Shared Check LoRAs / import probe process for every T2I model:

    1. Same prompt for baseline and with-LoRA (caller supplies trigger-aware text)
    2. One cached no-LoRA baseline per (model, prompt, size, steps)
    3. With-LoRA render
    4. CNN/pixel compare — identical ⇒ fail (no effect)

    Probe PNGs get the same EXIF UserComment layout as normal generations
    (Image Model / Seed / Steps / LoRA / Prompt) for later manual verification.
    """
    render_prompt = (prompt or "test").strip() or "test"
    cache = baseline_cache if baseline_cache is not None else LoraProbeBaselineCache()
    out_path = _probe_temp_path(model_key, lora_label)
    exif_lora = (lora_label or "").strip() or None
    pair = _probe_activity_pair(model_key, lora_label)

    def _report(message: str) -> None:
        if activity_callback is not None:
            activity_callback(message)

    def _gen_baseline(path: str) -> None:
        generate(path, False)

    def _gen_with_lora(path: str) -> None:
        generate(path, True)

    try:
        baseline_path, generated_baseline = _ensure_probe_baseline(
            cache,
            model_key=model_key,
            prompt=render_prompt,
            width=width,
            height=height,
            steps=steps,
            cancel_check=cancel_check,
            render_baseline=_gen_baseline,
            activity_callback=activity_callback,
        )
        if baseline_path is None or cancel_check():
            return False
        _report(f"Creating test image for {pair}")
        _gen_with_lora(out_path)
        if cancel_check():
            return False
        _report(f"Creating similarity data for {pair}")
        has_effect = _lora_probe_has_effect(
            baseline_path=baseline_path,
            out_path=out_path,
            label=lora_label,
            model_key=model_key,
            prompt=render_prompt,
            width=width,
            height=height,
            steps=steps,
            generated_baseline=generated_baseline,
        )
        # After compare so EXIF rewrite cannot affect pixel/CNN probe results.
        if generated_baseline:
            _write_probe_image_exif(
                baseline_path,
                model_key=model_key,
                prompt=render_prompt,
                steps=steps,
                seed=seed,
                lora=None,
                quantization=quantization,
                guidance=guidance,
            )
        _write_probe_image_exif(
            out_path,
            model_key=model_key,
            prompt=render_prompt,
            steps=steps,
            seed=seed,
            lora=exif_lora,
            quantization=quantization,
            guidance=guidance,
        )
        return has_effect
    finally:
        _retain_probe_temps(out_path)


def _compact_probe_label(text: str) -> str:
    """Strip spaces, punctuation, and separators for readable probe filenames."""
    compact = re.sub(r"[^a-zA-Z0-9]+", "", (text or "").strip())
    return compact or "lora"


def _probe_lora_display_label(
    entry: Optional[FluxLoraEntry],
    lora_path: str,
) -> str:
    """Human label for probe PNG names (display name preferred over lora_id)."""
    if entry is not None and (entry.display_name or "").strip():
        return str(entry.display_name).strip()
    if entry is not None and entry.lora_id and entry.lora_id != _PENDING_DOWNLOAD_LORA_ID:
        return lora_choice_label(entry)
    return Path(lora_path).stem or "lora"


def _probe_file_stem(model_key: str, lora_label: str) -> str:
    """e.g. Z-Image Turbo 4-bit + Retro anime -> ZImageTurbo4bit-Retroanime."""
    model_part = _compact_probe_label(lora_model_display_name(model_key))
    raw_lora = (lora_label or "").strip()
    if raw_lora:
        lora_part = _compact_probe_label(raw_lora)
        stem = f"{model_part}-{lora_part}"
    else:
        stem = model_part
    return stem[:120] or "lora"


def _probe_temp_path(
    model_key: str,
    lora_label: str,
    *,
    role: str = "",
    suffix: str = ".png",
) -> str:
    """Named probe image under profile tmp (e.g. ZImageTurbo4bit-Retroanime.png)."""
    stem = _probe_file_stem(model_key, lora_label)
    if role:
        filename = f"{stem}-{_compact_probe_label(role)}{suffix}"
    else:
        filename = f"{stem}{suffix}"
    max_name = 200
    if len(filename) > max_name:
        filename = filename[: max_name - len(suffix)] + suffix
    return os.path.join(ensure_temporary_files_directory(), filename)


def _probe_t2i(
    *,
    model_key: str,
    hf_model: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test",
    lora_label: str = "lora",
    baseline_cache: Optional[LoraProbeBaselineCache] = None,
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    from imagegen_plugins.pipelines.mflux_schnell import (
        align_mflux_dims,
        run_mflux_flux_schnell_generate,
    )

    if cancel_check():
        return False
    w, h = align_mflux_dims(
        LORA_PROBE_SIZE, LORA_PROBE_SIZE, max_side=LORA_PROBE_SIZE
    )
    steps = lora_probe_default_steps(model_key)

    def _generate(output_path: str, with_lora: bool) -> None:
        _prepare_mflux_output_path(output_path)
        run_mflux_flux_schnell_generate(
            prompt=(prompt or "test").strip() or "test",
            width=w,
            height=h,
            steps=steps,
            guidance=0.0,
            seed=42,
            model=hf_model,
            quantize=3,
            mflux_output_path=output_path,
            low_ram=True,
            lora_paths=[lora_path] if with_lora else None,
            lora_scales=[lora_scale] if with_lora else None,
        )

    try:
        return _run_baseline_vs_lora_probe(
            model_key=model_key,
            lora_label=lora_label,
            prompt=prompt,
            width=w,
            height=h,
            steps=steps,
            cancel_check=cancel_check,
            baseline_cache=baseline_cache,
            generate=_generate,
            seed=42,
            quantization=3,
            guidance=0.0,
            activity_callback=activity_callback,
        )
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise


def _resolved_probe_lora_weights(
    entry: Optional[FluxLoraEntry],
    lora_path: str,
) -> tuple[str, float]:
    """Absolute on-disk LoRA path + scale for probe generation."""
    scale = float(entry.scale) if entry is not None else 1.0
    if (
        entry is not None
        and entry.lora_id
        and entry.lora_id != _PENDING_DOWNLOAD_LORA_ID
    ):
        try:
            from imagegen_plugins.mflux_lora_presets import resolve_lora_path

            resolved = os.path.abspath(resolve_lora_path(entry.lora_id))
            if os.path.isfile(resolved):
                return resolved, scale
        except Exception as exc:
            print(
                f"[Check LoRAs] resolve_lora_path failed for "
                f"{entry.lora_id!r}: {exc}"
            )
    resolved = os.path.abspath(os.path.expanduser(str(lora_path)))
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"LoRA weights not found: {lora_path!r}")
    return resolved, scale


def _probe_z_image_turbo(
    *,
    hf_model: str,
    model_key: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test",
    entry: Optional[FluxLoraEntry] = None,
    baseline_cache: Optional[LoraProbeBaselineCache] = None,
    lora_label: str = "lora",
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Z-Image Turbo T2I: shared no-LoRA baseline vs with-LoRA."""
    from imagegen_plugins.lora_host_registry import HOST_Z_IMAGE_TURBO
    from imagegen_plugins.mflux_z_image_session import (
        compute_z_image_model_key,
        release_z_image_session,
    )
    from imagegen_plugins.pipelines.mflux_z_image_turbo import run_mflux_z_image_generate
    from imagegen_plugins.pipelines.z_image_turbo import align_z_image_dims

    if cancel_check():
        return False

    cross_host = entry is not None and entry.host_id != HOST_Z_IMAGE_TURBO
    probe_steps = lora_probe_default_steps(model_key)
    probe_low_ram = not cross_host
    w, h = align_z_image_dims(LORA_PROBE_SIZE, LORA_PROBE_SIZE, max_side=LORA_PROBE_SIZE)
    render_prompt = (prompt or "test").strip() or "test"

    def _generate(output_path: str, with_lora: bool) -> None:
        lora_paths = [lora_path] if with_lora else None
        lora_scales = [float(lora_scale)] if with_lora else None
        if with_lora:
            key = compute_z_image_model_key(str(hf_model), lora_paths, lora_scales)
            print(
                f"[Check LoRAs] Z-Image with LoRA «{lora_label}» "
                f"path={lora_path!r} scale={float(lora_scale)} "
                f"session_key={key!r}"
            )
        _prepare_mflux_output_path(output_path)
        run_mflux_z_image_generate(
            prompt=render_prompt,
            width=w,
            height=h,
            steps=probe_steps,
            seed=42,
            model=hf_model,
            mflux_output_path=output_path,
            low_ram=probe_low_ram,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            isolate_session=True,
            require_lora_layers=bool(cross_host and with_lora),
        )

    try:
        return _run_baseline_vs_lora_probe(
            model_key=model_key,
            lora_label=lora_label,
            prompt=render_prompt,
            width=w,
            height=h,
            steps=probe_steps,
            cancel_check=cancel_check,
            baseline_cache=baseline_cache,
            generate=_generate,
            seed=42,
            quantization=4,
            activity_callback=activity_callback,
        )
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise
    finally:
        release_z_image_session(reason="lora_probe_zimage_done")


def _probe_klein_create(
    *,
    model_key: str,
    hf_model_id: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test",
    quantize: int | None = 4,
    model_path: str | None = None,
    lora_label: str = "lora",
    baseline_cache: Optional[LoraProbeBaselineCache] = None,
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Klein txt2img: shared no-LoRA baseline vs with-LoRA (prompt only)."""
    from imagegen_plugins.mflux_flux2_klein_session import generate_flux2_klein_create
    from imagegen_plugins.pipelines.mflux_flux2_klein_create import (
        align_mflux_flux2_klein_dims,
    )

    if cancel_check():
        return False
    w, h = align_mflux_flux2_klein_dims(
        LORA_PROBE_SIZE, LORA_PROBE_SIZE, max_side=LORA_PROBE_SIZE
    )
    steps = lora_probe_default_steps(model_key)
    render_prompt = (prompt or "test").strip() or "test"

    def _generate(output_path: str, with_lora: bool) -> None:
        _prepare_mflux_output_path(output_path)
        image = generate_flux2_klein_create(
            model_name=hf_model_id,
            quantize=quantize,
            model_path=model_path,
            lora_paths=[lora_path] if with_lora else None,
            lora_scales=[lora_scale] if with_lora else None,
            prompt=render_prompt,
            seed=42,
            steps=steps,
            width=w,
            height=h,
            guidance=1.0,
            low_ram=True,
            stepwise_dir=None,
        )
        image.save(path=output_path)

    try:
        return _run_baseline_vs_lora_probe(
            model_key=model_key,
            lora_label=lora_label,
            prompt=render_prompt,
            width=w,
            height=h,
            steps=steps,
            cancel_check=cancel_check,
            baseline_cache=baseline_cache,
            generate=_generate,
            seed=42,
            quantization=quantize,
            guidance=1.0,
            activity_callback=activity_callback,
        )
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise


def _probe_diffusers(
    *,
    pipeline: str,
    hf_model_id: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    vae_hf_model_id: str = "",
    keep_pipeline_loaded: bool = False,
    prompt: str = "test",
    lora_label: str = "lora",
    baseline_cache: Optional[LoraProbeBaselineCache] = None,
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """SD 1.5 / SDXL T2I: shared no-LoRA baseline vs with-LoRA."""
    if cancel_check():
        return False
    steps = lora_probe_default_steps(hf_model_id)
    w = h = LORA_PROBE_SIZE
    render_prompt = (prompt or "test").strip() or "test"

    def _generate(output_path: str, with_lora: bool) -> None:
        payload: Dict[str, Any] = {
            "prompt": render_prompt,
            "width": w,
            "height": h,
            "steps": steps,
            "guidance_scale": 7.5,
            "output_path": output_path,
            "hf_model_id": hf_model_id,
            "random_seed": False,
            "seed": 42,
            "show_progressive_images": False,
        }
        _prepare_mflux_output_path(output_path)
        if pipeline == "sd15":
            from imagegen_plugins.pipelines.sd15_diffusers import run_from_payload

            if with_lora:
                payload["sd15_lora_paths"] = [lora_path]
                payload["sd15_lora_scales"] = [lora_scale]
            if vae_hf_model_id:
                payload["vae_hf_model_id"] = vae_hf_model_id
            run_from_payload(payload)
        elif pipeline == "sdxl":
            from imagegen_plugins.pipelines.sdxl_diffusers import run_from_payload

            if with_lora:
                payload["sdxl_lora_paths"] = [lora_path]
                payload["sdxl_lora_scales"] = [lora_scale]
            run_from_payload(payload)
        else:
            raise ValueError(f"Unknown diffusers probe pipeline: {pipeline}")

    try:
        return _run_baseline_vs_lora_probe(
            model_key=hf_model_id,
            lora_label=lora_label,
            prompt=render_prompt,
            width=w,
            height=h,
            steps=steps,
            cancel_check=cancel_check,
            baseline_cache=baseline_cache,
            generate=_generate,
            seed=42,
            guidance=7.5,
            activity_callback=activity_callback,
        )
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        msg = f"{type(e).__name__}: {e}".lower()
        if "lora" in msg or "peft" in msg or "adapter" in msg:
            return False
        raise
    finally:
        if not keep_pipeline_loaded:
            try:
                if pipeline == "sd15":
                    from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline

                    unload_pipeline()
                elif pipeline == "sdxl":
                    from imagegen_plugins.pipelines.sdxl_diffusers import unload_pipeline

                    unload_pipeline()
            except Exception:
                pass


def _release_probe_model(model_key: str) -> None:
    """Unload a base model after finishing all LoRA probes for it."""
    try:
        if model_key in SD15_LORA_MODEL_KEYS:
            from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline

            unload_pipeline()
        elif model_key == SDXL_BASE_1_0:
            from imagegen_plugins.pipelines.sdxl_diffusers import unload_pipeline

            unload_pipeline(force=True)
        elif model_key in (
            FLUX2_KLEIN_4B,
            FLUX2_KLEIN_9B,
            FLUX2_KLEIN_9B_KV,
            SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        ):
            from imagegen_plugins.mflux_flux2_klein_session import release_flux2_klein_session

            release_flux2_klein_session(reason="lora_check_model_done")
        elif model_key == Z_IMAGE_TURBO_MFLUX_4BIT:
            from imagegen_plugins.mflux_z_image_session import release_z_image_session

            release_z_image_session(reason="lora_check_model_done")
    except Exception:
        pass


def probe_lora_on_model(
    model_key: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    *,
    entry: Optional[FluxLoraEntry] = None,
    keep_model_loaded: bool = False,
    probe_prompt: str = "test",
    baseline_cache: Optional[LoraProbeBaselineCache] = None,
    activity_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Return True if a 512x512 T2I probe shows a visual effect vs no-LoRA baseline.

    ``probe_prompt`` is used as-is for both the no-LoRA baseline and the
    with-LoRA render (caller supplies any shared trigger text).
    """
    from imagegen_plugins.mflux_lora_presets import assert_lora_compatible_for_model

    try:
        weights_path, lora_scale = _resolved_probe_lora_weights(entry, lora_path)
    except FileNotFoundError:
        return False

    render_prompt = (probe_prompt or "test").strip() or "test"

    try:
        assert_lora_compatible_for_model(
            weights_path,
            model_key,
            catalog_host_id=entry.host_id if entry is not None else None,
        )
    except RuntimeError:
        return False

    lora_label = _probe_lora_display_label(entry, weights_path)
    cache = baseline_cache

    if model_key == FLUX1_SCHNELL:
        return _probe_t2i(
            model_key=model_key,
            hf_model=FLUX1_SCHNELL,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == FLUX1_DEV:
        return _probe_t2i(
            model_key=model_key,
            hf_model=FLUX1_DEV,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == FLUX2_KLEIN_4B:
        return _probe_klein_create(
            model_key=model_key,
            hf_model_id=FLUX2_KLEIN_4B,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == FLUX2_KLEIN_9B:
        return _probe_klein_create(
            model_key=model_key,
            hf_model_id=FLUX2_KLEIN_9B,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == FLUX2_KLEIN_9B_KV:
        return _probe_klein_create(
            model_key=model_key,
            hf_model_id=FLUX2_KLEIN_9B_KV,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX:
        from imagegen_plugins.sceneworks_klein_mlx import (
            DEFAULT_MLX_TIER,
            resolve_tier_model_path,
        )

        tier_path = resolve_tier_model_path(
            SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
            DEFAULT_MLX_TIER,
        )
        if not tier_path:
            return False
        return _probe_klein_create(
            model_key=model_key,
            hf_model_id=SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            quantize=None,
            model_path=tier_path,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key in SD15_LORA_MODEL_KEYS:
        vae = (
            SD15_DEFAULT_VAE
            if model_key == REALISTIC_VISION_V4_NOVAE
            else ""
        )
        return _probe_diffusers(
            pipeline="sd15",
            hf_model_id=model_key,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            vae_hf_model_id=vae,
            keep_pipeline_loaded=keep_model_loaded,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == SDXL_BASE_1_0:
        return _probe_diffusers(
            pipeline="sdxl",
            hf_model_id=SDXL_BASE_1_0,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            keep_pipeline_loaded=keep_model_loaded,
            prompt=render_prompt,
            lora_label=lora_label,
            baseline_cache=cache,
            activity_callback=activity_callback,
        )
    if model_key == Z_IMAGE_TURBO_MFLUX_4BIT:
        return _probe_z_image_turbo(
            hf_model=Z_IMAGE_TURBO_MFLUX_4BIT,
            model_key=model_key,
            lora_path=weights_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=render_prompt,
            entry=entry,
            baseline_cache=cache,
            lora_label=lora_label,
            activity_callback=activity_callback,
        )
    raise ValueError(f"Unknown LoRA probe model: {model_key}")


def _init_lora_probe_states(
    plan: List[LoraProbePlanItem],
    *,
    not_installed_models: List[str],
    previous_support: Dict[str, Any],
) -> List[_LoraProbeState]:
    """
    Seed each LoRA's supported list with prior passes for models *outside*
    this run's probe set. Models in ``plan_item.models`` start unset and are
    re-added only on pass / history reuse — so a scoped re-run cannot wipe
    unrelated model support.
    """
    _ = not_installed_models
    states: List[_LoraProbeState] = []
    for plan_item in plan:
        entry = plan_item.entry
        lora_id = entry.lora_id
        lora_label = (
            entry.display_name
            if plan_item.from_downloads
            else lora_choice_label(entry)
        )
        prev_models = (
            set()
            if plan_item.from_downloads
            else set(previous_support.get(lora_id, ()))
        )
        prev_models |= set(plan_item.cached_support)
        plan_models = set(plan_item.models)
        # Preserve prior / cached passes for models not tested in this run
        # (not-installed bases, unselected models, etc.).
        supported: List[str] = [
            m for m in LORA_PROBE_MODEL_ORDER if m in prev_models and m not in plan_models
        ]
        for model_key in prev_models:
            if model_key not in plan_models and model_key not in supported:
                supported.append(model_key)
        states.append(
            _LoraProbeState(
                plan_item=plan_item,
                entry=entry,
                lora_id=lora_id,
                lora_label=lora_label,
                lora_path=str(plan_item.weights_path),
                prev_models=prev_models,
                supported=supported,
                fingerprint=plan_item.fingerprint,
                history_key=plan_item.history_key,
            )
        )
    return states


def _probe_history_record(
    *,
    history_key: str,
    fingerprint: Optional[LoraFileFingerprint],
    supported: List[str],
    models_probed: List[str],
    complete: bool,
) -> Optional[Dict[str, Any]]:
    if not history_key or fingerprint is None:
        return None
    return {
        history_key: {
            "md5": fingerprint.md5,
            "mtime": fingerprint.mtime,
            "size": fingerprint.size,
            "path": fingerprint.path,
            "model_support": list(supported),
            "models_probed": sorted(set(models_probed)),
            "complete": bool(complete),
        }
    }


def _sync_probe_history_slice(
    state: _LoraProbeState,
    result: LoraCheckResult,
    *,
    cancelled: bool,
) -> None:
    if not state.fingerprint or not state.models_completed:
        return
    complete = _lora_probe_complete(
        state,
        cancelled=cancelled,
        previous_support=result.previous_support,
        registration_mode=result.registration_mode,
    )
    hist_rec = _probe_history_record(
        history_key=state.history_key,
        fingerprint=state.fingerprint,
        supported=state.supported,
        models_probed=sorted(state.models_completed),
        complete=complete,
    )
    if hist_rec:
        result.probe_history.update(hist_rec)


def _lora_probe_complete(
    state: _LoraProbeState,
    *,
    cancelled: bool,
    previous_support: Dict[str, Any],
    registration_mode: str,
) -> bool:
    if cancelled:
        return False
    for model_key in state.plan_item.models:
        if not _probe_should_run(
            state.lora_id,
            model_key,
            previous_support,
            registration_mode,
        ):
            continue
        if model_key not in state.models_completed:
            return False
    return True


def _mark_model_completed(state: _LoraProbeState, model_key: str) -> None:
    state.models_completed.add(model_key)


def _needs_gpu_probe(
    state: _LoraProbeState,
    model_key: str,
    *,
    previous_support: Dict[str, Any],
    registration_mode: str,
    skip_unchanged: bool,
) -> bool:
    if not _probe_should_run(
        state.lora_id,
        model_key,
        previous_support,
        registration_mode,
    ):
        return False
    if skip_unchanged and model_key in state.plan_item.probed_models_from_history:
        return False
    return True


def _record_probe_result(
    *,
    state: _LoraProbeState,
    model_key: str,
    ok: bool,
    result: LoraCheckResult,
    stats: LoraCheckStats,
    by_model_enabled: Dict[str, List[str]],
    by_model_hidden: Dict[str, List[str]],
) -> None:
    model_label = lora_model_display_name(model_key)
    was_supported = model_key in state.prev_models
    lora_id = state.lora_id
    lora_label = state.lora_label
    plan_item = state.plan_item

    if ok:
        stats.last_result = "pass"
        stats.passed_probe_count += 1
        if model_key not in state.supported:
            state.supported.append(model_key)
        if not plan_item.from_downloads:
            result.changes.append(
                LoraCheckChange(
                    kind="passed",
                    lora_id=lora_id,
                    lora_label=lora_label,
                    model_key=model_key,
                    model_label=model_label,
                )
            )
            if not was_supported:
                stats.newly_supported_count += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="newly_supported",
                        lora_id=lora_id,
                        lora_label=lora_label,
                        model_key=model_key,
                        model_label=model_label,
                    )
                )
            hidden = set(by_model_hidden.get(model_key, ()))
            enabled = by_model_enabled.setdefault(model_key, [])
            if lora_id in hidden:
                stats.skipped_hidden_count += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="skipped_hidden",
                        lora_id=lora_id,
                        lora_label=lora_label,
                        model_key=model_key,
                        model_label=model_label,
                    )
                )
            elif lora_id not in enabled:
                enabled.append(lora_id)
                stats.newly_enabled_count += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="newly_enabled",
                        lora_id=lora_id,
                        lora_label=lora_label,
                        model_key=model_key,
                        model_label=model_label,
                    )
                )
    else:
        stats.last_result = "fail"
        stats.failed_probe_count += 1
        if not plan_item.from_downloads:
            result.changes.append(
                LoraCheckChange(
                    kind="failed",
                    lora_id=lora_id,
                    lora_label=lora_label,
                    model_key=model_key,
                    model_label=model_label,
                )
            )
            if was_supported:
                result.changes.append(
                    LoraCheckChange(
                        kind="lost_support",
                        lora_id=lora_id,
                        lora_label=lora_label,
                        model_key=model_key,
                        model_label=model_label,
                    )
                )


def _finalize_lora_probe_state(
    state: _LoraProbeState,
    *,
    settings: Optional[Dict[str, Any]],
    result: LoraCheckResult,
    stats: LoraCheckStats,
    model_support: Dict[str, List[str]],
    by_model_enabled: Dict[str, List[str]],
    by_model_hidden: Dict[str, List[str]],
    previous_support: Dict[str, Any],
    registration_mode: str,
    cancelled: bool = False,
) -> None:
    plan_item = state.plan_item
    # On cancel, keep prior support for models we never finished testing.
    if cancelled:
        for model_key in plan_item.models:
            if model_key in state.models_completed:
                continue
            if model_key in state.prev_models and model_key not in state.supported:
                state.supported.append(model_key)
    supported = state.supported
    lora_label = state.lora_label
    registered_lora_id = state.lora_id

    if plan_item.from_downloads:
        if not state.probed:
            return
        if supported:
            from imagegen_plugins.image_gen_persistence import register_user_lora
            from imagegen_plugins.lora_user_entries import build_user_lora_entry

            primary = _primary_model_key(supported)
            try:
                new_entry = build_user_lora_entry(
                    source_path=plan_item.weights_path,
                    display_name=state.entry.display_name,
                    model_key=primary,
                    settings=settings,
                )
                register_user_lora(
                    new_entry,
                    model_key=primary,
                    supported_models=supported,
                )
                registered_lora_id = new_entry.lora_id
                stats.downloads_registered += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="downloads_registered",
                        lora_id=registered_lora_id,
                        lora_label=new_entry.display_name,
                        model_key=primary,
                        model_label=lora_model_display_name(primary),
                    )
                )
                for model_key in supported:
                    hidden = set(by_model_hidden.get(model_key, ()))
                    enabled = by_model_enabled.setdefault(model_key, [])
                    if registered_lora_id in hidden:
                        continue
                    if registered_lora_id not in enabled:
                        enabled.append(registered_lora_id)
                        stats.newly_enabled_count += 1
                stats.newly_supported_count += len(supported)
            except Exception as exc:
                print(
                    f"[Check LoRAs] could not register download {lora_label!r}: {exc}"
                )
                stats.downloads_failed += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="downloads_failed",
                        lora_id="",
                        lora_label=lora_label,
                    )
                )
                registered_lora_id = ""
        elif not cancelled:
            stats.downloads_failed += 1
            result.changes.append(
                LoraCheckChange(
                    kind="downloads_failed",
                    lora_id="",
                    lora_label=lora_label,
                )
            )
            registered_lora_id = ""

    if registered_lora_id and registered_lora_id != _PENDING_DOWNLOAD_LORA_ID:
        model_support[registered_lora_id] = supported
        from imagegen_plugins.lora_catalog import get_lora_entry
        from imagegen_plugins.lora_model_registry import cross_family_models_for_entry

        entry_for_cross = get_lora_entry(registered_lora_id, settings) or state.entry
        result.cross_family_models[registered_lora_id] = list(
            cross_family_models_for_entry(entry_for_cross, supported)
        )
        if supported:
            stats.supported_loras += 1
        elif not plan_item.from_downloads:
            stats.removed_loras += 1

    if state.fingerprint and state.models_completed:
        hist_key = registered_lora_id
        if not hist_key or hist_key == _PENDING_DOWNLOAD_LORA_ID:
            hist_key = state.history_key
        complete = _lora_probe_complete(
            state,
            cancelled=cancelled,
            previous_support=result.previous_support,
            registration_mode=result.registration_mode,
        )
        hist_rec = _probe_history_record(
            history_key=hist_key,
            fingerprint=state.fingerprint,
            supported=supported,
            models_probed=sorted(state.models_completed),
            complete=complete,
        )
        if hist_rec:
            result.probe_history.update(hist_rec)
            if hist_key != state.history_key and state.history_key.startswith("md5:"):
                result.probe_history.pop(state.history_key, None)


def _apply_reused_probe_result(
    *,
    state: _LoraProbeState,
    model_key: str,
    result: LoraCheckResult,
    stats: LoraCheckStats,
    by_model_enabled: Dict[str, List[str]],
    by_model_hidden: Dict[str, List[str]],
) -> None:
    ok = model_key in state.plan_item.cached_support
    if ok:
        _record_probe_result(
            state=state,
            model_key=model_key,
            ok=True,
            result=result,
            stats=stats,
            by_model_enabled=by_model_enabled,
            by_model_hidden=by_model_hidden,
        )
    else:
        stats.last_result = "skip"


def _reuse_model_from_history(
    *,
    state: _LoraProbeState,
    model_key: str,
    result: LoraCheckResult,
    stats: LoraCheckStats,
    by_model_enabled: Dict[str, List[str]],
    by_model_hidden: Dict[str, List[str]],
    cancelled: bool,
) -> None:
    _apply_reused_probe_result(
        state=state,
        model_key=model_key,
        result=result,
        stats=stats,
        by_model_enabled=by_model_enabled,
        by_model_hidden=by_model_hidden,
    )
    if state.plan_item.cached_support or model_key in state.plan_item.probed_models_from_history:
        state.probed = True
    _mark_model_completed(state, model_key)
    _sync_probe_history_slice(state, result, cancelled=cancelled)


def run_lora_compatibility_check(
    settings: Optional[Dict[str, Any]],
    *,
    progress_callback: Callable[
        [int, int, str, str, str, LoraCheckStats],
        None,
    ],
    cancel_check: Callable[[], bool],
    options: Optional[CheckLorasOptions] = None,
    prepared: Optional[PreparedLoraProbePlan] = None,
) -> LoraCheckResult:
    """
    Probe on-disk catalog LoRAs and discovered .safetensors (cache + Downloads)
    against installed probeable base models. Registers passing orphan files.
    Does not download missing weights. Enables passers (unless hidden).
    progress_callback(probe_index, probe_total, phase, lora_id, model_key, stats)
    phase is 'scan' | 'downloads' | 'probe'.
    """
    run_started = time.monotonic()
    result = LoraCheckResult()
    opts = options or CheckLorasOptions()
    previous_support = lora_model_support(settings)
    result.previous_support = previous_support
    result.registration_mode = opts.registration_mode
    model_support: Dict[str, List[str]] = {}
    # Accumulated enables per model (start from current settings; merge new).
    by_model_enabled: Dict[str, List[str]] = {}
    by_model_hidden: Dict[str, List[str]] = {}

    if prepared is not None:
        _candidates = prepared.candidates
        plan = prepared.plan
        stats = prepared.stats
        result.stats = stats
        stats.probe_prompt = (opts.probe_prompt or "test").strip() or "test"
        progress_callback(
            0,
            max(1, lora_check_work_total(stats)),
            "scan",
            "",
            "",
            stats,
        )
    else:
        progress_callback(0, 1, "scan", "", "", LoraCheckStats())
        _candidates, plan, stats = plan_disk_lora_probes(
            settings,
            dedupe_changes=result.changes,
            options=opts,
        )
        result.stats = stats
        stats.probe_prompt = (opts.probe_prompt or "test").strip() or "test"

    for plan_item in plan:
        for model_key in plan_item.models:
            if model_key not in by_model_enabled:
                st = model_state(settings, model_key)
                by_model_enabled[model_key] = list(st.get("enabled_ids") or [])
                by_model_hidden[model_key] = list(
                    st.get("deleted_ids") or st.get("hidden_ids") or []
                )

    for lid, skipped_entry in (
        (e.lora_id, e)
        for e in _candidates
        if local_lora_weights_path(e.lora_id, settings) is None
        and e.mflux_compatible is not False
    ):
        result.changes.append(
            LoraCheckChange(
                kind="skipped_not_on_disk",
                lora_id=lid,
                lora_label=lora_choice_label(skipped_entry),
            )
        )

    if stats.downloads_deduped:
        progress_callback(0, max(1, lora_check_work_total(stats)), "downloads", "", "", stats)

    progress_callback(0, max(1, lora_check_work_total(stats)), "scan", "", "", stats)
    if not plan:
        result.model_support = model_support
        result.stats = stats
        result.elapsed_seconds = time.monotonic() - run_started
        return result

    not_installed_models = [
        m
        for m in LORA_PROBE_MODEL_ORDER
        if m in _PROBEABLE_MODEL_KEYS and not lora_probe_model_is_local(m)
    ]

    # Preserve selection order; only models that appear on at least one plan item.
    selected_models = opts.resolved_model_keys()
    models_in_plan: Set[str] = set()
    for plan_item in plan:
        models_in_plan.update(plan_item.models)
    local_models = [m for m in selected_models if m in models_in_plan]
    if not local_models:
        local_models = [m for m in LORA_PROBE_MODEL_ORDER if m in models_in_plan]
    lora_states = _init_lora_probe_states(
        plan,
        not_installed_models=not_installed_models,
        previous_support=previous_support,
    )
    loras_per_model = len(lora_states)
    stats.loras_total = loras_per_model
    stats.models_for_lora = len(local_models)

    from imagegen_plugins.lora_trigger_resolve import check_loras_shared_probe_prompt

    shared_probe_prompt, shared_triggers = check_loras_shared_probe_prompt(
        opts.probe_prompt,
        [(state.entry, state.lora_path) for state in lora_states],
        allow_online=False,
    )
    stats.probe_prompt = shared_probe_prompt
    print(
        f"[Check LoRAs] Shared probe prompt "
        f"({len(shared_triggers)} known trigger"
        f"{'' if len(shared_triggers) == 1 else 's'}): "
        f"{shared_probe_prompt!r}"
    )

    probe_idx = 0
    baseline_cache = LoraProbeBaselineCache()
    for model_i, model_key in enumerate(local_models, start=1):
        if cancel_check():
            result.cancelled = True
            break

        stats.model_index_for_lora = model_i
        stats.last_result = ""

        gpu_lora_indices = [
            idx
            for idx, probe_state in enumerate(lora_states)
            if model_key in probe_state.plan_item.models
            and _needs_gpu_probe(
                probe_state,
                model_key,
                previous_support=previous_support,
                registration_mode=opts.registration_mode,
                skip_unchanged=opts.skip_unchanged,
            )
        ]
        if gpu_lora_indices:
            baseline_cache.reset_for_model(model_key)
        elif opts.skip_unchanged and any(
            model_key in probe_state.plan_item.probed_models_from_history
            for probe_state in lora_states
        ):
            print(
                f"[Check LoRAs] Reusing history for "
                f"{lora_model_display_name(model_key)} — no GPU load"
            )

        for lora_i, state in enumerate(lora_states, start=1):
            if cancel_check():
                result.cancelled = True
                break

            if model_key not in state.plan_item.models:
                continue

            lora_idx = lora_i - 1
            stats.lora_index = lora_i
            stats.probe_current = probe_idx + 1
            stats.last_result = ""
            stats.current_lora_label = state.lora_label
            stats.probe_activity = ""
            work_total = lora_check_work_total(stats)
            pair = _probe_activity_pair(model_key, state.lora_label)

            def report_activity(message: str) -> None:
                stats.probe_activity = message
                progress_callback(
                    probe_idx,
                    work_total,
                    "probe",
                    state.lora_id,
                    model_key,
                    stats,
                )

            if not _probe_should_run(
                state.lora_id,
                model_key,
                previous_support,
                opts.registration_mode,
            ):
                stats.skipped_registered_probes += 1
                stats.last_result = "skip"
                stats.probe_activity = f"Skipping registered pair {pair}"
                if (
                    opts.registration_mode == REGISTRATION_SKIP_REGISTERED
                    and model_key in state.prev_models
                    and model_key not in state.supported
                ):
                    state.supported.append(model_key)
                _mark_model_completed(state, model_key)
                progress_callback(
                    probe_idx,
                    work_total,
                    "probe",
                    state.lora_id,
                    model_key,
                    stats,
                )
                probe_idx += 1
                stats.probes_done = probe_idx
                progress_callback(
                    probe_idx,
                    work_total,
                    "probe",
                    state.lora_id,
                    model_key,
                    stats,
                )
                time.sleep(0)
                continue

            if (
                opts.skip_unchanged
                and model_key in state.plan_item.probed_models_from_history
            ):
                stats.probe_activity = f"Reusing probe history for {pair}"
                progress_callback(
                    probe_idx,
                    work_total,
                    "probe",
                    state.lora_id,
                    model_key,
                    stats,
                )
                _reuse_model_from_history(
                    state=state,
                    model_key=model_key,
                    result=result,
                    stats=stats,
                    by_model_enabled=by_model_enabled,
                    by_model_hidden=by_model_hidden,
                    cancelled=result.cancelled,
                )
                probe_idx += 1
                stats.probes_done = probe_idx
                progress_callback(
                    probe_idx,
                    work_total,
                    "probe",
                    state.lora_id,
                    model_key,
                    stats,
                )
                time.sleep(0)
                continue

            next_gpu_idx = next((i for i in gpu_lora_indices if i > lora_idx), None)
            keep_model_loaded = next_gpu_idx is not None
            # Clear before pre-probe UI update so a prior pass is not attributed
            # to this LoRA when the progress signal is delivered later.
            stats.last_result = ""
            stats.probe_activity = f"Preparing probe for {pair}"
            progress_callback(
                probe_idx,
                work_total,
                "probe",
                state.lora_id,
                model_key,
                stats,
            )
            print(
                f"[Check LoRAs] Model {model_i}/{len(local_models)} "
                f"{lora_model_display_name(model_key)} · "
                f"LoRA {lora_i}/{loras_per_model} «{state.lora_label}» "
                f"(render {stats.gpu_probes_done + 1}/{stats.probes_total}, "
                f"{LORA_PROBE_SIZE}x{LORA_PROBE_SIZE}, "
                f"steps={lora_probe_default_steps(model_key)})"
            )
            try:
                ok = probe_lora_on_model(
                    model_key,
                    state.lora_path,
                    state.entry.scale,
                    cancel_check,
                    entry=state.entry,
                    keep_model_loaded=keep_model_loaded,
                    probe_prompt=shared_probe_prompt,
                    baseline_cache=baseline_cache,
                    activity_callback=report_activity,
                )
            except Exception as e:
                print(
                    f"[Check LoRAs] probe error {state.lora_label!r} on "
                    f"{model_key!r}: {e}"
                )
                ok = False

            cancelled_now = cancel_check()
            # Cancel mid-probe returns False — do not record that as a real fail.
            # A completed pass must still be recorded even if cancel was requested
            # during the tail of the probe (EXIF write, etc.).
            if cancelled_now and not ok:
                result.cancelled = True
                break

            _record_probe_result(
                state=state,
                model_key=model_key,
                ok=ok,
                result=result,
                stats=stats,
                by_model_enabled=by_model_enabled,
                by_model_hidden=by_model_hidden,
            )
            state.probed = True
            stats.gpu_probes_done += 1
            _mark_model_completed(state, model_key)
            _sync_probe_history_slice(state, result, cancelled=result.cancelled)

            probe_idx += 1
            stats.probes_done = probe_idx
            progress_callback(
                probe_idx,
                work_total,
                "probe",
                state.lora_id,
                model_key,
                stats,
            )
            if cancelled_now:
                result.cancelled = True
                break
            time.sleep(0)

        if gpu_lora_indices:
            _release_probe_model(model_key)

        if result.cancelled:
            break

    for state in lora_states:
        _finalize_lora_probe_state(
            state,
            settings=settings,
            result=result,
            stats=stats,
            model_support=model_support,
            by_model_enabled=by_model_enabled,
            by_model_hidden=by_model_hidden,
            previous_support=previous_support,
            registration_mode=opts.registration_mode,
            cancelled=result.cancelled,
        )
    stats.loras_done = len(lora_states)

    result.model_support = model_support
    result.by_model = {
        mk: {
            "enabled_ids": list(by_model_enabled.get(mk, [])),
            "deleted_ids": list(by_model_hidden.get(mk, [])),
        }
        for mk in by_model_enabled
    }
    result.stats = stats
    result.elapsed_seconds = time.monotonic() - run_started
    return result
