#!/usr/bin/env python3
"""FIFO queue entries for image-generation jobs."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.model_task_status_info import format_image_generation_queue_status_html
from imagegen_plugins.flux_prompt_job import (
    effective_job_prompt_for_tooltip,
    has_flux_prompt_ai_job,
)

_PAINT_INFILL_SOURCE_EXTS = frozenset({".pxd", ".pxm"})


def _preview_output_path() -> str:
    from prowser_temp_files import ensure_temporary_files_directory

    return os.path.join(
        ensure_temporary_files_directory(), ".__imagegen_queue_preview__.png"
    )


def _is_paint_infill_values(values: dict[str, Any]) -> bool:
    doc_path = str(values.get("pixelmator_doc_path") or "").strip()
    if not doc_path or not os.path.isfile(doc_path):
        return False
    _, ext = os.path.splitext(doc_path)
    return ext.lower() in _PAINT_INFILL_SOURCE_EXTS


def missing_reference_paths(
    plugin: ImageGenModelPlugin | None, values: dict[str, Any]
) -> list[str]:
    """Paths required for this job that are missing on disk."""
    from imagegen_plugins.flux_prompt_job import flux_prompt_ai_job_meta
    from imagegen_plugins.image_gen_active_model import (
        FUNCTION_EDIT,
        FUNCTION_EXPAND,
        FUNCTION_INFILL,
    )
    from imagegen_plugins.image_gen_naming import resolve_source_image_paths

    if plugin is None:
        return ["(model unavailable)"]

    missing: list[str] = []
    function = plugin.function
    if function == FUNCTION_EDIT:
        resolved = resolve_source_image_paths(values)
        for raw in resolved:
            if raw and not os.path.isfile(raw):
                missing.append(raw)
        if not any(p and os.path.isfile(p) for p in resolved):
            if not missing:
                missing.append("(source image)")
    elif function == FUNCTION_EXPAND:
        source_path = str(values.get("source_image_path") or "").strip()
        if not source_path or not os.path.isfile(source_path):
            missing.append(source_path or "(source image)")
    elif function == FUNCTION_INFILL:
        if _is_paint_infill_values(values):
            mask_path = str(values.get("pixelmator_mask_path") or "")
            if mask_path and not os.path.isfile(mask_path):
                missing.append(mask_path)
        else:
            base_path = str(values.get("pixelmator_base_path") or "")
            mask_path = str(values.get("pixelmator_mask_path") or "")
            for path in (base_path, mask_path):
                if path and not os.path.isfile(path):
                    missing.append(path)
    ai_meta = flux_prompt_ai_job_meta(values)
    if isinstance(ai_meta, dict):
        raw_paths = ai_meta.get("image_paths")
        if isinstance(raw_paths, list):
            for item in raw_paths:
                path = str(item or "").strip()
                if path and not os.path.isfile(path):
                    missing.append(path)
    return missing


def job_references_invalid(
    plugin: ImageGenModelPlugin | None, values: dict[str, Any]
) -> bool:
    return bool(missing_reference_paths(plugin, values))


@dataclass
class QueuedGenerateJob:
    job_id: str
    plugin: ImageGenModelPlugin | None
    values: dict[str, Any]
    status_html: str
    thumbnail_paths: list[str]
    copies_total: int
    full_prompt: str = ""
    plugin_id: str = ""
    function: str = ""
    plugin_unavailable: bool = False
    references_invalid: bool = False


@dataclass
class QueueRowSnapshot:
    job_id: str
    is_active: bool
    status_html: str
    thumbnail_paths: list[str]
    full_prompt: str = ""
    references_invalid: bool = False


def thumbnail_paths_for_values(
    plugin: ImageGenModelPlugin | None, values: dict[str, Any]
) -> list[str]:
    if plugin is None:
        return []
    paths: list[str] = []
    seen: set[str] = set()

    def _append_path(raw: str) -> None:
        normalized = os.path.normpath(str(raw or ""))
        if normalized and os.path.isfile(normalized) and normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)

    pipeline = get_pipeline(plugin.pipeline_id)
    if pipeline.requires_source_image:
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths

        for src in resolve_source_image_paths(values):
            _append_path(src)
    if plugin.pipeline_id == "mflux_fill_infill":
        px_path = values.get("pixelmator_doc_path")
        if px_path:
            _append_path(str(px_path))
    from imagegen_plugins.flux_prompt_job import flux_prompt_ai_reference_image_paths

    for src in flux_prompt_ai_reference_image_paths(values):
        _append_path(src)
    return paths


def apply_payload_model_fields_to_values(
    values: dict[str, Any],
    payload: dict[str, Any],
    *,
    sync_prompt: bool = True,
) -> None:
    """Persist worker payload fields used for display, dequeue, and EXIF."""
    hf = payload.get("hf_model_id")
    if hf:
        values["hf_model_id"] = hf
    if sync_prompt and "prompt" in payload:
        values["prompt"] = payload["prompt"]


def _unavailable_job_status_html(
    plugin_id: str, function: str, values: dict[str, Any], *, copies_total: int
) -> str:
    prompt = str(values.get("prompt") or "").strip()
    preview = prompt[:48] + ("…" if len(prompt) > 48 else "")
    return (
        f"<b>Unavailable model</b> ({function} / {plugin_id})<br>"
        f"Copies: {copies_total}<br>"
        f"Prompt: {preview or '—'}"
    )


def refresh_queued_job_status(job: QueuedGenerateJob) -> None:
    """Rebuild status HTML after queue-row series edits (copies / refinement)."""
    if job.plugin is None or job.plugin_unavailable:
        job.status_html = _unavailable_job_status_html(
            job.plugin_id,
            job.function,
            job.values,
            copies_total=job.copies_total,
        )
        return
    payload = job.plugin.build_payload(
        job.values,
        _preview_output_path(),
        apply_image_exit=not has_flux_prompt_ai_job(job.values),
    )
    apply_payload_model_fields_to_values(job.values, payload, sync_prompt=False)
    exited = str(payload.get("prompt") or "").strip()
    if exited and not has_flux_prompt_ai_job(job.values):
        job.full_prompt = exited
    else:
        job.full_prompt = effective_job_prompt_for_tooltip(job.values)
    job.status_html = format_image_generation_queue_status_html(
        job.plugin,
        job.values,
        payload,
        series_copies_total=job.copies_total,
        with_ai=has_flux_prompt_ai_job(job.values),
    )


def make_queued_generate_job(
    plugin: ImageGenModelPlugin, values: dict[str, Any], *, copies_total: int
) -> QueuedGenerateJob:
    job = QueuedGenerateJob(
        job_id=uuid.uuid4().hex,
        plugin=plugin,
        values=dict(values),
        status_html="",
        thumbnail_paths=thumbnail_paths_for_values(plugin, values),
        copies_total=copies_total,
        full_prompt=effective_job_prompt_for_tooltip(values),
        plugin_id=plugin.plugin_id,
        function=plugin.function,
    )
    job.references_invalid = job_references_invalid(plugin, values)
    refresh_queued_job_status(job)
    return job


def restore_queued_generate_job(
    *,
    job_id: str,
    plugin: ImageGenModelPlugin | None,
    plugin_id: str,
    function: str,
    values: dict[str, Any],
    copies_total: int,
    full_prompt: str = "",
    plugin_unavailable: bool = False,
    skip_status_html: bool = False,
) -> QueuedGenerateJob:
    job = QueuedGenerateJob(
        job_id=job_id,
        plugin=plugin,
        values=dict(values),
        status_html="",
        thumbnail_paths=thumbnail_paths_for_values(plugin, values),
        copies_total=copies_total,
        full_prompt=full_prompt or str(values.get("prompt") or "").strip(),
        plugin_id=plugin_id,
        function=function,
        plugin_unavailable=plugin_unavailable,
    )
    job.references_invalid = (
        plugin_unavailable or job_references_invalid(plugin, values)
    )
    if not skip_status_html:
        refresh_queued_job_status(job)
    return job
