#!/usr/bin/env python3
"""
Whether pipeline model weights are present locally, and download confirmation.

Uses a lightweight Hugging Face cache scan on the GUI thread (no mflux import).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from utils import show_styled_ok_cancel

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

# Common MFLUX aliases -> Hugging Face repo id (avoid importing mflux in the GUI process).
_FLUX_REQUIRED_WEIGHT_SUBDIRS = ("vae", "transformer", "text_encoder", "text_encoder_2")
# FLUX.2 Klein layout (Qwen3 text encoder, no second TE).
_FLUX2_KLEIN_WEIGHT_SUBDIRS = ("vae", "transformer", "text_encoder")
_Z_IMAGE_WEIGHT_SUBDIRS = ("vae", "transformer", "text_encoder")
_SD15_WEIGHT_SUBDIRS = ("unet", "text_encoder")

_model_local_cache: dict[tuple[str, str], bool] = {}


def invalidate_model_local_cache(
    pipeline_id: str | None = None,
    hf_model_id: str | None = None,
) -> None:
    """Drop cached HF local checks (whole cache or one model)."""
    if pipeline_id is None and hf_model_id is None:
        _model_local_cache.clear()
        return
    drop = [
        key
        for key in _model_local_cache
        if (pipeline_id is None or key[0] == pipeline_id)
        and (hf_model_id is None or key[1] == hf_model_id)
    ]
    for key in drop:
        _model_local_cache.pop(key, None)


def model_display_name(pipeline_id: str, hf_model_id: str) -> str:
    """User-facing model name for download confirmation text."""
    if pipeline_id == "flux_schnell_mflux_play":
        repo = _resolve_mflux_repo_id(hf_model_id)
        tail = repo.split("/")[-1] if "/" in repo else repo
        if "FLUX.1-" in tail:
            variant = tail.split("FLUX.1-", 1)[1]
            return f"FLUX.1 {variant.replace('-', ' ').title()}"
        return tail.replace("-", " ")
    if pipeline_id == "sana_sprint_600m":
        if hf_model_id and "/" in hf_model_id:
            return hf_model_id.split("/")[-1].replace("_", " ")
        return "SANA Sprint 0.6B 1024px"
    if pipeline_id == "z_image_turbo_sdnq":
        return "Z-Image Turbo (8-bit)"
    if pipeline_id == "sd15_diffusers":
        if hf_model_id and "/" in hf_model_id:
            return hf_model_id.split("/")[-1].replace("_", " ")
        return "Stable Diffusion 1.5"
    if pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        if hf_model_id and "/" in hf_model_id:
            return hf_model_id.split("/")[-1].replace(".", " ").replace("-", " ")
        return "FLUX.1 Fill"
    if pipeline_id in (
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    ):
        text = (hf_model_id or "").strip().lower()
        if "9b-kv" in text or "klein-9b-kv" in text or "flux.2-klein-9b-kv" in text:
            return "FLUX 2 klein 9B KV"
        if "9b" in text:
            return "FLUX 2 klein 9B"
        if "4b" in text:
            return "FLUX 2 klein 4B"
        if hf_model_id and "/" in hf_model_id:
            return hf_model_id.split("/")[-1].replace(".", " ").replace("-", " ")
        return "FLUX.2 Klein 4B"
    return hf_model_id or "model"


def pipeline_model_is_local(
    pipeline_id: str, hf_model_id: str, *, use_cache: bool = True
) -> bool:
    key = (pipeline_id, hf_model_id)
    if use_cache and key in _model_local_cache:
        return _model_local_cache[key]
    if pipeline_id == "flux_schnell_mflux_play":
        result = _mflux_flux_weights_are_local(hf_model_id)
    elif pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        result = _hf_repo_snapshot_is_complete(hf_model_id)
    elif pipeline_id in (
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    ):
        result = _hf_repo_snapshot_is_complete(hf_model_id, _FLUX2_KLEIN_WEIGHT_SUBDIRS)
    elif pipeline_id == "sana_sprint_600m":
        result = _hf_repo_snapshot_has_weights(hf_model_id)
    elif pipeline_id == "z_image_turbo_sdnq":
        result = _hf_repo_snapshot_is_complete(hf_model_id, _Z_IMAGE_WEIGHT_SUBDIRS)
    elif pipeline_id == "sd15_diffusers":
        from imagegen_plugins.hf_model_ids import SD15_DEFAULT_VAE

        if not _hf_repo_snapshot_is_complete(hf_model_id, _SD15_WEIGHT_SUBDIRS):
            result = False
        elif _hf_repo_snapshot_is_complete(hf_model_id, ("vae",)):
            result = True
        else:
            result = _hf_repo_snapshot_has_weights(SD15_DEFAULT_VAE)
    else:
        result = True
    if use_cache:
        _model_local_cache[key] = result
    return result


def confirm_model_download_if_needed(
    plugin: ImageGenModelPlugin, parent
) -> bool:
    """
    Return True if generation may proceed (model already local, or user accepted download).
    """
    is_local = pipeline_model_is_local(plugin.pipeline_id, plugin.hf_model_id)
    if is_local:
        return True
    name = model_display_name(plugin.pipeline_id, plugin.hf_model_id)
    incomplete = _hf_repo_snapshot_has_weights(plugin.hf_model_id) and not is_local
    if incomplete:
        text = (
            f"{name} is only partially downloaded (large weight files are missing). "
            "Resume the full download now? This may take a while and use many gigabytes."
        )
    else:
        text = (
            f"{name} does not exist on your machine. "
            "A one-time download of several gigabytes will install the model on your machine."
        )
    answer = show_styled_ok_cancel(
        parent,
        "Download model?",
        text,
        default_cancel=True,
    )
    if answer != QMessageBox.StandardButton.Ok:
        return False
    if plugin.pipeline_id in (
        "mflux_fill_expand",
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    ):
        try:
            ensure_hf_repo_downloaded(
                plugin.hf_model_id,
                pipeline_id=plugin.pipeline_id,
                parent=parent,
            )
        except Exception as e:
            from utils import show_styled_critical

            show_styled_critical(
                parent,
                "Download failed",
                str(e)[:4000],
            )
            return False
        invalidate_model_local_cache(plugin.pipeline_id, plugin.hf_model_id)
        return pipeline_model_is_local(plugin.pipeline_id, plugin.hf_model_id)
    return True


def ensure_hf_repo_downloaded(
    repo_id: str, *, pipeline_id: str = "mflux_flux2_klein_edit", parent=None
) -> str:
    """Download or resume a full Hugging Face repo snapshot. Returns local snapshot path."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required to download model weights. "
            "Install with: pip install huggingface_hub"
        ) from e

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        path = snapshot_download(repo_id=repo_id, resume_download=True)
    finally:
        if app is not None:
            app.restoreOverrideCursor()

    invalidate_model_local_cache(pipeline_id, repo_id)
    if not pipeline_model_is_local(pipeline_id, repo_id):
        raise RuntimeError(
            f"Download finished but {repo_id} still appears incomplete. "
            "Check Hugging Face access (model license) and disk space, then try again."
        )
    return path


