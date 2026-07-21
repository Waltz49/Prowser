#!/usr/bin/env python3
"""Image-gen settings in ~/.prowser/data/settings.json (per dialog/function)."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import get_config

# Serialize imagegen settings writes (model params, LoRA catalog, active plugin, …).
_imagegen_settings_lock = threading.Lock()


def _ensure_imagegen_dict(settings: dict) -> dict:
    """Ensure settings['imagegen'] is a dict without dropping existing keys (e.g. lora_catalog)."""
    imagegen = settings.get("imagegen")
    if not isinstance(imagegen, dict):
        imagegen = {}
        settings["imagegen"] = imagegen
    return imagegen


def _mutate_imagegen_settings(mutator: Callable[[dict], None]) -> None:
    """Load settings, mutate imagegen under lock, save (avoids lost LoRA catalog updates)."""
    import copy
    import shutil

    config = get_config()
    with _imagegen_settings_lock:
        settings = config.load_settings()
        imagegen = _ensure_imagegen_dict(settings)
        mutator(imagegen)
        settings_path = config.settings_file
        if settings_path.exists():
            try:
                backup = settings_path.with_suffix(".json.pre_imagegen_write")
                shutil.copy2(settings_path, backup)
            except OSError:
                pass
        config.save_settings(copy.deepcopy(settings))


def _normalize_plugin_id(plugin_id: str) -> str:
    if plugin_id == "flux_fill_infil":
        return "flux_fill_infill"
    return plugin_id


_DIALOGS_KEY = "dialogs"
_LEGACY_MODELS_KEY = "models"
_LORA_STACKS_KEY = "lora_stacks"

# Not shared across models in a function dialog (come from plugin model_defaults).
_PLUGIN_SPECIFIC_DIALOG_KEYS = frozenset(
    {
        "hf_model_id",
        "source_image_path",
        "source_image_paths",
    }
)

# Shared across all models in a function dialog (e.g. create).
_SHARED_FUNCTION_KEYS = frozenset({"prompt"})

# Global image-gen prefs (not per function, model, or dialog field values).
_GLOBAL_DIALOG_PREF_KEYS = frozenset(
    {
        "pass_image_to_ai_with_prompt",
        "flux_prompt_job_with_generate",
        "flux_prompt_ai_job",
        "show_progressive_images",
    }
)
_PASS_IMAGE_TO_AI_KEY = "pass_image_to_ai_with_prompt"
_SHOW_PROGRESSIVE_IMAGES_KEY = "show_progressive_images"
_FLUX_PROMPT_JOB_WITH_GENERATE_KEY = "flux_prompt_job_with_generate"
_FLUX_PROMPT_SYSTEM_PROMPT_TEXT_KEY = "flux_prompt_system_prompt_text"
_FLUX_PROMPT_SYSTEM_PROMPT_VISIBLE_KEY = "flux_prompt_system_prompt_visible"
_FLUX_PROMPT_SYSTEM_PROMPT_SPLITTER_SIZES_KEY = (
    "flux_prompt_system_prompt_splitter_sizes"
)
_FLUX_PROMPT_SYSTEM_PROMPT_EDITOR_EXPANDED_KEY = (
    "flux_prompt_system_prompt_editor_expanded"
)


def _sanitize_dialog_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v
        for k, v in dict(values).items()
        if k not in _PLUGIN_SPECIFIC_DIALOG_KEYS
        and k not in _GLOBAL_DIALOG_PREF_KEYS
    }


def _shared_function_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: values[k] for k in _SHARED_FUNCTION_KEYS if k in values}


def _per_plugin_dialog_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if k not in _SHARED_FUNCTION_KEYS}


def _split_lora_stack_from_values(
    values: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Pop ``mflux_lora_stack`` before sanitize; it is stored under ``lora_stacks``."""
    raw = dict(values)
    stack = _coerce_lora_stack_list(raw.pop("mflux_lora_stack", None))
    return _sanitize_dialog_values(raw), stack


def _coerce_lora_stack_list(raw: Any) -> List[str]:
    from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        pid = coerce_lora_preset_id(item)
        if pid != "none" and pid not in out:
            out.append(pid)
    return out


def _plugin_uses_lora_stack(plugin_id: str) -> bool:
    """FLUX/mflux/Klein use multi-LoRA stacks; SD15 keeps single ``mflux_lora``."""
    from imagegen_plugins.lora_host_registry import HOST_SD15

    plugin_id = _normalize_plugin_id(plugin_id)
    try:
        from imagegen_plugins import discover_plugins

        for plugin in discover_plugins():
            if plugin.plugin_id == plugin_id:
                host = getattr(plugin, "lora_host_id", None)
                return host is not None and host != HOST_SD15
    except Exception:
        pass
    return True


