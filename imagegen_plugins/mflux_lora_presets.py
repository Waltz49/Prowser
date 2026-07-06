#!/usr/bin/env python3
"""FLUX LoRA resolution for MFLUX (Hugging Face download on first use)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QComboBox, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QComboBox

from imagegen_plugins.lora_catalog import (
    DEFAULT_CACHE,
    LORA_CATALOG,
    FluxLoraEntry,
    catalog_cache_path,
    get_lora_entry,
    lora_choice_label,
    lora_choices_for_plugin,
    lora_choices_for_pipeline,
    lora_entry_min_steps,
    manual_download_help,
)
from imagegen_plugins.lora_entry import PAPER_CUTOUT_LORA_PATH
from imagegen_plugins.lora_host_registry import HOST_SD15

FLUX_LORA_CATALOG = LORA_CATALOG

MFLUX_LORA_UI_CHOICES: Tuple[Tuple[str, str], ...] = (("None", "none"),) + tuple(
    (lora_choice_label(e), e.lora_id)
    for e in sorted(LORA_CATALOG.values(), key=lambda x: x.display_name.lower())
)

# Migrate saved UI settings from removed presets.
_LEGACY_PRESET_IDS = {"anime": "mspaint1"}

# Shown (disabled) when the active model does not support LoRAs.
LORA_UNSUPPORTED_PRESET_ID = "__lora_unsupported__"
LORA_UNSUPPORTED_LABEL = "not supported with this model"


def lora_choice_ids() -> Tuple[str, ...]:
    return tuple(c[1] for c in MFLUX_LORA_UI_CHOICES)


def repopulate_mflux_lora_combo(
    combo: "QComboBox",
    *,
    plugin: Any = None,
    pipeline_id: str = "",
    plugin_hf_model_id: str = "",
    current_preset_id: Any = None,
) -> None:
    """Rebuild LoRA pulldown items from settings (enabled + installed for plugin host)."""
    from imagegen_plugins.image_gen_model_selector import populate_image_gen_lora_combo

    populate_image_gen_lora_combo(
        combo,
        plugin,
        pipeline_id=pipeline_id,
        plugin_hf_model_id=plugin_hf_model_id,
        current_preset_id=current_preset_id,
    )


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
    if text == LORA_UNSUPPORTED_PRESET_ID:
        return "none"
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


def _assert_mflux_compatible_lora(path: str, *, host_id: str | None = None) -> None:
    """Reject FLUX.1 LoRA key layouts known to crash MFLUX (not used for FLUX.2 Klein)."""
    if host_id == "flux2_klein":
        return
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
        _assert_mflux_compatible_lora(resolved, host_id=entry.host_id)
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
        _assert_mflux_compatible_lora(resolved, host_id=entry.host_id)
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
        if entry.host_id == HOST_SD15:
            return str(Path(entry.local_path).expanduser().resolve())
        return _resolve_local_path(entry)

    dest_path = catalog_cache_path(entry)
    if dest_path is None:
        raise ValueError(f"LoRA entry has no download path: {preset_id}")
    dest_dir = (cache_dir or DEFAULT_CACHE) / entry.repo_id.replace("/", "__")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.filename
    if dest_path.is_file() and dest_path.stat().st_size > 1024:
        resolved = str(dest_path.resolve())
        if entry.host_id != HOST_SD15:
            _assert_mflux_compatible_lora(resolved, host_id=entry.host_id)
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
    if entry.host_id != HOST_SD15:
        _assert_mflux_compatible_lora(resolved, host_id=entry.host_id)
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


def effective_steps_for_lora_stack(
    steps: int,
    stack: List[str],
    *,
    for_fill: bool = False,
) -> int:
    """Raise steps to the maximum minimum required by any LoRA in the stack."""
    result = int(steps)
    for preset_id in stack:
        result = effective_steps_for_lora(result, preset_id, for_fill=for_fill)
    return result


def lora_stack_min_steps(stack: List[str]) -> Optional[int]:
    """Highest per-LoRA min steps in stack, or None when empty."""
    mins: List[int] = []
    for preset_id in stack:
        lo = lora_preset_min_steps(preset_id)
        if lo is not None:
            mins.append(lo)
    return max(mins) if mins else None


def normalize_lora_stack_from_values(
    values: Dict[str, Any],
    *,
    pop: bool = False,
) -> List[str]:
    """
    Resolve active LoRA preset ids from dialog/job values.

    Accepts ``mflux_lora_stack`` (list) or legacy single ``mflux_lora`` string.
    """
    if pop:
        stack_raw = values.pop("mflux_lora_stack", None)
        legacy = values.pop("mflux_lora", None)
        values.pop("mflux_lora_paths", None)
        values.pop("mflux_lora_scales", None)
    else:
        stack_raw = values.get("mflux_lora_stack")
        legacy = values.get("mflux_lora")

    ids: List[str] = []
    if isinstance(stack_raw, list):
        for item in stack_raw:
            pid = _normalize_preset_id(item)
            if pid != "none" and pid not in ids:
                ids.append(pid)
    elif stack_raw is not None and stack_raw != []:
        pid = _normalize_preset_id(stack_raw)
        if pid != "none" and pid not in ids:
            ids.append(pid)

    if not ids and legacy is not None:
        pid = _normalize_preset_id(legacy)
        if pid != "none":
            ids.append(pid)
    return ids


def lora_display_names_for_stack(stack: List[str]) -> List[str]:
    names: List[str] = []
    for preset_id in stack:
        entry = get_lora_entry(preset_id)
        if entry is not None:
            names.append(entry.display_name)
        else:
            names.append(preset_id)
    return names


def lora_name_for_exif_from_values(values: Dict[str, Any]) -> Optional[str]:
    """LoRA label for EXIF from stack or legacy single preset."""
    stack = normalize_lora_stack_from_values(values, pop=False)
    if not stack:
        return None
    names = lora_display_names_for_stack(stack)
    if len(names) == 1:
        return names[0]
    return " + ".join(names)


def apply_lora_to_mflux_payload(
    merged: Dict[str, object],
    *,
    for_fill: bool = False,
    for_klein: bool = False,
) -> None:
    """Set mflux_lora_paths/scales when one or more presets are selected."""
    stack = normalize_lora_stack_from_values(merged, pop=True)
    if not stack:
        merged.pop("mflux_lora_paths", None)
        merged.pop("mflux_lora_scales", None)
        return

    from config import get_config
    from imagegen_plugins.hf_model_ids import FLUX1_DEV, FLUX1_FILL_DEV
    from imagegen_plugins.lora_catalog import (
        klein_lora_mismatch_message,
        lora_model_key_from_values,
        lora_probe_passed_for_model,
    )

    model_key = lora_model_key_from_values(dict(merged))
    if for_fill:
        model_key = model_key or FLUX1_FILL_DEV
    elif not model_key:
        model_key = FLUX1_DEV

    settings = get_config().load_settings()
    paths: List[str] = []
    scales: List[float] = []

    for preset_id in stack:
        entry = get_lora_entry(preset_id)
        if entry is None:
            raise ValueError(f"Unknown mflux LoRA preset: {preset_id}")

        if model_key and not lora_probe_passed_for_model(
            preset_id, model_key, settings
        ):
            raise ValueError(
                f"LoRA «{entry.display_name}» did not pass Check LoRAs for this base model. "
                "Run Tools → Debug → Check LoRAs, or enable a passing LoRA in Settings → LoRA."
            )

        if for_klein and entry.base_hf_model_id:
            from imagegen_plugins.lora_model_registry import entry_matches_lora_model

            active = str(merged.get("hf_model_id") or "").strip()
            if active and not entry_matches_lora_model(entry, active):
                raise ValueError(klein_lora_mismatch_message(entry, active))

        if not for_fill and not for_klein:
            required = (entry.base_hf_model_id or FLUX1_DEV).strip()
            active = str(merged.get("hf_model_id") or "").strip()
            if required and active and required != active:
                from imagegen_plugins.image_gen_model_availability import model_display_name

                req_name = model_display_name("flux_schnell_mflux_play", required)
                act_name = model_display_name("flux_schnell_mflux_play", active)
                raise ValueError(
                    f"LoRA «{entry.display_name}» requires {req_name}. "
                    f"Select {req_name} in the Create dialog, then choose this LoRA "
                    f"(active model: {act_name})."
                )

        paths.append(resolve_lora_path(preset_id))
        scales.append(entry.scale)

    merged["mflux_lora_paths"] = paths
    merged["mflux_lora_scales"] = scales
    if not for_fill and not for_klein:
        merged["steps"] = effective_steps_for_lora_stack(
            int(merged.get("steps") or 0),
            stack,
            for_fill=False,
        )


__all__ = [
    "MFLUX_LORA_UI_CHOICES",
    "PAPER_CUTOUT_LORA_PATH",
    "apply_lora_to_mflux_payload",
    "coerce_lora_preset_id",
    "effective_steps_for_lora",
    "effective_steps_for_lora_stack",
    "lora_choice_ids",
    "lora_choices_for_plugin",
    "lora_choices_for_pipeline",
    "lora_display_names_for_stack",
    "lora_name_for_exif_from_values",
    "lora_preset_min_steps",
    "lora_stack_min_steps",
    "manual_download_help",
    "normalize_lora_stack_from_values",
    "repopulate_mflux_lora_combo",
    "resolve_lora_path",
]