def _resolve_mflux_repo_id(hf_model_id: str) -> str:
    if "/" in hf_model_id and not hf_model_id.startswith(("./", "../", "~/")):
        return hf_model_id
    return hf_model_id


def _hf_repo_snapshot_is_complete(
    repo_id: str,
    subdirs: tuple[str, ...] = _FLUX_REQUIRED_WEIGHT_SUBDIRS,
) -> bool:
    """True if HF hub cache has a complete snapshot for repo_id (no mflux import)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return False

    repo_cache_dir = Path(HF_HUB_CACHE) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if not repo_cache_dir.is_dir():
        return False

    snapshots = sorted(
        (p for p in repo_cache_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for snapshot_path in snapshots:
        if _snapshot_has_component_weights(snapshot_path, subdirs):
            return True
    return False


def _snapshot_has_component_weights(
    snapshot_path: Path, subdirs: tuple[str, ...]
) -> bool:
    for subdir in subdirs:
        if not _component_has_weights(snapshot_path / subdir):
            return False
    return True


def _component_has_weights(component_path: Path) -> bool:
    """True when a FLUX component dir has real weight shards (not just index.json)."""
    if not component_path.is_dir():
        return False
    for entry in component_path.iterdir():
        name = entry.name
        if not name.endswith(".safetensors") or name.endswith(".index.json"):
            continue
        if entry.is_symlink() and not entry.exists():
            continue
        if entry.is_file() or (entry.is_symlink() and entry.exists()):
            return True
    for index_name in (
        "diffusion_pytorch_model.safetensors.index.json",
        "model.safetensors.index.json",
    ):
        index_path = component_path / index_name
        if not index_path.is_file():
            continue
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return False
        weight_map = data.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            return False
        shards = {str(v) for v in weight_map.values() if v}
        if not shards:
            return False
        for shard in shards:
            shard_path = component_path / shard
            if not shard_path.is_file():
                return False
        return True
    return False


def _mflux_flux_weights_are_local(hf_model_id: str) -> bool:
    path = _resolve_mflux_repo_id(hf_model_id)
    local_path = os.path.expanduser(path)
    if os.path.exists(local_path):
        return True
    return _hf_repo_snapshot_is_complete(path)


def _hf_repo_snapshot_has_weights(repo_id: str) -> bool:
    """True if HF hub cache has at least one weight file for repo_id."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return False

    repo_cache_dir = Path(HF_HUB_CACHE) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if not repo_cache_dir.is_dir():
        return False

    for snapshot_path in sorted(
        (p for p in repo_cache_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        for root, _dirs, files in os.walk(snapshot_path):
            for name in files:
                if name.endswith((".safetensors", ".bin", ".pt")):
                    full = os.path.join(root, name)
                    if os.path.isfile(full) and os.path.getsize(full) > 0:
                        return True
    return False
