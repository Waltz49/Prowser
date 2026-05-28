#!/usr/bin/env python3
"""FLUX LoRA resolution for MFLUX (Hugging Face download on first use)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QComboBox, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QComboBox

from imagegen_plugins.flux_lora_catalog import (
    DEFAULT_CACHE,
    FLUX_LORA_CATALOG,
    FluxLoraEntry,
    PAPER_CUTOUT_LORA_PATH,
    catalog_cache_path,
    get_lora_entry,
    lora_choices_for_pipeline,
    lora_entry_min_steps,
    manual_download_help,
)

MFLUX_LORA_UI_CHOICES: Tuple[Tuple[str, str], ...] = (("None", "none"),) + tuple(
    (e.display_name, e.lora_id)
    for e in sorted(FLUX_LORA_CATALOG.values(), key=lambda x: x.display_name.lower())
)

# Migrate saved UI settings from removed presets.
_LEGACY_PRESET_IDS = {"anime": "mspaint1"}


def lora_choice_ids() -> Tuple[str, ...]:
    return tuple(c[1] for c in MFLUX_LORA_UI_CHOICES)


def repopulate_mflux_lora_combo(
    combo: "QComboBox",
    *,
    pipeline_id: str,
    plugin_hf_model_id: str,
    current_preset_id: Any = None,
) -> None:
    """Rebuild LoRA pulldown items from settings (enabled + deleted catalog state)."""
    from config import get_config

    choices = lora_choices_for_pipeline(
        pipeline_id,
        plugin_hf_model_id,
        get_config().load_settings(),
    )
    preset_id = coerce_lora_preset_id(
        current_preset_id if current_preset_id is not None else combo.currentData()
    )
    choice_ids = {c[1] for c in choices}
    if preset_id not in choice_ids:
        preset_id = "none"
    combo.blockSignals(True)
    combo.clear()
    for label, pid in choices:
        combo.addItem(str(label), pid)
    idx = combo.findData(preset_id)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.blockSignals(False)


def coerce_lora_preset_id(preset_id: Any) -> str:
    """UI may pass preset id string, or a (label, id) tuple from a buggy QComboBox."""
    if isinstance(preset_id, (tuple, list)):
        if len(preset_id) >= 2:
            return str(preset_id[1])
        if len(preset_id) == 1:
            return str(preset_id[0])
        return "none"
    if preset_id is None:
        return "none"
    text = str(preset_id).strip()
    if text.startswith("(") and "," in text:
        try:
            import ast

            parsed = ast.literal_eval(text)
            if isinstance(parsed, (tuple, list)) and len(parsed) >= 2:
                return str(parsed[1])
        except (SyntaxError, ValueError):
            pass
    return text or "none"


def _normalize_preset_id(preset_id: Any) -> str:
    preset_id = coerce_lora_preset_id(preset_id)
    return _LEGACY_PRESET_IDS.get(preset_id, preset_id)


def _assert_mflux_compatible_lora(path: str) -> None:
    """Reject LoRA key layouts known to crash MFLUX at first denoise step."""
    try:
        from safetensors import safe_open
    except ImportError:
        return
    with safe_open(path, framework="pt") as f:
        for i, key in enumerate(f.keys()):
            if i >= 8:
                break
            if key.startswith("lora_unet_") or key.startswith("diffusion_model."):
                raise RuntimeError(
                    "This LoRA file is not compatible with MFLUX (BFL/ComfyUI key layout). "
                    f"Example key: {key[:72]}. "
                    "Enable a verified LoRA in Settings → LoRA."
                )
            if key.startswith("double_blocks.") and not key.startswith("transformer."):
                raise RuntimeError(
                    "This LoRA file is not compatible with MFLUX (XLabs-style keys). "
                    f"Example key: {key[:72]}. "
                    "Enable a verified LoRA in Settings → LoRA."
                )


def _resolve_local_path(entry: FluxLoraEntry) -> str:
    path = Path(entry.local_path or "").expanduser().resolve()
    if path.is_file() and path.stat().st_size > 1024:
        resolved = str(path)
        _assert_mflux_compatible_lora(resolved)
        return resolved
    alt = (
        Path.home()
        / ".cache"
        / "mflux_loras"
        / "paper-cutout"
        / "Flux_1_Dev_LoRA_Paper-Cutout-Style.safetensors"
    )
    if alt.is_file() and alt.stat().st_size > 1024:
        resolved = str(alt.resolve())
        _assert_mflux_compatible_lora(resolved)
        return resolved
    raise FileNotFoundError(f"LoRA file not found: {path}")


def resolve_lora_path(preset_id: str, *, cache_dir: Optional[Path] = None) -> str:
    """Download preset weights if needed; return absolute path to .safetensors."""
    preset_id = _normalize_preset_id(preset_id)
    if preset_id == "none":
        raise ValueError("resolve_lora_path called with preset_id 'none'")
    entry = get_lora_entry(preset_id)
    if entry is None:
        raise ValueError(f"Unknown mflux LoRA preset: {preset_id}")

    if entry.local_path:
        return _resolve_local_path(entry)

    dest_path = catalog_cache_path(entry)
    if dest_path is None:
        raise ValueError(f"LoRA entry has no download path: {preset_id}")
    dest_dir = (cache_dir or DEFAULT_CACHE) / entry.repo_id.replace("/", "__")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.filename
    if dest_path.is_file() and dest_path.stat().st_size > 1024:
        resolved = str(dest_path.resolve())
        _assert_mflux_compatible_lora(resolved)
        return resolved

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is required to download LoRA weights. "
            f"Install with: pip install huggingface_hub\n"
            f"Or download manually:\n"
            f"  https://huggingface.co/{entry.repo_id}/resolve/main/{entry.filename}\n"
            f"Save as: {dest_path}"
        ) from e

    downloaded = hf_hub_download(
        repo_id=entry.repo_id,
        filename=entry.filename,
        local_dir=str(dest_dir),
    )
    path = Path(downloaded)
    if not path.is_file():
        raise RuntimeError(f"LoRA download failed: {downloaded}")
    resolved = str(path.resolve())
    _assert_mflux_compatible_lora(resolved)
    return resolved


def lora_preset_min_steps(preset_id: Any) -> Optional[int]:
    """Minimum steps when this LoRA is active on text-to-image (None if none/unknown)."""
    preset_id = _normalize_preset_id(preset_id)
    if preset_id == "none":
        return None
    return lora_entry_min_steps(preset_id)


def effective_steps_for_lora(
    steps: int,
    preset_id: Any,
    *,
    for_fill: bool = False,
) -> int:
    """Match payload builder: LoRA on generate pipelines may require higher steps."""
    if for_fill:
        return int(steps)
    min_steps = lora_preset_min_steps(preset_id)
    if min_steps is None:
        return int(steps)
    return max(int(steps), min_steps)


def apply_lora_to_mflux_payload(
    merged: Dict[str, object],
    *,
    for_fill: bool = False,
) -> None:
    """Set mflux_lora_paths/scales and optional dev model + steps when a preset is selected."""
    preset_id = _normalize_preset_id(merged.pop("mflux_lora", "none") or "none")
    if preset_id == "none":
        merged.pop("mflux_lora_paths", None)
        merged.pop("mflux_lora_scales", None)
        return

    entry = get_lora_entry(preset_id)
    if entry is None:
        raise ValueError(f"Unknown mflux LoRA preset: {preset_id}")

    path = resolve_lora_path(preset_id)
    merged["mflux_lora_paths"] = [path]
    merged["mflux_lora_scales"] = [entry.scale]
    if not for_fill:
        merged["hf_model_id"] = entry.mflux_model
        merged["steps"] = effective_steps_for_lora(
            int(merged.get("steps") or entry.min_steps),
            preset_id,
            for_fill=False,
        )


__all__ = [
    "MFLUX_LORA_UI_CHOICES",
    "PAPER_CUTOUT_LORA_PATH",
    "apply_lora_to_mflux_payload",
    "coerce_lora_preset_id",
    "effective_steps_for_lora",
    "lora_choice_ids",
    "lora_choices_for_pipeline",
    "lora_preset_min_steps",
    "manual_download_help",
    "repopulate_mflux_lora_combo",
    "resolve_lora_path",
]
