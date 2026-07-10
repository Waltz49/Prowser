#!/usr/bin/env python3
"""Queued image-gen jobs with an LM Studio prompt-refinement stage."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

FLUX_PROMPT_AI_JOB_KEY = "flux_prompt_ai_job"


def _append_existing_image_path(path: str, paths: List[str]) -> None:
    normalized = (path or "").strip()
    if normalized and os.path.isfile(normalized) and normalized not in paths:
        paths.append(normalized)


def resolve_flux_prompt_refine_image_paths(owner: Any) -> List[str]:
    """Resolve reference image(s) for Gen Prompt when Pass image is checked."""
    from imagegen_plugins.image_gen_active_model import (
        FUNCTION_CREATE,
        FUNCTION_EDIT,
        FUNCTION_EXPAND,
        FUNCTION_INFILL_PAINT,
    )

    paths: List[str] = []
    function = getattr(owner, "_function", None)

    if function == FUNCTION_EDIT:
        # Edit always uses the first image in the canvas as the AI reference.
        _append_existing_image_path(getattr(owner, "source_path", None) or "", paths)
        if not paths:
            source_paths = getattr(owner, "_source_paths", None) or []
            if source_paths:
                _append_existing_image_path(str(source_paths[0]), paths)
        return paths

    if function in (FUNCTION_EXPAND, FUNCTION_INFILL_PAINT):
        _append_existing_image_path(getattr(owner, "source_path", None) or "", paths)
        return paths

    if function == FUNCTION_CREATE:
        from imagegen_plugins.image_gen_source_nav import (
            active_image_path_for_browse_or_thumbnail,
            resolve_image_gen_main_window,
        )

        active = active_image_path_for_browse_or_thumbnail(
            resolve_image_gen_main_window(owner)
        )
        if active:
            _append_existing_image_path(active, paths)
        return paths

    _append_existing_image_path(getattr(owner, "source_path", None) or "", paths)
    return paths


def pass_image_checked_for_owner(owner: Any) -> bool:
    """True when Pass image is enabled on the panel's AI controls."""
    from imagegen_plugins.image_gen_dialog import pass_image_to_ai_checked

    return pass_image_to_ai_checked(owner)


def allow_empty_prompt_for_ai_refine(flux_ai: Any, owner: Any) -> bool:
    """True when Gen Prompt may run with an empty prompt field."""
    prompt = (flux_ai._get_prompt_text() or "").strip()
    if prompt:
        return True
    if not pass_image_checked_for_owner(owner):
        return False
    return bool(resolve_flux_prompt_refine_image_paths(owner))


def job_title_with_ai_suffix(title: str) -> str:
    base = (title or "").strip()
    if not base:
        return "+AI"
    if base.endswith("+AI"):
        return base
    return f"{base} +AI"


def has_flux_prompt_ai_job(values: Dict[str, Any] | None) -> bool:
    if not isinstance(values, dict):
        return False
    meta = values.get(FLUX_PROMPT_AI_JOB_KEY)
    return isinstance(meta, dict) and bool(meta)


def flux_prompt_ai_job_meta(values: Dict[str, Any] | None) -> dict[str, Any] | None:
    if not has_flux_prompt_ai_job(values):
        return None
    assert values is not None
    meta = values.get(FLUX_PROMPT_AI_JOB_KEY)
    if not isinstance(meta, dict):
        return None
    return meta


def flux_prompt_ai_reference_image_paths(values: Dict[str, Any] | None) -> List[str]:
    """Original image paths sent to LM Studio for queued Job AI prompt refinement."""
    meta = flux_prompt_ai_job_meta(values)
    if meta is None:
        return []
    raw = meta.get("image_paths")
    if not isinstance(raw, list):
        return []
    paths: List[str] = []
    for item in raw:
        _append_existing_image_path(str(item or ""), paths)
    return paths


def flux_prompt_ai_user_prompt(values: Dict[str, Any] | None) -> str:
    """Pre-AI user prompt stored in queued job AI metadata."""
    meta = flux_prompt_ai_job_meta(values)
    if meta is not None:
        user = str(meta.get("user_prompt") or "").strip()
        if user:
            return user
    if isinstance(values, dict):
        return str(values.get("prompt") or "").strip()
    return ""