def load_lora_stack_for_plugin(function: str, plugin_id: str) -> List[str]:
    """Per-function, per-plugin LoRA stack (preset ids). Migrates legacy ``mflux_lora``."""
    from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

    plugin_id = _normalize_plugin_id(plugin_id)
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    dialogs = imagegen.get(_DIALOGS_KEY) or {}
    fn_entry = dialogs.get(function) or {}
    stacks = fn_entry.get(_LORA_STACKS_KEY) or {}
    if isinstance(stacks, dict):
        raw = stacks.get(plugin_id)
        stack = _coerce_lora_stack_list(raw)
        if stack:
            return stack

    per_plugin = load_model_settings(plugin_id)
    if _plugin_uses_lora_stack(plugin_id):
        legacy = per_plugin.get("mflux_lora")
        pid = coerce_lora_preset_id(legacy)
        if pid != "none":
            return [pid]
        return []

    legacy = per_plugin.get("mflux_lora")
    pid = coerce_lora_preset_id(legacy)
    if pid != "none":
        return [pid]
    raw_stack = per_plugin.get("mflux_lora_stack")
    return _coerce_lora_stack_list(raw_stack)



def _merge_prompt_from_shared(
    shared: Dict[str, Any], per_plugin: Dict[str, Any]
) -> Optional[str]:
    shared_p = (shared.get("prompt") or "").strip()
    if shared_p:
        return shared["prompt"]
    per = (per_plugin.get("prompt") or "").strip()
    if per:
        return per_plugin["prompt"]
    return None


def _legacy_settings_for_function(function: str) -> Dict[str, Any]:
    """Merge legacy per-plugin settings into one function-level dict (shared prompt)."""
    from imagegen_plugins import plugins_for_function

    merged: Dict[str, Any] = {}
    for plugin in plugins_for_function(function):
        legacy = _sanitize_dialog_values(load_model_settings(plugin.plugin_id))
        if not legacy:
            continue
        prompt = (legacy.get("prompt") or "").strip()
        if prompt:
            merged["prompt"] = legacy["prompt"]
        for key, value in legacy.items():
            if key == "prompt":
                continue
            merged.setdefault(key, value)
    return merged


def _merge_shared_prompt_from_legacy(
    saved: Dict[str, Any],
    function: str,
    *,
    fallback_plugin_id: Optional[str],
) -> Dict[str, Any]:
    if (saved.get("prompt") or "").strip():
        return saved
    legacy = _legacy_settings_for_function(function)
    prompt = (legacy.get("prompt") or "").strip()
    if not prompt and fallback_plugin_id:
        single = _sanitize_dialog_values(load_model_settings(fallback_plugin_id))
        prompt = (single.get("prompt") or "").strip()
    if prompt:
        return {**saved, "prompt": prompt}
    return saved


