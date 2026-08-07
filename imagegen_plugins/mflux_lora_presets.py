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
    lora_weights_file_is_valid,
)
from imagegen_plugins.lora_host_registry import HOST_FLUX1_T2I, HOST_SD15, HOST_SDXL, HOST_Z_IMAGE_TURBO, lora_host_for_pipeline

FLUX_LORA_CATALOG = LORA_CATALOG

_DIFFUSERS_LORA_HOSTS = frozenset({HOST_SD15, HOST_SDXL})

MFLUX_LORA_UI_CHOICES: Tuple[Tuple[str, str], ...] = (("None", "none"),) + tuple(
    (lora_choice_label(e), e.lora_id)
    for e in sorted(LORA_CATALOG.values(), key=lambda x: x.display_name.lower())
)

# Shown (disabled) when the active model does not support LoRAs.
LORA_UNSUPPORTED_PRESET_ID = "__lora_unsupported__"
LORA_UNSUPPORTED_LABEL = "not supported with this model"




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
    return coerce_lora_preset_id(preset_id)


def _scan_mflux_lora_keys(path: str) -> None:
    """Reject FLUX/MFLUX LoRA key layouts known to crash MFLUX loaders."""
    try:
        from safetensors import safe_open
    except ImportError:
        return
    with safe_open(path, framework="pt") as f:
        for key in f.keys():
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


def _assert_mflux_compatible_lora(path: str, *, host_id: str | None = None) -> None:
    """Reject FLUX.1 LoRA key layouts known to crash MFLUX (not used for FLUX.2 Klein or Z-Image)."""
    if host_id in _DIFFUSERS_LORA_HOSTS or host_id in ("flux2_klein", HOST_Z_IMAGE_TURBO):
        return
    _scan_mflux_lora_keys(path)


def assert_lora_compatible_for_model(
    path: str,
    model_key: str,
    *,
    catalog_host_id: str | None = None,
) -> None:
    """Key-layout validation for the base model that will load this LoRA."""
    from imagegen_plugins.hf_model_ids import (
        FLUX1_DEV,
        FLUX1_FILL_DEV,
        FLUX1_SCHNELL,
        FLUX2_KLEIN_4B,
        FLUX2_KLEIN_9B,
        FLUX2_KLEIN_9B_KV,
        SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        SD15_LORA_MODEL_KEYS,
        SDXL_BASE_1_0,
        Z_IMAGE_TURBO_MFLUX_4BIT,
    )

    if model_key in SD15_LORA_MODEL_KEYS or model_key == SDXL_BASE_1_0:
        return
    if model_key in (
        FLUX2_KLEIN_4B,
        FLUX2_KLEIN_9B,
        FLUX2_KLEIN_9B_KV,
        SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    ):
        return
    if model_key == Z_IMAGE_TURBO_MFLUX_4BIT and catalog_host_id == HOST_Z_IMAGE_TURBO:
        return
    if model_key in (FLUX1_SCHNELL, FLUX1_DEV, FLUX1_FILL_DEV):
        _scan_mflux_lora_keys(path)


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
        if entry.host_id in _DIFFUSERS_LORA_HOSTS:
            resolved = str(Path(entry.local_path).expanduser().resolve())
            if not lora_weights_file_is_valid(Path(resolved)):
                raise RuntimeError(
                    f"LoRA download looks incomplete or corrupt: {resolved}. "
                    "Delete it and try again, or download manually from Hugging Face."
                )
            return resolved
        return _resolve_local_path(entry)

    dest_path = catalog_cache_path(entry)
    if dest_path is None:
        raise ValueError(f"LoRA entry has no download path: {preset_id}")
    dest_dir = (cache_dir or DEFAULT_CACHE) / entry.repo_id.replace("/", "__")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / entry.filename
    if dest_path.is_file() and dest_path.stat().st_size > 1024:
        if lora_weights_file_is_valid(dest_path):
            resolved = str(dest_path.resolve())
            if entry.host_id in _DIFFUSERS_LORA_HOSTS:
                if not lora_weights_file_is_valid(dest_path):
                    raise RuntimeError(
                        f"LoRA download looks incomplete or corrupt: {dest_path}. "
                        "Delete it and try again, or download manually from Hugging Face."
                    )
            elif entry.host_id not in _DIFFUSERS_LORA_HOSTS:
                _assert_mflux_compatible_lora(resolved, host_id=entry.host_id)
            return resolved
        try:
            dest_path.unlink()
        except OSError:
            pass

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
    if entry.host_id in _DIFFUSERS_LORA_HOSTS:
        if not lora_weights_file_is_valid(path):
            raise RuntimeError(
                f"LoRA download looks incomplete or corrupt: {path}. "
                "Delete it and try again, or download manually from Hugging Face."
            )
    elif entry.host_id not in _DIFFUSERS_LORA_HOSTS:
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


