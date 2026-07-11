#!/usr/bin/env python3
"""SceneWorks FLUX.2 Klein 9B KV MLX tier helpers (pre-quantized weights)."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Final, Iterable, Tuple

from imagegen_plugins.hf_model_ids import SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX

_MFLUX_ALLOWED_QUANT: Final[frozenset[int]] = frozenset({3, 4, 5, 6, 8})
_FLUX2_KLEIN_WEIGHT_SUBDIRS: Final[tuple[str, ...]] = ("vae", "transformer", "text_encoder")

MLX_TIER_CHOICES: Tuple[tuple[str, str], ...] = (
    ("Q4 (~22 GB, recommended)", "q4"),
    ("Q8 (~26 GB)", "q8"),
    ("BF16 (~35 GB)", "bf16"),
)
DEFAULT_MLX_TIER: Final[str] = "q4"
_VALID_MLX_TIERS: Final[frozenset[str]] = frozenset(t for _label, t in MLX_TIER_CHOICES)

TIER_SIZE_ESTIMATE_BYTES: dict[str, int] = {
    "q4": 22_000_000_000,
    "q8": 26_000_000_000,
    "bf16": 35_000_000_000,
}


def is_sceneworks_klein_mlx_repo(repo_id: str) -> bool:
    return (repo_id or "").strip() == SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX


def normalize_mlx_tier(value: Any) -> str:
    tier = str(value or DEFAULT_MLX_TIER).strip().lower()
    if tier not in _VALID_MLX_TIERS:
        return DEFAULT_MLX_TIER
    return tier


def mlx_tier_status_quant_label(tier: Any) -> str | None:
    """Job/EXIF Q: label digits for a pre-quantized MLX tier (q4 -> 4, bf16 -> 16)."""
    normalized = normalize_mlx_tier(tier)
    if normalized == "bf16":
        return "16"
    if normalized.startswith("q") and normalized[1:].isdigit():
        return normalized[1:]
    return normalized or None


def tier_allow_patterns(tier: str) -> list[str]:
    tier = normalize_mlx_tier(tier)
    return [f"{tier}/**"]


def _hf_snapshot_dirs(repo_id: str) -> list[Path]:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return []

    repo_cache_dir = (
        Path(HF_HUB_CACHE) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    )
    if not repo_cache_dir.is_dir():
        return []
    return sorted(
        (p for p in repo_cache_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _component_has_weights(component_path: Path) -> bool:
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


def tier_snapshot_root(repo_id: str, tier: str) -> Path | None:
    """Return HF cache snapshot root containing a complete tier tree, if any."""
    tier = normalize_mlx_tier(tier)
    for snapshot_path in _hf_snapshot_dirs(repo_id):
        tier_root = snapshot_path / tier
        if all(
            _component_has_weights(tier_root / subdir)
            for subdir in _FLUX2_KLEIN_WEIGHT_SUBDIRS
        ):
            return tier_root
    return None


def tier_is_local(repo_id: str, tier: str) -> bool:
    return tier_snapshot_root(repo_id, tier) is not None


def sceneworks_model_is_local(repo_id: str, *, tier: str = DEFAULT_MLX_TIER) -> bool:
    if not is_sceneworks_klein_mlx_repo(repo_id):
        return False
    return tier_is_local(repo_id, tier)


def resolve_tier_model_path(repo_id: str, tier: str) -> str | None:
    root = tier_snapshot_root(repo_id, tier)
    if root is None:
        return None
    return str(root)


def ensure_sceneworks_tier_downloaded(
    repo_id: str,
    tier: str,
    *,
    parent=None,
) -> str:
    """Download one SceneWorks MLX tier; returns local tier directory path."""
    if not is_sceneworks_klein_mlx_repo(repo_id):
        raise ValueError(f"Not a SceneWorks Klein MLX repo: {repo_id!r}")

    tier = normalize_mlx_tier(tier)
    existing = resolve_tier_model_path(repo_id, tier)
    if existing:
        return existing

    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required to download model weights. "
            "Install with: pip install huggingface_hub"
        ) from e

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        snapshot_path = snapshot_download(
            repo_id=repo_id,
            allow_patterns=tier_allow_patterns(tier),
            resume_download=True,
        )
    finally:
        if app is not None:
            app.restoreOverrideCursor()

    tier_path = resolve_tier_model_path(repo_id, tier)
    if tier_path:
        return tier_path

    fallback = Path(snapshot_path) / tier
    if fallback.is_dir():
        return str(fallback)

    raise RuntimeError(
        f"Download finished but {repo_id} tier {tier} still appears incomplete. "
        "Check disk space and try again from Tools > Manage models."
    )


def klein_load_params_from_payload(
    payload: dict[str, Any],
) -> tuple[str, int | None, str | None]:
    """Return (model_name, quantize, model_path) for Klein create/edit workers."""
    model = str(payload.get("hf_model_id") or "").strip()
    if not model:
        raise ValueError("hf_model_id is required")

    if is_sceneworks_klein_mlx_repo(model):
        tier = normalize_mlx_tier(payload.get("mlx_tier"))
        model_path = resolve_tier_model_path(model, tier)
        if not model_path:
            raise RuntimeError(
                f"{model} ({tier.upper()} tier) is not installed. "
                "Download it from Tools > Manage models, then try again."
            )
        return model, None, model_path

    quantize = int(payload.get("mflux_quantize", 4))
    if quantize not in _MFLUX_ALLOWED_QUANT:
        raise ValueError(
            f"mflux_quantize must be one of {sorted(_MFLUX_ALLOWED_QUANT)}"
        )
    return model, quantize, None


def sceneworks_download_script_lines(
    repo_id: str,
    *,
    tier: str = DEFAULT_MLX_TIER,
) -> Iterable[str]:
    """Extra hf download args for SceneWorks tier snapshots."""
    del repo_id
    tier = normalize_mlx_tier(tier)
    include_args = " ".join(shlex.quote(p) for p in tier_allow_patterns(tier))
    return (
        f'# SceneWorks MLX tier "{tier}" only (not the full multi-tier repo).',
        f'"$HF" download "$REPO_ID" --include {include_args}',
    )