def effective_job_prompt_for_tooltip(values: Dict[str, Any] | None) -> str:
    """Current prompt for job hover tooltips (includes post-AI refinement)."""
    if not isinstance(values, dict):
        return ""
    current = str(values.get("prompt") or "").strip()
    if not current:
        current = flux_prompt_ai_user_prompt(values)
    if not current:
        return ""
    from imagegen_plugins.lora_trigger_prompt_guard import (
        augment_prompt_with_missing_lora_triggers,
    )

    return augment_prompt_with_missing_lora_triggers(current, values)


def clear_flux_prompt_ai_job(values: Dict[str, Any]) -> None:
    values.pop(FLUX_PROMPT_AI_JOB_KEY, None)


def set_flux_prompt_ai_job(values: Dict[str, Any], meta: dict[str, Any]) -> None:
    values[FLUX_PROMPT_AI_JOB_KEY] = dict(meta)


def build_flux_prompt_ai_job_meta(flux_ai: Any, owner: Any) -> dict[str, Any] | None:
    """Build AI stage metadata from the flux prompt toolbar state."""
    from workers.model_tasks_worker import flux_prompt_system_message

    preflight_error = flux_ai._preflight_ai_refine()
    if preflight_error:
        return None

    user_prompt = (flux_ai._get_prompt_text() or "").strip()
    image_paths = flux_ai._resolve_image_paths_for_refine()
    override = None
    if flux_ai._get_system_prompt_override is not None:
        override = flux_ai._get_system_prompt_override()
    if not override:
        from imagegen_plugins.flux_prompt_system_mount import (
            flux_prompt_system_override_for,
        )

        override = flux_prompt_system_override_for(owner)
    if override:
        system_prompt = override
    else:
        system_prompt = flux_prompt_system_message(
            flux_ai._task_kind,
            with_image=bool(image_paths),
            image_count=len(image_paths),
        )
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "image_paths": list(image_paths),
        "task_kind": flux_ai._task_kind,
    }


def flux_prompt_ai_job_ui_active(owner: Any) -> bool:
    """True when flux prompt AI toolbar exists and the system-prompt pane is visible."""
    from imagegen_plugins.flux_prompt_system_mount import flux_prompt_ai_controls_visible

    if not flux_prompt_ai_controls_visible(owner):
        return False
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    return flux_ai is not None and flux_ai.ai_controls_mounted()


def strip_flux_prompt_ai_job_if_ui_inactive(
    owner: Any | None, values: Dict[str, Any]
) -> None:
    """Drop queued AI stage metadata when the submitting dialog has no visible AI UI."""
    if owner is None or flux_prompt_ai_job_ui_active(owner):
        return
    clear_flux_prompt_ai_job(values)


def attach_flux_prompt_ai_job_to_values(
    owner: Any,
    values: Dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    """Embed or clear flux_prompt_ai_job on values. Returns True when meta attached."""
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    clear_flux_prompt_ai_job(values)
    if not flux_prompt_ai_job_ui_active(owner):
        return False
    if not force and not flux_ai.job_checkbox_checked(owner):
        return False
    meta = build_flux_prompt_ai_job_meta(flux_ai, owner)
    if meta is None:
        return False
    set_flux_prompt_ai_job(values, meta)
    return True


def prompt_required_for_generate(owner: Any, values: Dict[str, Any]) -> bool:
    """False when Job AI can run with empty prompt (pass-image preflight passes)."""
    return not allow_empty_prompt_for_flux_ai_job(owner, force=False)


def allow_empty_prompt_for_flux_ai_job(
    owner: Any, *, force: bool = False
) -> bool:
    if not flux_prompt_ai_job_ui_active(owner):
        return False
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    if flux_ai is None:
        return False
    if force or flux_ai.job_checkbox_checked(owner):
        return flux_ai._preflight_ai_refine() is None
    return False


def apply_flux_prompt_job_to_prepare_run_values(
    owner: Any,
    values: Dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    """After validation, attach or strip AI job meta. Returns False if force attach fails."""
    if not flux_prompt_ai_job_ui_active(owner):
        clear_flux_prompt_ai_job(values)
        if force:
            return False
        return True
    if force:
        if not attach_flux_prompt_ai_job_to_values(owner, values, force=True):
            return False
        return True
    attach_flux_prompt_ai_job_to_values(owner, values, force=False)
    return True
