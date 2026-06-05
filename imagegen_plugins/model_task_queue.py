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

def _preview_output_path() -> str:
    from prowser_temp_files import ensure_temporary_files_directory

    return os.path.join(
        ensure_temporary_files_directory(), ".__imagegen_queue_preview__.png"
    )


@dataclass
class QueuedGenerateJob:
    job_id: str
    plugin: ImageGenModelPlugin
    values: dict[str, Any]
    status_html: str
    thumbnail_paths: list[str]
    copies_total: int
    full_prompt: str = ""


@dataclass
class QueueRowSnapshot:
    job_id: str
    is_active: bool
    status_html: str
    thumbnail_paths: list[str]
    full_prompt: str = ""


def thumbnail_paths_for_values(
    plugin: ImageGenModelPlugin, values: dict[str, Any]
) -> list[str]:
    paths: list[str] = []
    pipeline = get_pipeline(plugin.pipeline_id)
    if pipeline.requires_source_image:
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths

        for src in resolve_source_image_paths(values):
            paths.append(os.path.normpath(src))
    if plugin.pipeline_id == "mflux_fill_infill":
        px_path = values.get("pixelmator_doc_path")
        if px_path and os.path.isfile(str(px_path)):
            paths.append(os.path.normpath(str(px_path)))
    return paths


def refresh_queued_job_status(job: QueuedGenerateJob) -> None:
    """Rebuild status HTML after queue-row series edits (copies / refinement)."""
    payload = job.plugin.build_payload(job.values, _preview_output_path())
    job.status_html = format_image_generation_queue_status_html(
        job.plugin,
        job.values,
        payload,
        series_copies_total=job.copies_total,
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
        full_prompt=str(values.get("prompt") or "").strip(),
    )
    refresh_queued_job_status(job)
    return job