def load_dialog_settings(
    function: str,
    *,
    fallback_plugin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Saved field values for a function dialog (create, edit, expand, …)."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    dialogs = imagegen.get(_DIALOGS_KEY) or {}
    saved = dict(dialogs.get(function) or {})
    if not saved:
        saved = _legacy_settings_for_function(function)
        if not saved and fallback_plugin_id:
            saved = _sanitize_dialog_values(load_model_settings(fallback_plugin_id))
    else:
        saved = _merge_shared_prompt_from_legacy(
            saved, function, fallback_plugin_id=fallback_plugin_id
        )
    return _sanitize_dialog_values(saved)


def load_plugin_dialog_settings(function: str, plugin_id: str) -> Dict[str, Any]:
    """Per-plugin field values merged with function-level shared keys (prompt)."""
    plugin_id = _normalize_plugin_id(plugin_id)
    shared = load_dialog_settings(function, fallback_plugin_id=plugin_id)
    per_plugin = _sanitize_dialog_values(load_model_settings(plugin_id))

    if per_plugin:
        out = dict(per_plugin)
    elif shared:
        out = dict(shared)
    else:
        out = {}

    prompt = _merge_prompt_from_shared(shared, per_plugin)
    if prompt is not None:
        out["prompt"] = prompt

    stack = load_lora_stack_for_plugin(function, plugin_id)
    if _plugin_uses_lora_stack(plugin_id):
        out["mflux_lora_stack"] = stack
        out.pop("mflux_lora", None)
    else:
        from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

        pid = coerce_lora_preset_id(out.get("mflux_lora", "none"))
        if pid == "none" and stack:
            out["mflux_lora"] = stack[0]
        out.pop("mflux_lora_stack", None)
    return _sanitize_dialog_values(out)


def save_plugin_dialog_settings(
    function: str,
    plugin_id: str,
    values: Dict[str, Any],
    *,
    active_plugin_id: Optional[str] = None,
) -> None:
    """Persist model-specific settings per plugin; prompt stays function-level."""
    plugin_id = _normalize_plugin_id(plugin_id)
    sanitized, stack = _split_lora_stack_from_values(dict(values))
    persist_stack = _plugin_uses_lora_stack(plugin_id)
    if not persist_stack:
        from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

        sanitized.pop("mflux_lora_stack", None)
        pid = coerce_lora_preset_id(sanitized.get("mflux_lora", "none"))
        if pid == "none" and stack:
            sanitized["mflux_lora"] = stack[0]

    def mutate(imagegen: dict) -> None:
        from imagegen_plugins.image_gen_active_model import (
            apply_active_plugin_to_imagegen,
        )

        dialogs = imagegen.get(_DIALOGS_KEY)
        if not isinstance(dialogs, dict):
            dialogs = {}
            imagegen[_DIALOGS_KEY] = dialogs
        prev_shared = dict(dialogs.get(function) or {})
        prev_shared.update(_shared_function_values(sanitized))
        fn_entry = dict(prev_shared)
        stacks = fn_entry.get(_LORA_STACKS_KEY)
        if not isinstance(stacks, dict):
            stacks = {}
        if persist_stack:
            stacks[plugin_id] = stack
        else:
            stacks.pop(plugin_id, None)
        fn_entry[_LORA_STACKS_KEY] = stacks
        dialogs[function] = fn_entry

        models = imagegen.get(_LEGACY_MODELS_KEY)
        if not isinstance(models, dict):
            models = {}
            imagegen[_LEGACY_MODELS_KEY] = models
        per_plugin = _per_plugin_dialog_values(sanitized)
        if persist_stack:
            per_plugin.pop("mflux_lora", None)
        models[plugin_id] = per_plugin

        aid = active_plugin_id or plugin_id
        apply_active_plugin_to_imagegen(imagegen, function, aid)

    _mutate_imagegen_settings(mutate)


def switch_plugin_persisted_settings(
    function: str,
    outgoing_plugin_id: str,
    outgoing_values: Dict[str, Any],
    incoming_plugin_id: str,
    *,
    active_plugin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Save outgoing plugin state; return persisted settings for the incoming plugin."""
    save_plugin_dialog_settings(
        function,
        outgoing_plugin_id,
        outgoing_values,
        active_plugin_id=active_plugin_id or incoming_plugin_id,
    )
    return load_plugin_dialog_settings(function, incoming_plugin_id)



def save_dialog_sessions_batch(
    sessions: Dict[str, Tuple[Dict[str, Any], Optional[str]]],
) -> None:
    """Persist multiple function dialog values (+ optional plugin ids) in one write."""
    if not sessions:
        return

    prepared: Dict[str, Tuple[Dict[str, Any], Optional[str], List[str]]] = {}
    for function, (values, plugin_id) in sessions.items():
        sanitized, stack = _split_lora_stack_from_values(dict(values))
        if plugin_id is not None and not _plugin_uses_lora_stack(
            _normalize_plugin_id(plugin_id)
        ):
            from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

            sanitized.pop("mflux_lora_stack", None)
            pid = coerce_lora_preset_id(sanitized.get("mflux_lora", "none"))
            if pid == "none" and stack:
                sanitized["mflux_lora"] = stack[0]
        prepared[function] = (sanitized, plugin_id, stack)

    def mutate(imagegen: dict) -> None:
        from imagegen_plugins.image_gen_active_model import (
            apply_active_plugin_to_imagegen,
        )

        dialogs = imagegen.get(_DIALOGS_KEY)
        if not isinstance(dialogs, dict):
            dialogs = {}
            imagegen[_DIALOGS_KEY] = dialogs
        models = imagegen.get(_LEGACY_MODELS_KEY)
        if not isinstance(models, dict):
            models = {}
            imagegen[_LEGACY_MODELS_KEY] = models
        for function, (vals, plugin_id, stack) in prepared.items():
            persist_stack = (
                _plugin_uses_lora_stack(_normalize_plugin_id(plugin_id))
                if plugin_id is not None
                else False
            )
            prev_shared = dict(dialogs.get(function) or {})
            prev_shared.update(_shared_function_values(vals))
            fn_entry = dict(prev_shared)
            if plugin_id is not None:
                stacks = fn_entry.get(_LORA_STACKS_KEY)
                if not isinstance(stacks, dict):
                    stacks = {}
                if persist_stack:
                    stacks[_normalize_plugin_id(plugin_id)] = stack
                else:
                    stacks.pop(_normalize_plugin_id(plugin_id), None)
                fn_entry[_LORA_STACKS_KEY] = stacks
            dialogs[function] = fn_entry
            if plugin_id is not None:
                per_plugin = _per_plugin_dialog_values(vals)
                if persist_stack:
                    per_plugin.pop("mflux_lora", None)
                models[_normalize_plugin_id(plugin_id)] = per_plugin
                apply_active_plugin_to_imagegen(imagegen, function, plugin_id)

    _mutate_imagegen_settings(mutate)


def load_model_settings(plugin_id: str) -> Dict[str, Any]:
    """Per-plugin dialog field values (steps, LoRA, dimensions, …)."""
    plugin_id = _normalize_plugin_id(plugin_id)
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    models = imagegen.get(_LEGACY_MODELS_KEY) or {}
    saved = dict(models.get(plugin_id) or {})
    if not saved and plugin_id == "flux_fill_infill":
        saved = dict(models.get("flux_fill_infil") or {})
    return saved



def load_imagegen_dialog_geometry_hex() -> Optional[str]:
    """Saved image-generation dialog geometry (hex QByteArray), shared by all types."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    geom = imagegen.get("dialog_geometry")
    if isinstance(geom, str) and geom:
        return geom
    geoms = imagegen.get("dialog_geometries")
    if isinstance(geoms, dict):
        for value in geoms.values():
            if isinstance(value, str) and value:
                return value
    legacy_paint = imagegen.get("infill_paint_dialog_geometry")
    return legacy_paint if isinstance(legacy_paint, str) and legacy_paint else None


def save_imagegen_dialog_geometry_hex(geom_hex: str) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["dialog_geometry"] = geom_hex

    _mutate_imagegen_settings(mutate)


def load_close_dialog_on_generate() -> bool:
    """Whether the unified image-gen dialog closes after a successful generate."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    return bool(imagegen.get("close_dialog_on_generate"))


def save_close_dialog_on_generate(enabled: bool) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["close_dialog_on_generate"] = bool(enabled)

    _mutate_imagegen_settings(mutate)


def _legacy_pass_image_to_ai_from_imagegen(imagegen: dict) -> Optional[bool]:
    dialogs = imagegen.get(_DIALOGS_KEY) or {}
    for func_saved in dialogs.values():
        if isinstance(func_saved, dict) and _PASS_IMAGE_TO_AI_KEY in func_saved:
            return bool(func_saved[_PASS_IMAGE_TO_AI_KEY])
    models = imagegen.get(_LEGACY_MODELS_KEY) or {}
    for model_saved in models.values():
        if isinstance(model_saved, dict) and _PASS_IMAGE_TO_AI_KEY in model_saved:
            return bool(model_saved[_PASS_IMAGE_TO_AI_KEY])
    return None


def _strip_legacy_pass_image_to_ai_from_imagegen(imagegen: dict) -> None:
    dialogs = imagegen.get(_DIALOGS_KEY)
    if isinstance(dialogs, dict):
        for func_saved in dialogs.values():
            if isinstance(func_saved, dict):
                func_saved.pop(_PASS_IMAGE_TO_AI_KEY, None)
    models = imagegen.get(_LEGACY_MODELS_KEY)
    if isinstance(models, dict):
        for model_saved in models.values():
            if isinstance(model_saved, dict):
                model_saved.pop(_PASS_IMAGE_TO_AI_KEY, None)


def load_pass_image_to_ai_with_prompt() -> bool:
    """Whether AI prompt refinement should include the source image (all gen dialogs)."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    if _PASS_IMAGE_TO_AI_KEY in imagegen:
        return bool(imagegen[_PASS_IMAGE_TO_AI_KEY])
    legacy = _legacy_pass_image_to_ai_from_imagegen(imagegen)
    if legacy is not None:
        save_pass_image_to_ai_with_prompt(legacy)
        return legacy
    return False


def save_pass_image_to_ai_with_prompt(enabled: bool) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen[_PASS_IMAGE_TO_AI_KEY] = bool(enabled)
        _strip_legacy_pass_image_to_ai_from_imagegen(imagegen)

    _mutate_imagegen_settings(mutate)


def _legacy_show_progressive_images_from_imagegen(imagegen: dict) -> Optional[bool]:
    dialogs = imagegen.get(_DIALOGS_KEY) or {}
    for func_saved in dialogs.values():
        if isinstance(func_saved, dict) and _SHOW_PROGRESSIVE_IMAGES_KEY in func_saved:
            return bool(func_saved[_SHOW_PROGRESSIVE_IMAGES_KEY])
    models = imagegen.get(_LEGACY_MODELS_KEY) or {}
    for model_saved in models.values():
        if isinstance(model_saved, dict) and _SHOW_PROGRESSIVE_IMAGES_KEY in model_saved:
            return bool(model_saved[_SHOW_PROGRESSIVE_IMAGES_KEY])
    return None


def _strip_legacy_show_progressive_images_from_imagegen(imagegen: dict) -> None:
    dialogs = imagegen.get(_DIALOGS_KEY)
    if isinstance(dialogs, dict):
        for func_saved in dialogs.values():
            if isinstance(func_saved, dict):
                func_saved.pop(_SHOW_PROGRESSIVE_IMAGES_KEY, None)
    models = imagegen.get(_LEGACY_MODELS_KEY)
    if isinstance(models, dict):
        for model_saved in models.values():
            if isinstance(model_saved, dict):
                model_saved.pop(_SHOW_PROGRESSIVE_IMAGES_KEY, None)


def load_show_progressive_images() -> bool:
    """Whether intermediate previews are shown during supported image generation."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    if _SHOW_PROGRESSIVE_IMAGES_KEY in imagegen:
        return bool(imagegen[_SHOW_PROGRESSIVE_IMAGES_KEY])
    legacy = _legacy_show_progressive_images_from_imagegen(imagegen)
    if legacy is not None:
        save_show_progressive_images(legacy)
        return legacy
    return False


def save_show_progressive_images(enabled: bool) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen[_SHOW_PROGRESSIVE_IMAGES_KEY] = bool(enabled)
        _strip_legacy_show_progressive_images_from_imagegen(imagegen)

    _mutate_imagegen_settings(mutate)


def load_flux_prompt_job_with_generate() -> bool:
    """Whether Generate should queue an AI prompt-refinement stage with the job."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    return bool(imagegen.get(_FLUX_PROMPT_JOB_WITH_GENERATE_KEY, False))


def save_flux_prompt_job_with_generate(enabled: bool) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen[_FLUX_PROMPT_JOB_WITH_GENERATE_KEY] = bool(enabled)

    _mutate_imagegen_settings(mutate)


def load_flux_prompt_system_prompt_settings() -> tuple[str, bool, list[int], bool]:
    """Global flux Prompt AI system prompt pane state."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    text = imagegen.get(_FLUX_PROMPT_SYSTEM_PROMPT_TEXT_KEY, "")
    visible = bool(imagegen.get(_FLUX_PROMPT_SYSTEM_PROMPT_VISIBLE_KEY, False))
    sizes = imagegen.get(_FLUX_PROMPT_SYSTEM_PROMPT_SPLITTER_SIZES_KEY, [])
    expanded = bool(imagegen.get(_FLUX_PROMPT_SYSTEM_PROMPT_EDITOR_EXPANDED_KEY, True))
    if not isinstance(text, str):
        text = ""
    if not isinstance(sizes, list):
        sizes = []
    return text, visible, sizes, expanded


def save_flux_prompt_system_prompt_settings(
    text: str,
    visible: bool,
    splitter_sizes: list[int],
    *,
    editor_expanded: bool = True,
) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen[_FLUX_PROMPT_SYSTEM_PROMPT_TEXT_KEY] = text
        imagegen[_FLUX_PROMPT_SYSTEM_PROMPT_VISIBLE_KEY] = bool(visible)
        imagegen[_FLUX_PROMPT_SYSTEM_PROMPT_EDITOR_EXPANDED_KEY] = bool(
            editor_expanded
        )
        if (
            isinstance(splitter_sizes, list)
            and len(splitter_sizes) == 2
            and sum(splitter_sizes) > 0
        ):
            imagegen[_FLUX_PROMPT_SYSTEM_PROMPT_SPLITTER_SIZES_KEY] = list(
                splitter_sizes
            )

    _mutate_imagegen_settings(mutate)


def reset_all_gen_dialog_settings() -> None:
    """Clear persisted field values for all image-gen function dialogs (create, edit, …).

    Active model choices, dialog geometry, LoRA catalog, and other non-field prefs are kept.
    """
    from imagegen_plugins.image_gen_active_model import (
        FUNCTION_INFILL,
        FUNCTION_INFILL_PAINT,
        IMAGEGEN_FUNCTIONS,
    )

    persist_functions = set()
    for function in IMAGEGEN_FUNCTIONS:
        if function == FUNCTION_INFILL_PAINT:
            persist_functions.add(FUNCTION_INFILL)
        else:
            persist_functions.add(function)

    def mutate(imagegen: dict) -> None:
        dialogs = imagegen.get(_DIALOGS_KEY)
        if isinstance(dialogs, dict):
            for function in persist_functions:
                dialogs.pop(function, None)

        models = imagegen.get(_LEGACY_MODELS_KEY)
        if isinstance(models, dict):
            models.clear()

    _mutate_imagegen_settings(mutate)


def load_job_queue_geometry_hex() -> Optional[str]:
    """Saved job queue dialog geometry (hex QByteArray), if any."""
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    geom = imagegen.get("job_queue_geometry")
    return geom if isinstance(geom, str) and geom else None


def save_job_queue_geometry_hex(geom_hex: str) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["job_queue_geometry"] = geom_hex

    _mutate_imagegen_settings(mutate)


def load_hold_job_queue() -> bool:
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    return bool(imagegen.get("hold_job_queue", False))


def save_hold_job_queue(enabled: bool) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["hold_job_queue"] = bool(enabled)

    _mutate_imagegen_settings(mutate)


def _json_safe_value(value: Any) -> Any:
    import json

    json.dumps(value)
    return value


def _json_safe_dict(values: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in dict(values).items():
        try:
            out[key] = _json_safe_value(value)
        except (TypeError, ValueError):
            continue
    return out


def serialize_queued_job_record(job) -> Dict[str, Any]:
    """JSON-serializable dict for one pending queue entry."""
    from imagegen_plugins.model_task_queue import QueuedGenerateJob

    if not isinstance(job, QueuedGenerateJob):
        raise TypeError("expected QueuedGenerateJob")
    plugin_id = job.plugin_id or (
        job.plugin.plugin_id if job.plugin is not None else ""
    )
    function = job.function or (
        job.plugin.function if job.plugin is not None else ""
    )
    return {
        "job_id": job.job_id,
        "function": function,
        "plugin_id": plugin_id,
        "values": _json_safe_dict(job.values),
        "copies_total": int(job.copies_total),
        "full_prompt": job.full_prompt,
        "plugin_unavailable": bool(job.plugin_unavailable),
    }


def save_job_queue_records(records: list) -> None:
    def mutate(imagegen: dict) -> None:
        imagegen["job_queue"] = list(records)

    _mutate_imagegen_settings(mutate)


def load_job_queue_records() -> list:
    settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    raw = imagegen.get("job_queue")
    if not isinstance(raw, list):
        return []
    out: list = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("job_id") or "").strip()
        plugin_id = str(item.get("plugin_id") or "").strip()
        function = str(item.get("function") or "").strip()
        values = item.get("values")
        if not job_id or not plugin_id or not function or not isinstance(values, dict):
            continue
        copies_total = item.get("copies_total", values.get("copies", 1))
        try:
            copies_total = max(1, int(copies_total))
        except (TypeError, ValueError):
            copies_total = 1
        out.append(
            {
                "job_id": job_id,
                "plugin_id": plugin_id,
                "function": function,
                "values": dict(values),
                "copies_total": copies_total,
                "full_prompt": str(item.get("full_prompt") or "").strip(),
                "plugin_unavailable": bool(item.get("plugin_unavailable", False)),
            }
        )
    return out









def save_lora_catalog_state(
    *,
    host_id: Optional[str] = None,
    model_id: Optional[str] = None,
    enabled_ids: Optional[list] = None,
    hidden_ids: Optional[list] = None,
    deleted_ids: Optional[list] = None,
    by_host: Optional[Dict[str, Dict[str, list]]] = None,
    by_model: Optional[Dict[str, Dict[str, list]]] = None,
    model_support: Optional[dict] = None,
) -> None:
    from imagegen_plugins.lora_catalog import merged_lora_catalog
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog
    from imagegen_plugins.hf_model_ids import LORA_PROBE_MODEL_ORDER
    from imagegen_plugins.lora_model_registry import entry_matches_lora_model

    hidden = hidden_ids if hidden_ids is not None else deleted_ids

    def mutate(imagegen: dict) -> None:
        lc = imagegen.get("lora_catalog")
        if not isinstance(lc, dict):
            lc = {}
            imagegen["lora_catalog"] = lc
        lc = migrate_lora_catalog(lc)
        catalog = merged_lora_catalog({"imagegen": {"lora_catalog": lc}})
        ms = lc.get("model_support") if isinstance(lc.get("model_support"), dict) else {}

        if by_host is not None:
            bh = dict(lc.get("by_host") or {})
            for hid, slice_ in by_host.items():
                if not isinstance(slice_, dict):
                    continue
                prev = dict(bh.get(hid) or {"enabled_ids": [], "hidden_ids": []})
                if "enabled_ids" in slice_:
                    prev["enabled_ids"] = [
                        str(x)
                        for x in slice_["enabled_ids"]
                        if str(x) in catalog and catalog[str(x)].host_id == hid
                    ]
                if "hidden_ids" in slice_:
                    prev["hidden_ids"] = [
                        str(x)
                        for x in slice_["hidden_ids"]
                        if str(x) in catalog and catalog[str(x)].host_id == hid
                    ]
                bh[hid] = prev
            lc["by_host"] = bh

        if host_id and (enabled_ids is not None or hidden is not None):
            bh = dict(lc.get("by_host") or {})
            prev = dict(bh.get(host_id) or {"enabled_ids": [], "hidden_ids": []})
            if enabled_ids is not None:
                prev["enabled_ids"] = [
                    str(x)
                    for x in enabled_ids
                    if str(x) in catalog and catalog[str(x)].host_id == host_id
                ]
            if hidden is not None:
                prev["hidden_ids"] = [
                    str(x)
                    for x in hidden
                    if str(x) in catalog and catalog[str(x)].host_id == host_id
                ]
            bh[host_id] = prev
            lc["by_host"] = bh

        if by_model is not None:
            bm = dict(lc.get("by_model") or {})
            for mid, slice_ in by_model.items():
                if not isinstance(slice_, dict):
                    continue
                prev = dict(bm.get(mid) or {"enabled_ids": [], "hidden_ids": []})
                if "enabled_ids" in slice_:
                    prev["enabled_ids"] = [
                        str(x)
                        for x in slice_["enabled_ids"]
                    if str(x) in catalog
                    and entry_matches_lora_model(
                        catalog[str(x)], mid, model_support=ms
                    )
                    ]
                if "hidden_ids" in slice_:
                    prev["hidden_ids"] = [
                        str(x)
                        for x in slice_["hidden_ids"]
                    if str(x) in catalog
                    and entry_matches_lora_model(
                        catalog[str(x)], mid, model_support=ms
                    )
                    ]
                bm[mid] = prev
            lc["by_model"] = bm

        if model_id and (enabled_ids is not None or hidden is not None):
            bm = dict(lc.get("by_model") or {})
            prev = dict(bm.get(model_id) or {"enabled_ids": [], "hidden_ids": []})
            if enabled_ids is not None:
                prev["enabled_ids"] = [
                    str(x)
                    for x in enabled_ids
                    if str(x) in catalog
                    and entry_matches_lora_model(
                        catalog[str(x)], model_id, model_support=ms
                    )
                ]
            if hidden is not None:
                prev["hidden_ids"] = [
                    str(x)
                    for x in hidden
                    if str(x) in catalog
                    and entry_matches_lora_model(
                        catalog[str(x)], model_id, model_support=ms
                    )
                ]
            bm[model_id] = prev
            lc["by_model"] = bm

        # Legacy flat keys (flux1_t2i only) for older readers.
        if enabled_ids is not None and host_id in (None, "flux1_t2i"):
            lc["enabled_ids"] = [
                str(x)
                for x in (enabled_ids if host_id else lc.get("by_host", {}).get("flux1_t2i", {}).get("enabled_ids", []))
                if str(x) in catalog
            ]
        if hidden is not None and host_id is None:
            lc["deleted_ids"] = sorted(
                {
                    str(x)
                    for hid, slice_ in (lc.get("by_host") or {}).items()
                    for x in (slice_.get("hidden_ids") or [])
                    if str(x) in catalog
                }
            )

        if model_support is not None:
            prev_ms = lc.get("model_support")
            cleaned: dict = {}
            if isinstance(prev_ms, dict):
                cleaned = {
                    str(k): list(v)
                    for k, v in prev_ms.items()
                    if str(k) in catalog and isinstance(v, (list, tuple))
                }
            allowed = set(LORA_PROBE_MODEL_ORDER)
            for lid, models in model_support.items():
                lid_s = str(lid)
                if lid_s not in catalog:
                    continue
                if not isinstance(models, (list, tuple)):
                    continue
                cleaned[lid_s] = [str(m) for m in models if str(m) in allowed]
            lc["model_support"] = cleaned

        imagegen["lora_catalog"] = lc

    _mutate_imagegen_settings(mutate)


def register_user_lora(
    entry,
    *,
    model_key: str,
    supported_models: list,
) -> None:
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog
    from imagegen_plugins.lora_user_entries import USER_ENTRIES_KEY, _entry_to_dict

    def mutate(imagegen: dict) -> None:
        lc = migrate_lora_catalog(dict(imagegen.get("lora_catalog") or {}))
        raw = dict(lc.get(USER_ENTRIES_KEY) or {})
        raw[entry.lora_id] = _entry_to_dict(entry)
        lc[USER_ENTRIES_KEY] = raw
        ms = dict(lc.get("model_support") or {})
        prev = ms.get(entry.lora_id) or []
        merged = list(dict.fromkeys([*(prev if isinstance(prev, list) else []), *supported_models]))
        ms[entry.lora_id] = merged
        lc["model_support"] = ms
        bm = dict(lc.get("by_model") or {})
        slice_ = dict(bm.get(model_key) or {"enabled_ids": [], "hidden_ids": []})
        enabled = list(slice_.get("enabled_ids") or [])
        if entry.lora_id not in enabled:
            enabled.append(entry.lora_id)
        hidden = [h for h in (slice_.get("hidden_ids") or []) if h != entry.lora_id]
        bm[model_key] = {"enabled_ids": enabled, "hidden_ids": hidden}
        lc["by_model"] = bm
        imagegen["lora_catalog"] = lc

    _mutate_imagegen_settings(mutate)


def update_lora_entry_metadata(
    lora_id: str,
    *,
    display_name: str,
    trigger_word: Optional[str] = None,
    scale: float = 1.0,
    comment: Optional[str] = None,
) -> None:
    """Persist user-editable LoRA metadata (name, trigger, scale, comment)."""
    from imagegen_plugins.lora_catalog import LORA_CATALOG
    from imagegen_plugins.lora_catalog_settings import (
        ENTRY_OVERRIDES_KEY,
        migrate_lora_catalog,
    )
    from imagegen_plugins.lora_user_entries import USER_ENTRIES_KEY, is_user_lora_id

    lid = str(lora_id or "").strip()
    if not lid:
        return
    name = (display_name or "").strip()
    if not name:
        raise ValueError("Display name is required.")
    trigger = (trigger_word or "").strip() or None
    note = (comment or "").strip() or None
    try:
        scale_val = float(scale)
    except (TypeError, ValueError):
        scale_val = 1.0

    def mutate(imagegen: dict) -> None:
        lc = migrate_lora_catalog(dict(imagegen.get("lora_catalog") or {}))
        if is_user_lora_id(lid):
            raw = dict(lc.get(USER_ENTRIES_KEY) or {})
            entry_dict = raw.get(lid)
            if not isinstance(entry_dict, dict):
                raise ValueError(f"User LoRA {lid!r} was not found.")
            entry_dict = dict(entry_dict)
            entry_dict["display_name"] = name
            entry_dict["trigger_word"] = trigger
            entry_dict["scale"] = scale_val
            entry_dict["comment"] = note
            raw[lid] = entry_dict
            lc[USER_ENTRIES_KEY] = raw
        else:
            if lid not in LORA_CATALOG:
                raise ValueError(f"LoRA {lid!r} was not found.")
            overrides = dict(lc.get(ENTRY_OVERRIDES_KEY) or {})
            overrides[lid] = {
                "display_name": name,
                "trigger_word": trigger,
                "scale": scale_val,
                "comment": note,
            }
            lc[ENTRY_OVERRIDES_KEY] = overrides
        imagegen["lora_catalog"] = lc

    _mutate_imagegen_settings(mutate)



def remove_user_lora(lora_id: str) -> None:
    from imagegen_plugins.lora_catalog import get_lora_entry
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog
    from imagegen_plugins.lora_user_entries import (
        USER_ENTRIES_KEY,
        is_user_lora_id,
        remove_user_lora_files,
    )

    if not is_user_lora_id(lora_id):
        return
    entry = get_lora_entry(lora_id)
    if entry is not None:
        remove_user_lora_files(entry)

    def mutate(imagegen: dict) -> None:
        lc = migrate_lora_catalog(dict(imagegen.get("lora_catalog") or {}))
        raw = dict(lc.get(USER_ENTRIES_KEY) or {})
        raw.pop(lora_id, None)
        lc[USER_ENTRIES_KEY] = raw
        ms = dict(lc.get("model_support") or {})
        ms.pop(lora_id, None)
        lc["model_support"] = ms
        bm = dict(lc.get("by_model") or {})
        for mk, slice_ in list(bm.items()):
            if not isinstance(slice_, dict):
                continue
            enabled = [x for x in (slice_.get("enabled_ids") or []) if x != lora_id]
            bm[mk] = {"enabled_ids": enabled, "hidden_ids": []}
        lc["by_model"] = bm
        imagegen["lora_catalog"] = lc

    _mutate_imagegen_settings(mutate)


def remove_lora_enabled_everywhere(lora_id: str) -> None:
    """Remove a LoRA id from enabled lists for every base model and host in settings."""
    from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog

    lid = str(lora_id or "").strip()
    if not lid:
        return

    def mutate(imagegen: dict) -> None:
        lc = migrate_lora_catalog(dict(imagegen.get("lora_catalog") or {}))
        bm = dict(lc.get("by_model") or {})
        for mk, slice_ in list(bm.items()):
            if not isinstance(slice_, dict):
                continue
            enabled = [x for x in (slice_.get("enabled_ids") or []) if x != lid]
            bm[mk] = {"enabled_ids": enabled, "hidden_ids": []}
        lc["by_model"] = bm
        bh = dict(lc.get("by_host") or {})
        for hid, slice_ in list(bh.items()):
            if not isinstance(slice_, dict):
                continue
            enabled = [x for x in (slice_.get("enabled_ids") or []) if x != lid]
            bh[hid] = {"enabled_ids": enabled, "hidden_ids": []}
        lc["by_host"] = bh
        imagegen["lora_catalog"] = lc

    _mutate_imagegen_settings(mutate)