def _uses_sd15_single_lora(
    values: Dict[str, Any],
    *,
    pipeline_id: Optional[str] = None,
) -> bool:
    pid = (pipeline_id or values.get("pipeline_id") or "").strip()
    if pid:
        return lora_host_for_pipeline(pid) == HOST_SD15
    from imagegen_plugins.hf_model_ids import SD15_LORA_MODEL_KEYS

    hf = str(values.get("hf_model_id") or "").strip()
    return hf in SD15_LORA_MODEL_KEYS


MFLUX_LORA_PAYLOAD_KEYS: Tuple[str, ...] = ("mflux_lora_paths", "mflux_lora_scales")
SD15_LORA_PAYLOAD_KEYS: Tuple[str, ...] = ("sd15_lora_paths", "sd15_lora_scales")
SDXL_LORA_PAYLOAD_KEYS: Tuple[str, ...] = ("sdxl_lora_paths", "sdxl_lora_scales")
_DIFFUSERS_LORA_PAYLOAD_KEYS: Tuple[str, ...] = (
    SD15_LORA_PAYLOAD_KEYS + SDXL_LORA_PAYLOAD_KEYS
)


def strip_lora_payload_keys_for_host(
    values: Dict[str, Any],
    *,
    host_id: str,
    pop: bool = True,
) -> None:
    """Drop resolved LoRA paths that belong to a different pipeline family."""
    if host_id == HOST_SD15:
        keep = set(SD15_LORA_PAYLOAD_KEYS)
    elif host_id == HOST_SDXL:
        keep = set(SDXL_LORA_PAYLOAD_KEYS)
    else:
        keep = set(MFLUX_LORA_PAYLOAD_KEYS)
    all_keys = MFLUX_LORA_PAYLOAD_KEYS + _DIFFUSERS_LORA_PAYLOAD_KEYS
    for key in all_keys:
        if key in keep:
            continue
        if pop:
            values.pop(key, None)
        elif key in values:
            del values[key]


def _strip_sd15_lora_stack_keys(values: Dict[str, Any], *, pop: bool) -> None:
    if pop:
        values.pop("mflux_lora_stack", None)
        values.pop("mflux_lora_paths", None)
        values.pop("mflux_lora_scales", None)


def effective_lora_ids_from_values(
    values: Dict[str, Any],
    *,
    pipeline_id: Optional[str] = None,
    pop: bool = False,
) -> List[str]:
    """
    Active LoRA preset ids for generation, EXIF, and trigger-word guards.

    SD 1.5 uses the single ``mflux_lora`` field only; SDXL and MFLUX hosts use
    ``mflux_lora_stack``.
    """
    pid = (pipeline_id or values.get("pipeline_id") or "").strip()
    if _uses_sd15_single_lora(values, pipeline_id=pid or None):
        _strip_sd15_lora_stack_keys(values, pop=pop)
        if pop:
            legacy = values.pop("mflux_lora", None)
        else:
            legacy = values.get("mflux_lora")
        preset_id = _normalize_preset_id(legacy or "none")
        return [] if preset_id == "none" else [preset_id]
    return normalize_lora_stack_from_values(values, pop=pop)


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
        explicit_stack = stack_raw is not None
    else:
        stack_raw = values.get("mflux_lora_stack")
        legacy = values.get("mflux_lora")
        explicit_stack = "mflux_lora_stack" in values

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

    if explicit_stack:
        return ids

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


