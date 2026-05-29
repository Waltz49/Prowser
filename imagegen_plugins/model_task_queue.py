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

_PREVIEW_OUTPUT = "/tmp/.__imagegen_queue_preview__.png"


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
        src = str(values.get("source_image_path") or "")
        if src and os.path.isfile(src):
            paths.append(os.path.normpath(src))
    if plugin.pipeline_id == "mflux_fill_infill":
        px_path = values.get("pixelmator_doc_path")
        if px_path and os.path.isfile(str(px_path)):
            paths.append(os.path.normpath(str(px_path)))
    return paths


def make_queued_generate_job(
    plugin: ImageGenModelPlugin, values: dict[str, Any], *, copies_total: int
) -> QueuedGenerateJob:
    payload = plugin.build_payload(values, _PREVIEW_OUTPUT)
    status_html = format_image_generation_queue_status_html(
        plugin,
        values,
        payload,
        series_copies_total=copies_total,
    )
    return QueuedGenerateJob(
        job_id=uuid.uuid4().hex,
        plugin=plugin,
        values=dict(values),
        status_html=status_html,
        thumbnail_paths=thumbnail_paths_for_values(plugin, values),
        copies_total=copies_total,
        full_prompt=str(values.get("prompt") or "").strip(),
    )
