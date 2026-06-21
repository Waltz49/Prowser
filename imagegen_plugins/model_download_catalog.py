#!/usr/bin/env python3
"""Static image-gen model download catalog (from registered plugins)."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
    ANYTHING_FURRY,
    REALISTIC_VISION_V4_NOVAE,
    SD15_DEFAULT_VAE,
    Z_IMAGE_TURBO_SDNQ_INT8,
    lora_model_display_name,
)
from imagegen_plugins.image_gen_model_availability import pipeline_model_is_local

_FUNCTION_LABELS: Dict[str, str] = {
    "create": "Create",
    "edit": "Edit",
    "expand": "Expand",
    "infill": "Infill",
}

# Download-size estimates (bytes) measured on the Prowser dev machine via scan_cache_dir.
MODEL_DOWNLOAD_SIZE_ESTIMATE_BYTES: Dict[str, int] = {
    FLUX1_SCHNELL: 33_751_852_192,
    FLUX1_DEV: 33_752_765_526,
    FLUX1_FILL_DEV: 33_831_976_058,
    FLUX2_KLEIN_4B: 23_748_001_493,
    FLUX2_KLEIN_9B: 52_887_747_363,
    FLUX2_KLEIN_9B_KV: 52_886_250_544,
    "Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers": 7_703_533_162,
    Z_IMAGE_TURBO_SDNQ_INT8: 6_200_000_000,
    ANYTHING_FURRY: 4_100_000_000,
    REALISTIC_VISION_V4_NOVAE: 4_265_000_000,
    SD15_DEFAULT_VAE: 334_000_000,
}

_GATED_REPO_PREFIXES: Tuple[str, ...] = ("black-forest-labs/",)


@dataclass(frozen=True)
class ModelDownloadCatalogEntry:
    repo_id: str
    display_name: str
    description_lines: Tuple[str, ...]
    pipeline_id: str
    gated: bool
    size_estimate_bytes: int


def _format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "unknown size"
    gb = num_bytes / 1_000_000_000
    if gb >= 10:
        return f"~{gb:.0f} GB"
    return f"~{gb:.1f} GB"


def format_download_size_estimate(repo_id: str) -> str:
    return _format_bytes(MODEL_DOWNLOAD_SIZE_ESTIMATE_BYTES.get(repo_id, 0))


def model_is_gated(repo_id: str) -> bool:
    return any(repo_id.startswith(prefix) for prefix in _GATED_REPO_PREFIXES)


def model_is_installed(entry: ModelDownloadCatalogEntry) -> bool:
    return pipeline_model_is_local(entry.pipeline_id, entry.repo_id)


def delete_model_from_hf_cache(repo_id: str) -> bool:
    """Remove all cached revisions for repo_id. Returns True if anything was deleted."""
    try:
        from huggingface_hub import scan_cache_dir
    except ImportError:
        return False

    info = scan_cache_dir()
    revisions: list[str] = []
    for repo in info.repos:
        if repo.repo_id != repo_id:
            continue
        revisions.extend(rev.commit_hash for rev in repo.revisions)
    if not revisions:
        return False
    info.delete_revisions(*revisions).execute()
    return True


def _used_by_line_html(func_labels: list[str]) -> str:
    bold_labels = ", ".join(f"<b>{html.escape(label)}</b>" for label in func_labels)
    return f"Used by: {bold_labels}"


def _description_lines(functions: Iterable[str], model_comment: str) -> Tuple[str, ...]:
    func_labels = [_FUNCTION_LABELS.get(fn, fn.title()) for fn in sorted(set(functions))]
    lines: list[str] = []
    if func_labels:
        lines.append(_used_by_line_html(func_labels))
    comment = (model_comment or "").strip()
    if comment:
        lines.append(comment)
    return tuple(lines[:2])


def build_model_download_catalog() -> Tuple[ModelDownloadCatalogEntry, ...]:
    """Unique HF repos from registered plugins (static install catalog)."""
    from imagegen_plugins import discover_plugins

    grouped: Dict[str, dict] = {}
    for plugin in discover_plugins():
        repo_id = (plugin.hf_model_id or "").strip()
        if not repo_id or "/" not in repo_id:
            continue
        bucket = grouped.setdefault(
            repo_id,
            {
                "functions": set(),
                "pipeline_id": plugin.pipeline_id,
                "comments": [],
                "display_names": [],
            },
        )
        bucket["functions"].add(plugin.function)
        if plugin.model_comment.strip():
            bucket["comments"].append(plugin.model_comment.strip())
        if plugin.display_name.strip():
            bucket["display_names"].append(plugin.display_name.strip())

    entries: list[ModelDownloadCatalogEntry] = []
    for repo_id in sorted(grouped):
        meta = grouped[repo_id]
        comment = meta["comments"][0] if meta["comments"] else ""
        display_name = lora_model_display_name(repo_id)
        for name in meta["display_names"]:
            if name != repo_id:
                display_name = name
                break
        entries.append(
            ModelDownloadCatalogEntry(
                repo_id=repo_id,
                display_name=display_name,
                description_lines=_description_lines(meta["functions"], comment),
                pipeline_id=meta["pipeline_id"],
                gated=model_is_gated(repo_id),
                size_estimate_bytes=MODEL_DOWNLOAD_SIZE_ESTIMATE_BYTES.get(repo_id, 0),
            )
        )
    return tuple(entries)