def _lora_scale_for_exif(values: Dict[str, Any], preset_id: str, index: int) -> float:
    """Prefer snapshotted scale lists, then per-id overrides, then catalog."""
    for key in ("mflux_lora_scales", "sdxl_lora_scales", "sd15_lora_scales"):
        scales_list = values.get(key)
        if isinstance(scales_list, list) and index < len(scales_list):
            try:
                return float(scales_list[index])
            except (TypeError, ValueError):
                break
    from imagegen_plugins.job_values_snapshot import _lora_scale_for_preset

    return float(_lora_scale_for_preset(values, preset_id))


def _display_name_for_lora_path(path: str) -> str:
    """Best-effort catalog display name for an on-disk LoRA path."""
    from pathlib import Path as _Path

    from imagegen_plugins.lora_catalog import (
        catalog_entries_sorted,
        local_lora_weights_path,
    )

    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        resolved = str(_Path(raw).expanduser().resolve())
    except OSError:
        resolved = raw
    filename = _Path(raw).name
    stem = _Path(raw).stem
    for entry in catalog_entries_sorted():
        weights = local_lora_weights_path(entry.lora_id, entry=entry)
        if weights is not None:
            try:
                entry_path = str(weights.resolve())
            except OSError:
                entry_path = str(weights)
            if entry_path in (resolved, raw) or weights.name == filename:
                return entry.display_name
        if entry.filename and entry.filename == filename:
            return entry.display_name
        if entry.local_path:
            try:
                local = str(_Path(entry.local_path).expanduser().resolve())
            except OSError:
                local = str(entry.local_path)
            if local in (resolved, raw) or _Path(local).name == filename:
                return entry.display_name
    return stem or filename


def lora_name_for_exif_from_paths_and_scales(
    paths: Any,
    scales: Any = None,
) -> Optional[str]:
    """Format ``name [weight]`` labels from mflux path/scale lists."""
    from imagegen_plugins.image_gen_naming import format_exif_lora_weight

    if not isinstance(paths, list) or not paths:
        return None
    scale_list = scales if isinstance(scales, list) else []
    labels: List[str] = []
    for i, path in enumerate(paths):
        name = _display_name_for_lora_path(str(path))
        if not name:
            continue
        try:
            scale = float(scale_list[i]) if i < len(scale_list) else 1.0
        except (TypeError, ValueError):
            scale = 1.0
        labels.append(f"{name} [{format_exif_lora_weight(scale)}]")
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return " + ".join(labels)


def lora_name_for_exif_from_values(
    values: Dict[str, Any],
    *,
    pipeline_id: Optional[str] = None,
) -> Optional[str]:
    """LoRA label for EXIF from stack or legacy single preset (``name [weight]``)."""
    from imagegen_plugins.image_gen_naming import format_exif_lora_weight

    stack = effective_lora_ids_from_values(
        values, pipeline_id=pipeline_id, pop=False
    )
    if stack:
        names = lora_display_names_for_stack(stack)
        labels: List[str] = []
        for i, (preset_id, name) in enumerate(zip(stack, names)):
            scale = _lora_scale_for_exif(values, preset_id, i)
            labels.append(f"{name} [{format_exif_lora_weight(scale)}]")
        if len(labels) == 1:
            return labels[0]
        return " + ".join(labels)

    for paths_key, scales_key in (
        ("mflux_lora_paths", "mflux_lora_scales"),
        ("sdxl_lora_paths", "sdxl_lora_scales"),
        ("sd15_lora_paths", "sd15_lora_scales"),
    ):
        label = lora_name_for_exif_from_paths_and_scales(
            values.get(paths_key), values.get(scales_key)
        )
        if label:
            return label
    return None


def apply_lora_to_mflux_payload(
    merged: Dict[str, object],
    *,
    for_fill: bool = False,
    for_klein: bool = False,
    for_z_image: bool = False,
) -> None:
    """Set mflux_lora_paths/scales when one or more presets are selected."""
    from imagegen_plugins.job_values_snapshot import job_values_snapshotted

    lora_host = HOST_Z_IMAGE_TURBO if for_z_image else HOST_FLUX1_T2I
    pipeline_id = str(merged.get("pipeline_id") or "").strip() or None
    if job_values_snapshotted(dict(merged)):
        snap_paths = merged.get("mflux_lora_paths")
        snap_scales = merged.get("mflux_lora_scales")
        if isinstance(snap_paths, list) and isinstance(snap_scales, list):
            saved_paths = list(snap_paths)
            saved_scales = list(snap_scales)
            stack = effective_lora_ids_from_values(
                merged,
                pipeline_id=pipeline_id,
                pop=True,
            )
            if not stack:
                merged.pop("mflux_lora_paths", None)
                merged.pop("mflux_lora_scales", None)
                strip_lora_payload_keys_for_host(merged, host_id=lora_host, pop=True)
                return
            if len(saved_paths) == len(saved_scales) == len(stack):
                strip_lora_payload_keys_for_host(merged, host_id=lora_host, pop=True)
                merged["mflux_lora_paths"] = saved_paths
                merged["mflux_lora_scales"] = saved_scales
                if not for_fill and not for_klein and not for_z_image:
                    merged["steps"] = effective_steps_for_lora_stack(
                        int(merged.get("steps") or 0),
                        stack,
                        for_fill=False,
                    )
                return

    stack = effective_lora_ids_from_values(
        merged,
        pipeline_id=pipeline_id,
        pop=True,
    )
    if not stack:
        merged.pop("mflux_lora_paths", None)
        merged.pop("mflux_lora_scales", None)
        strip_lora_payload_keys_for_host(merged, host_id=lora_host, pop=True)
        return

    from config import get_config
    from imagegen_plugins.hf_model_ids import FLUX1_DEV, FLUX1_FILL_DEV, Z_IMAGE_TURBO_MFLUX_4BIT
    from imagegen_plugins.lora_catalog import (
        klein_lora_mismatch_message,
        lora_model_key_from_values,
        lora_probe_passed_for_model,
    )

    model_key = lora_model_key_from_values(dict(merged))
    if for_z_image:
        model_key = model_key or Z_IMAGE_TURBO_MFLUX_4BIT
    elif for_fill:
        model_key = model_key or FLUX1_FILL_DEV
    elif not model_key:
        model_key = FLUX1_DEV

    settings = get_config().load_settings()
    paths: List[str] = []
    scales: List[float] = []

    strip_lora_payload_keys_for_host(merged, host_id=lora_host, pop=True)

    for preset_id in stack:
        entry = get_lora_entry(preset_id)
        if entry is None:
            raise ValueError(f"Unknown mflux LoRA preset: {preset_id}")
        if entry.host_id in _DIFFUSERS_LORA_HOSTS:
            raise ValueError(
                f"LoRA «{entry.display_name}» is for diffusers SD models only. "
                "Select an SD 1.5 or SDXL model in Create, or pick a compatible LoRA."
            )
        if for_z_image and entry.host_id != HOST_Z_IMAGE_TURBO:
            if not lora_probe_passed_for_model(preset_id, model_key, settings):
                raise ValueError(
                    f"LoRA «{entry.display_name}» is not for Z-Image Turbo. "
                    "Run Check LoRAs on Z-Image Turbo first, or pick a Z-Image LoRA."
                )
        if not for_z_image and entry.host_id == HOST_Z_IMAGE_TURBO:
            raise ValueError(
                f"LoRA «{entry.display_name}» is for Z-Image Turbo only. "
                "Select Z-Image Turbo (4-bit) in Create, or pick a FLUX/Klein LoRA."
            )

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

        if not for_fill and not for_klein and not for_z_image:
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
    if not for_fill and not for_klein and not for_z_image:
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
    "effective_lora_ids_from_values",
    "effective_steps_for_lora_stack",
    "lora_choices_for_plugin",
    "lora_choices_for_pipeline",
    "lora_display_names_for_stack",
    "lora_name_for_exif_from_paths_and_scales",
    "lora_name_for_exif_from_values",
    "lora_preset_min_steps",
    "lora_stack_min_steps",
    "normalize_lora_stack_from_values",
    "resolve_lora_path",
    "strip_lora_payload_keys_for_host",
    "MFLUX_LORA_PAYLOAD_KEYS",
    "SD15_LORA_PAYLOAD_KEYS",
]
