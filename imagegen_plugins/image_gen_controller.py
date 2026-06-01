#!/usr/bin/env python3
"""Controller for local image generation and LM Studio captions (shared worker)."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from imagegen_plugins.edit_aspect_pad import remove_edit_aspect_pad_temps
from imagegen_plugins.expand_base_image import (
    prepare_and_save_expand_base,
    remove_expand_base_temp,
)
from imagegen_plugins.image_gen_naming import (
    format_image_exif_prompt,
    lora_name_for_exif,
    make_readable_user_comment_before_browse,
    next_imagegen_path,
    apply_refinement_source_for_next_copy,
    reference_entries_for_source_paths,
    resolve_source_image_paths,
    resolve_generation_elapsed_seconds,
    write_exif_user_comment,
)
from imagegen_plugins.image_gen_persistence import load_dialog_settings, save_dialog_settings
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.image_gen_seed_persistence import (
    extract_used_seed_from_worker_result,
    parse_worker_stdout,
)
from imagegen_plugins.model_task_queue import (
    QueuedGenerateJob,
    QueueRowSnapshot,
    make_queued_generate_job,
    thumbnail_paths_for_values,
)
from imagegen_plugins.model_task_status_info import (
    _append_table_rows,
    _series_after_this_one_value,
    _table_row,
    apply_cooldown_to_status_html,
    cooldown_skip_icon_html,
    format_caption_status_html,
    format_image_generation_queue_status_html,
    format_image_generation_status_html,
    format_series_line_value,
    freeze_status_html_generation_elapsed,
    refresh_expand_task_status_html_for_display,
    remove_elapsed_row,
    strip_cooldown_from_status_html,
    update_status_html_steps_progress,
)
from model_tasks_controller import get_model_tasks_controller
from utils import show_styled_critical, show_styled_question, show_styled_warning

_COPY_COOLDOWN_MS = 60_000
_COPIES_MIN = 1
_COPIES_MAX = 200


class ImageGenController(QObject):
    """UI façade for model tasks (generation + caption) on one background worker."""

    generation_started = Signal()
    generation_finished = Signal(bool, str, str)  # success, output_path, error_message
    task_status_info_changed = Signal()
    queue_changed = Signal()

    caption_chunk = Signal(str)
    caption_ready = Signal(str)
    caption_error = Signal(str)
    caption_finished = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._tasks = get_model_tasks_controller(self)
        self._tasks.set_generate_progress_callback(self._on_generate_progress)
        self._tasks.generation_started.connect(self._on_generation_started)
        self._tasks.generation_finished.connect(self._on_generation_finished)
        self._tasks.caption_chunk.connect(self.caption_chunk.emit)
        self._tasks.caption_ready.connect(self.caption_ready.emit)
        self._tasks.caption_error.connect(self._on_caption_error)
        self._tasks.task_started.connect(self._on_task_started)
        self._tasks.job_processing_started.connect(self._on_job_processing_started)
        self._tasks.task_finished.connect(self._on_task_finished)

        self._queue: List[QueuedGenerateJob] = []
        self._active_queue_job_id: str = ""
        self._active_thumbnail_paths: list[str] = []

        self._active_plugin: Optional[ImageGenModelPlugin] = None
        self._output_path: str = ""
        self._pending_values: Dict[str, Any] = {}
        self._progressive_browse_opened = False
        self._task_status_info_html: str = ""
        self._step_progress_start_time: Optional[float] = None
        self._expand_source_path: str = ""
        self._expand_base_path: str = ""
        self._aspect_pad_temp_paths: list[str] = []
        self._task_reference_paths: list[str] = []
        self._suppress_task_failure_ui = False
        self._copies_total = 0
        self._copies_done = 0
        self._copy_batch_active = False
        self._copy_batch_cancelled = False
        self._cooldown_timer: Optional[QTimer] = None
        self._cooldown_deadline: Optional[float] = None
        self._frozen_elapsed_seconds: Optional[float] = None
        self._last_cooldown_ui_second: Optional[int] = None
        self._live_step = 0
        self._live_step_total = 0
        self._live_elapsed_seconds: Optional[float] = None
        self._live_estimate_seconds: Optional[float] = None
        # Seconds per step, frozen when a diffusion step completes (for live ETA).
        self._step_seconds_per_step: Optional[float] = None

    def is_running(self) -> bool:
        if self._copy_batch_active and not self._copy_batch_cancelled:
            return True
        timer = self._cooldown_timer
        if timer is not None and timer.isActive():
            return True
        return self._tasks.is_running()

    def has_pending_work(self) -> bool:
        return bool(self._queue) or self.is_running()

    def is_queue_empty(self) -> bool:
        return not self._queue

    @property
    def active_queue_job_id(self) -> str:
        return self._active_queue_job_id

    def active_job_full_prompt(self) -> str:
        return str(self._pending_values.get("prompt") or "").strip()

    def queue_snapshot(self) -> list[QueueRowSnapshot]:
        rows: list[QueueRowSnapshot] = []
        if self._active_queue_job_id:
            rows.append(
                QueueRowSnapshot(
                    job_id=self._active_queue_job_id,
                    is_active=True,
                    status_html=self._task_status_info_html,
                    thumbnail_paths=list(self._active_thumbnail_paths),
                    full_prompt=self.active_job_full_prompt(),
                )
            )
        for job in self._queue:
            rows.append(
                QueueRowSnapshot(
                    job_id=job.job_id,
                    is_active=False,
                    status_html=job.status_html,
                    thumbnail_paths=list(job.thumbnail_paths),
                    full_prompt=job.full_prompt,
                )
            )
        return rows

    def job_record_for_row(
        self, row: int
    ) -> tuple[ImageGenModelPlugin, Dict[str, Any]] | None:
        """Return (plugin, values) for a queue table row (active or pending)."""
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return None
        entry = rows[row]
        if entry.is_active:
            plugin = self._active_plugin
            if plugin is None:
                return None
            return plugin, dict(self._pending_values)
        for job in self._queue:
            if job.job_id == entry.job_id:
                return job.plugin, dict(job.values)
        return None

    def start_generation(
        self, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        values["copies"] = copies
        if copies > 1 and not values.get("random_seed"):
            show_styled_warning(
                self.main_window,
                "Random seed required",
                "Copies greater than 1 require Random seed to be enabled "
                "so each image uses a different seed.",
            )
            return False

        if self.is_running():
            return self.enqueue_generation(plugin, values)

        return self._start_generation_now(plugin, values)

    def enqueue_generation(
        self, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        copies = self._normalize_copies(values.get("copies", 1))
        try:
            job = make_queued_generate_job(
                plugin, values, copies_total=copies
            )
        except Exception as e:
            show_styled_critical(
                self.main_window,
                "Could not queue job",
                str(e),
            )
            return False
        self._queue.append(job)
        self.queue_changed.emit()
        self._sync_cancel_menu()
        return True

    def cancel_queued_job(self, job_id: str) -> None:
        before = len(self._queue)
        self._queue = [job for job in self._queue if job.job_id != job_id]
        if len(self._queue) != before:
            self.queue_changed.emit()
            self._sync_cancel_menu()

    def cancel_job_at_row(self, row: int) -> None:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return
        entry = rows[row]
        if entry.is_active:
            self.cancel_active_job()
        else:
            self.cancel_queued_job(entry.job_id)

    def cancel_active_job(self) -> None:
        self.cancel_generation()

    @staticmethod
    def _normalize_copies(raw: Any) -> int:
        try:
            copies = int(raw)
        except (TypeError, ValueError):
            copies = 1
        return max(_COPIES_MIN, min(_COPIES_MAX, copies))

    def _start_generation_now(
        self,
        plugin: ImageGenModelPlugin,
        values: Dict[str, Any],
        *,
        job_id: str | None = None,
        status_html: str | None = None,
        thumbnail_paths: list[str] | None = None,
    ) -> bool:
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        values["copies"] = copies

        self._active_queue_job_id = job_id or uuid.uuid4().hex
        self._active_thumbnail_paths = list(
            thumbnail_paths if thumbnail_paths is not None
            else thumbnail_paths_for_values(plugin, values)
        )

        self._copies_total = copies
        self._copies_done = 0
        self._copy_batch_active = copies > 1
        self._copy_batch_cancelled = False
        self._stop_copy_cooldown_timer()

        self._active_plugin = plugin
        self._pending_values = values
        self._progressive_browse_opened = False

        if status_html:
            self._task_status_info_html = status_html
            self.task_status_info_changed.emit()

        self.queue_changed.emit()
        return self._launch_generation_job()

    def _launch_generation_job(self) -> bool:
        plugin = self._active_plugin
        values = self._pending_values
        if plugin is None:
            return False

        output_path = next_imagegen_path(ext=".png")
        try:
            payload = plugin.build_payload(values, output_path)
            pad_temps = payload.pop("_aspect_pad_temp_paths", None)
            if isinstance(pad_temps, list) and pad_temps:
                self._aspect_pad_temp_paths.extend(str(p) for p in pad_temps)
            if plugin.pipeline_id == "mflux_fill_expand":
                base_path = prepare_and_save_expand_base(values, output_path)
                payload["prepared_fill_image_path"] = base_path
                self._expand_source_path = str(values.get("source_image_path") or "")
                self._expand_base_path = base_path
            elif get_pipeline(plugin.pipeline_id).requires_source_image:
                from imagegen_plugins.image_gen_naming import resolve_source_image_paths

                self._expand_source_path = str(values.get("source_image_path") or "")
                self._expand_base_path = ""
                self._task_reference_paths = resolve_source_image_paths(values)
            else:
                self._expand_source_path = ""
                self._expand_base_path = ""
        except Exception as e:
            show_styled_critical(
                self.main_window,
                "Generation failed",
                str(e),
            )
            self._finish_copy_batch()
            return False

        self._output_path = output_path
        if isinstance(payload.get("steps"), (int, float)):
            self._pending_values["steps"] = int(payload["steps"])
        if self._copies_done == 0 and not self._task_status_info_html:
            self._task_status_info_html = format_image_generation_status_html(
                plugin, values, payload
            )
            self.task_status_info_changed.emit()

        from config import get_config

        payload["debug_mode"] = bool(
            get_config().load_settings().get("debug_mode", False)
        )

        if not self._tasks.start_generate_job(payload):
            show_styled_critical(
                self.main_window,
                "Generation failed",
                "Could not start the model worker process.",
            )
            self._finish_copy_batch()
            return False
        return True

    def get_task_status_info_html(self) -> str:
        html = self._task_status_info_html
        in_cooldown = self._is_in_copy_cooldown()
        if (
            self._task_reference_paths
            or self._expand_source_path
            or self._expand_base_path
        ):
            show_elapsed = bool(self._expand_source_path or self._expand_base_path)
            elapsed = None
            if show_elapsed:
                elapsed = self._frozen_elapsed_seconds if in_cooldown else None
                if elapsed is None and self._step_progress_start_time is not None:
                    elapsed = time.perf_counter() - self._step_progress_start_time
            html, self._task_reference_paths = refresh_expand_task_status_html_for_display(
                html,
                elapsed_seconds=elapsed,
                source_path=self._expand_source_path,
                base_path=self._expand_base_path,
                reference_paths=self._task_reference_paths,
            )
        if in_cooldown:
            html = apply_cooldown_to_status_html(
                html,
                self._cooldown_seconds_remaining(),
                skip_icon_html=cooldown_skip_icon_html(),
            )
        if self._step_progress_start_time is not None and self._live_step_total > 0:
            if self._live_step > 0:
                html = self._apply_live_steps_progress(html)
            else:
                html = update_status_html_steps_progress(
                    html, 0, self._live_step_total
                )
        return html

    def _live_generation_elapsed_seconds(self) -> Optional[float]:
        start = self._step_progress_start_time
        if start is None:
            return None
        return time.perf_counter() - start

    @staticmethod
    def _estimate_remaining_seconds(
        *,
        elapsed: float,
        completed_steps: int,
        total_steps: int,
        seconds_per_step: Optional[float],
    ) -> Optional[float]:
        """(N-n)*a - (E-n*a) with frozen a; i.e. total_steps*a - elapsed."""
        if (
            completed_steps <= 0
            or total_steps <= 0
            or completed_steps >= total_steps
            or seconds_per_step is None
            or seconds_per_step <= 0
        ):
            return None
        return max(0.0, (total_steps * seconds_per_step) - elapsed)

    def _apply_live_steps_progress(self, html: str) -> str:
        if not html or self._live_step_total <= 0 or self._live_step <= 0:
            return html
        elapsed = self._live_generation_elapsed_seconds()
        if elapsed is None:
            return html
        estimate = self._estimate_remaining_seconds(
            elapsed=elapsed,
            completed_steps=self._live_step,
            total_steps=self._live_step_total,
            seconds_per_step=self._step_seconds_per_step,
        )
        self._live_elapsed_seconds = elapsed
        self._live_estimate_seconds = estimate
        return update_status_html_steps_progress(
            html,
            self._live_step,
            self._live_step_total,
            elapsed_seconds=elapsed,
            estimate_seconds=estimate,
        )

    def _is_in_copy_cooldown(self) -> bool:
        timer = self._cooldown_timer
        return timer is not None and timer.isActive()

    def _cooldown_seconds_remaining(self) -> int:
        deadline = self._cooldown_deadline
        if deadline is None:
            return 0
        return max(0, int(round(deadline - time.perf_counter())))

    def task_status_display_needs_refresh(self) -> bool:
        """False when only the cooldown countdown second is unchanged (timer polls)."""
        if not self._is_in_copy_cooldown():
            self._last_cooldown_ui_second = None
            return True
        remaining = self._cooldown_seconds_remaining()
        if remaining == self._last_cooldown_ui_second:
            return False
        self._last_cooldown_ui_second = remaining
        return True

    def skip_copy_cooldown(self) -> None:
        """End the inter-copy cooldown early and start the next generation."""
        if not self._is_in_copy_cooldown():
            return
        QTimer.singleShot(0, self._skip_copy_cooldown_deferred)

    def _skip_copy_cooldown_deferred(self) -> None:
        if not self._is_in_copy_cooldown():
            return
        self._stop_copy_cooldown_timer()
        self._on_copy_cooldown_elapsed()

    def active_series_remaining_after(self) -> int:
        """Images in the active batch still to run after the current cycle."""
        if not self._active_queue_job_id:
            return 0
        return max(0, self._copies_total - self._copies_done - 1)

    def can_add_active_series_cycle(self) -> bool:
        if not self._active_queue_job_id:
            return False
        max_after = _COPIES_MAX - self._copies_done - 1
        return self.active_series_remaining_after() < max_after

    def add_active_series_cycle(self) -> bool:
        """Add one more image to the active batch (same parameters)."""
        return self._adjust_active_series_remaining_after(1)

    def subtract_active_series_remaining(self) -> bool:
        """Remove one pending image from the active batch (minimum 0 remaining)."""
        return self._adjust_active_series_remaining_after(-1)

    def active_series_refinement_enabled(self) -> bool:
        return bool(self._pending_values.get("use_last_generated_image", False))

    def set_active_series_refinement(self, enabled: bool) -> bool:
        """Toggle whether remaining copies reuse the last generated image."""
        if not self._active_queue_job_id or self.active_series_remaining_after() <= 0:
            return False
        enabled = bool(enabled)
        if self.active_series_refinement_enabled() == enabled:
            return False
        self._pending_values["use_last_generated_image"] = enabled
        self.task_status_info_changed.emit()
        self.queue_changed.emit()
        return True

    def _adjust_active_series_remaining_after(self, delta: int) -> bool:
        if not self._active_queue_job_id or delta == 0:
            return False
        after = self.active_series_remaining_after()
        max_after = _COPIES_MAX - self._copies_done - 1
        new_after = max(0, min(max_after, after + delta))
        if new_after == after:
            return False
        self._set_active_series_remaining_after(new_after)
        return True

    def _set_active_series_remaining_after(self, after: int) -> None:
        after = max(0, min(_COPIES_MAX - self._copies_done - 1, int(after)))
        new_total = self._copies_done + 1 + after
        self._copies_total = new_total
        self._pending_values["copies"] = new_total
        self._copy_batch_active = new_total > 1
        self.task_status_info_changed.emit()
        self.queue_changed.emit()

    def _series_images_after_for_queue_display(self) -> int | None:
        """Images still to render after the current one in a multi-copy batch."""
        after = self.active_series_remaining_after()
        return after if after > 0 else None

    def _reset_live_queue_progress(self) -> None:
        self._live_step = 0
        self._live_step_total = 0
        self._live_elapsed_seconds = None
        self._live_estimate_seconds = None
        self._step_seconds_per_step = None

    def get_task_queue_status_info_html(self) -> str:
        """Active-job info table (job queue top row and status-bar dot menu)."""
        html = self.get_task_status_info_html()
        series_after = self._series_images_after_for_queue_display()
        if series_after and html:
            html = _append_table_rows(
                html,
                [
                    _table_row(
                        "Series:",
                        format_series_line_value(
                            _series_after_this_one_value(series_after),
                            self._pending_values,
                        ),
                    )
                ],
            )
        if html:
            return html
        plugin = self._active_plugin
        if plugin is None:
            return ""
        return format_image_generation_queue_status_html(
            plugin,
            self._pending_values,
            source_path=self._expand_source_path,
            base_path=self._expand_base_path,
            series_images_after=series_after,
        )

    def get_show_progressive_images_menu_state(self) -> Optional[tuple[bool, bool]]:
        """Return (supported, enabled) for the active image-generation task, or None."""
        plugin = self._active_plugin
        if plugin is None:
            return None
        if not get_pipeline(plugin.pipeline_id).supports_progressive_images:
            return None
        values = dict(self._pending_values)
        if "show_progressive_images" not in values:
            values.update(
                load_dialog_settings(
                    plugin.function, fallback_plugin_id=plugin.plugin_id
                )
            )
        return True, bool(values.get("show_progressive_images", False))

    def set_show_progressive_images(self, enabled: bool) -> None:
        """Persist show_progressive_images for the active function dialog."""
        plugin = self._active_plugin
        if plugin is None:
            return
        if not get_pipeline(plugin.pipeline_id).supports_progressive_images:
            return
        enabled = bool(enabled)
        self._pending_values["show_progressive_images"] = enabled
        saved = load_dialog_settings(
            plugin.function, fallback_plugin_id=plugin.plugin_id
        )
        saved["show_progressive_images"] = enabled
        save_dialog_settings(plugin.function, saved)
        if enabled and self._tasks.is_running() and self._output_path:
            self._refresh_progressive_image(self._output_path)

    def _show_progressive_images_enabled(self) -> bool:
        return bool(self._pending_values.get("show_progressive_images", False))

    def get_task_reference_paths(self) -> list[str]:
        return list(self._task_reference_paths)

    def open_task_reference_paths(self, paths: list[str]) -> None:
        existing = [p for p in paths if p and os.path.isfile(p)]
        if not existing or not hasattr(self.main_window, "refresh_from_configuration"):
            return
        self.main_window.refresh_from_configuration(
            {"files": existing, "sort_mode": "custom"}
        )

    def start_caption(
        self, file_path: str, user_prompt_override: str | None = None
    ) -> bool:
        if self.has_pending_work():
            return False
        self._task_status_info_html = format_caption_status_html(user_prompt_override)
        self.task_status_info_changed.emit()
        if not self._tasks.start_caption_job(file_path, user_prompt_override):
            self._task_status_info_html = ""
            return False
        return True

    def cancel_generation(self) -> None:
        """Cancel any in-flight generation or caption and terminate the worker."""
        if not self.is_running():
            return
        self._copy_batch_cancelled = True
        timer = self._cooldown_timer
        if timer is not None and timer.isActive():
            self._stop_copy_cooldown_timer()
            self._finish_copy_batch(cancelled=True)
            return
        self._tasks.cancel_task()

    def prepare_for_shutdown(self, *, suppress_failure_ui: bool = True) -> None:
        """Stop any in-flight task without confirmation or failure dialogs."""
        if suppress_failure_ui:
            self._suppress_task_failure_ui = True
        self._queue.clear()
        self.cancel_generation()

    def confirm_quit_if_running(self, parent=None) -> bool:
        """Return True if quit may proceed (not running, or user confirmed)."""
        if getattr(self.main_window, "_api_quit_in_progress", False):
            self.prepare_for_shutdown()
            return True
        if not self.has_pending_work():
            return True
        parent = parent or self.main_window
        answer = show_styled_question(
            parent,
            "AI task running",
            "Image generation, an AI caption, or queued jobs are active. Quit anyway?",
            default_no=True,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.prepare_for_shutdown()
        return True

    def cleanup(self) -> None:
        self._copy_batch_cancelled = True
        self._queue.clear()
        self._stop_copy_cooldown_timer()
        self._tasks.cleanup()
        self._finish_copy_batch(cancelled=True)

    def _on_caption_error(self, error_message: str) -> None:
        if self._suppress_task_failure_ui:
            return
        self.caption_error.emit(error_message)

    def _on_generation_started(self) -> None:
        self.generation_started.emit()

    def _on_task_started(self, _kind: str) -> None:
        self._sync_cancel_menu()

    def _on_job_processing_started(self, kind: str) -> None:
        if kind == "generate":
            if self._task_status_info_html:
                self._task_status_info_html = strip_cooldown_from_status_html(
                    self._task_status_info_html
                )
                if not (self._expand_source_path or self._expand_base_path):
                    self._task_status_info_html = remove_elapsed_row(
                        self._task_status_info_html
                    )
            self._step_progress_start_time = time.perf_counter()
            self._live_step = 0
            try:
                self._live_step_total = int(self._pending_values.get("steps") or 0)
            except (TypeError, ValueError):
                self._live_step_total = 0
            self._live_elapsed_seconds = None
            self._live_estimate_seconds = None
            self._step_seconds_per_step = None
            self._frozen_elapsed_seconds = None
            if self._live_step_total > 0 and self._task_status_info_html:
                self._task_status_info_html = update_status_html_steps_progress(
                    self._task_status_info_html,
                    0,
                    self._live_step_total,
                )
                self.task_status_info_changed.emit()
        self._update_status_bar_indicator(kind)

    def _on_task_finished(self, kind: str, _success: bool, _err: str) -> None:
        if kind == "caption":
            self.caption_finished.emit()
        if self._copy_batch_active or self._tasks.is_running():
            if self._copy_batch_active:
                self._sync_cancel_menu()
            return
        if not self._tasks.is_running():
            self._sync_cancel_menu()
            if not self._copy_batch_active:
                if not self._queue:
                    self._update_status_bar_indicator(None)
                    self._task_status_info_html = ""

    def _on_generation_finished(
        self, success: bool, output_path: str, error_message: str
    ) -> None:
        plugin = self._active_plugin
        values = self._pending_values
        if not output_path:
            output_path = self._output_path
        worker_result = self._tasks.pop_worker_result()
        if worker_result is None and not success:
            worker_result = parse_worker_stdout(self._tasks.stderr_text())

        if success and plugin and output_path:
            try:
                elapsed_seconds = resolve_generation_elapsed_seconds(
                    worker_result,
                    output_path,
                )
                used_seed = extract_used_seed_from_worker_result(
                    plugin.pipeline_id, worker_result
                )
                if used_seed is None and not values.get("random_seed"):
                    try:
                        used_seed = int(values.get("seed"))
                    except (TypeError, ValueError):
                        used_seed = None
                comment = format_image_exif_prompt(
                    plugin.menu_label(values),
                    values.get("prompt", ""),
                    iterations=values.get("steps"),
                    elapsed_seconds=elapsed_seconds,
                    seed=used_seed,
                    steps=values.get("steps"),
                    quantization=values.get("mflux_quantize"),
                    lora=lora_name_for_exif(values.get("mflux_lora")),
                    guidance=values.get("guidance_scale"),
                )
                ref_entries, allow_cross_dir = self._exif_reference_entries_for_output(
                    plugin, values, output_path
                )
                if get_pipeline(plugin.pipeline_id).requires_source_image:
                    source_paths = resolve_source_image_paths(values)
                    will_refine_next = (
                        self._copy_batch_active
                        and not self._copy_batch_cancelled
                        and bool(values.get("use_last_generated_image"))
                        and (self._copies_done + 1 < self._copies_total)
                    )
                    if ref_entries and not will_refine_next:
                        self._task_reference_paths = list(source_paths)
                write_exif_user_comment(
                    output_path,
                    comment,
                    reference_entries=ref_entries,
                    allow_cross_directory_references=allow_cross_dir,
                )
            except Exception:
                pass
            try:
                plugin.persist_reproducible_seed(values, worker_result)
            except Exception:
                pass
            QTimer.singleShot(0, lambda p=output_path: self._open_in_browse(p))
            self.generation_finished.emit(True, output_path, "")
            if plugin.pipeline_id == "mflux_fill_expand":
                remove_expand_base_temp(self._expand_base_path)
                self._expand_base_path = ""
            self._remove_aspect_pad_temps()
            self._copies_done += 1
            remaining = self._copies_total - self._copies_done
            if (
                remaining > 0
                and self._copy_batch_active
                and not self._copy_batch_cancelled
            ):
                if values.get("use_last_generated_image"):
                    if output_path and os.path.isfile(output_path):
                        self._pending_values = apply_refinement_source_for_next_copy(
                            self._pending_values, output_path
                        )
                        paths = resolve_source_image_paths(self._pending_values)
                        self._expand_source_path = paths[0] if paths else ""
                        self._task_reference_paths = list(paths)
                        self._active_thumbnail_paths = list(paths)
                        self.task_status_info_changed.emit()
                        self.queue_changed.emit()
                self._enter_copy_cooldown_after_success()
                return
            self._finish_copy_batch()
            return

        err = error_message or self._tasks.stderr_text() or "Generation failed."
        cancelled = error_message == "Cancelled" or self._copy_batch_cancelled
        if not cancelled:
            self._remove_partial_output()
        if cancelled:
            self._finish_copy_batch(cancelled=True)
            self.generation_finished.emit(False, output_path, err)
            return
        if not self._suppress_task_failure_ui:
            show_styled_critical(
                self.main_window,
                "Generation failed",
                err[:4000] if err else "Image generation failed.",
            )
        self.generation_finished.emit(False, output_path, err)
        self._finish_copy_batch()

    def _open_in_browse(self, output_path: str) -> None:
        self._refresh_progressive_image(output_path, force_fullscreen=True)

    def _exif_reference_entries_for_output(
        self,
        plugin: ImageGenModelPlugin,
        values: Dict[str, Any],
        output_path: str,
    ) -> tuple[Optional[list], bool]:
        ref_entries = None
        allow_cross_dir = False
        if plugin.pipeline_id == "mflux_fill_infill":
            from imagegen_plugins.pixelmator_export import resolve_infill_reference

            resolved = resolve_infill_reference(
                output_path,
                values.get("pixelmator_doc_name"),
                pixelmator_file_path=values.get("pixelmator_doc_path"),
            )
            if resolved is not None:
                ref_entries = [resolved]
                allow_cross_dir = True
        elif get_pipeline(plugin.pipeline_id).requires_source_image:
            source_paths = resolve_source_image_paths(values)
            ref_entries = reference_entries_for_source_paths(
                source_paths, output_path
            )
            if ref_entries:
                allow_cross_dir = True
        return ref_entries, allow_cross_dir

    def _on_generate_progress(self, msg: Dict[str, Any]) -> None:
        step = msg.get("step")
        step_total = msg.get("step_total")
        if step is not None and step_total is not None:
            step_i = int(step)
            total_i = int(step_total)
            if step_i > 0 and self._step_progress_start_time is not None:
                elapsed_seconds = self._live_generation_elapsed_seconds()
                if elapsed_seconds is not None:
                    self._step_seconds_per_step = elapsed_seconds / step_i
            self._live_step = step_i
            self._live_step_total = total_i
            self._task_status_info_html = self._apply_live_steps_progress(
                self._task_status_info_html
            )
            self.task_status_info_changed.emit()
        path = msg.get("path")
        if path and self._show_progressive_images_enabled():
            step_i = int(step) if step is not None else -1
            if step_i != 0:
                self._refresh_progressive_image(str(path))
            else:
                self._note_progressive_step_zero(str(path))

    def _note_progressive_step_zero(self, output_path: str) -> None:
        """Step 0 preview is empty or redundant; avoid a full browse refresh."""
        mw = self.main_window
        current = getattr(mw, "current_image_path", None)
        if (
            current
            and os.path.normpath(current) == os.path.normpath(output_path)
            and getattr(mw, "current_view_mode", None) == "browse"
        ):
            self._progressive_browse_opened = True
        if getattr(mw, "debug_mode", False):
            from debug_log import debug_timestamp

            print(
                f"{debug_timestamp()} [imagegen] skip progressive refresh "
                f"(step=0 path={output_path})",
                flush=True,
            )

    def _refresh_progressive_image(
        self, output_path: str, *, force_fullscreen: bool = False
    ) -> None:
        if not output_path or not os.path.isfile(output_path):
            return
        # Stepwise previews: match final Image Model / Prompt EXIF (skip last step).
        mw = self.main_window
        if not force_fullscreen:
            step = self._live_step
            total = self._live_step_total
            plugin = self._active_plugin
            values = self._pending_values
            if (
                step > 0
                and total > 0
                and step < total
                and plugin is not None
                and values
            ):
                try:
                    ref_entries, allow_cross_dir = (
                        self._exif_reference_entries_for_output(
                            plugin, values, output_path
                        )
                    )
                    elapsed = self._live_generation_elapsed_seconds()
                    estimate = None
                    if elapsed is not None:
                        estimate = self._estimate_remaining_seconds(
                            elapsed=elapsed,
                            completed_steps=step,
                            total_steps=total,
                            seconds_per_step=self._step_seconds_per_step,
                        )
                    make_readable_user_comment_before_browse(
                        output_path,
                        model_name=plugin.menu_label(values),
                        values=values,
                        elapsed_seconds=elapsed,
                        intermediate_step=step,
                        intermediate_total=total,
                        estimate_seconds=estimate,
                        reference_entries=ref_entries,
                        allow_cross_directory_references=allow_cross_dir,
                    )
                    current = getattr(mw, "current_image_path", None)
                    sidebar = getattr(mw, "right_sidebar", None)
                    if (
                        sidebar is not None
                        and current
                        and os.path.normpath(current)
                        == os.path.normpath(output_path)
                        and hasattr(sidebar, "show_image_info_overlay")
                    ):
                        sidebar.show_image_info_overlay()
                except Exception as e:
                    print(
                        "DEBUG make_readable_user_comment_before_browse: "
                        f"{e}"
                    )
        if hasattr(mw, "set_date_sort"):
            mw.set_date_sort(reverse=False, notify=False)
        if not hasattr(mw, "refresh_from_configuration"):
            return
        fullscreen = force_fullscreen or not self._progressive_browse_opened
        self._progressive_browse_opened = True
        mw.refresh_from_configuration(
            {"files": [output_path], "fullscreen": fullscreen},
            from_api=True,
        )

    def _remove_partial_output(self) -> None:
        path = self._output_path
        if path and os.path.isfile(path):
            try:
                if os.path.getsize(path) < 64:
                    os.remove(path)
            except OSError:
                pass

    def _enter_copy_cooldown_after_success(self) -> None:
        final_elapsed = self._live_elapsed_seconds
        if final_elapsed is None and self._step_progress_start_time is not None:
            final_elapsed = time.perf_counter() - self._step_progress_start_time
        final_step = self._live_step
        final_step_total = self._live_step_total
        self._frozen_elapsed_seconds = final_elapsed
        self._step_progress_start_time = None
        self._reset_live_queue_progress()
        if self._task_status_info_html and final_elapsed is not None:
            self._task_status_info_html = freeze_status_html_generation_elapsed(
                self._task_status_info_html,
                final_elapsed,
                step=final_step if final_step > 0 else None,
                step_total=final_step_total if final_step_total > 0 else None,
            )
        self.queue_changed.emit()
        self.task_status_info_changed.emit()
        self._schedule_copy_cooldown()

    def _stop_copy_cooldown_timer(self) -> None:
        timer = self._cooldown_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._cooldown_timer = None
        self._cooldown_deadline = None
        self._last_cooldown_ui_second = None

    def _schedule_copy_cooldown(self) -> None:
        self._stop_copy_cooldown_timer()
        self._sync_cancel_menu()
        self._update_status_bar_indicator("cooldown")
        self._cooldown_deadline = time.perf_counter() + (_COPY_COOLDOWN_MS / 1000.0)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_copy_cooldown_elapsed)
        self._cooldown_timer = timer
        timer.start(_COPY_COOLDOWN_MS)

    def _on_copy_cooldown_elapsed(self) -> None:
        self._cooldown_timer = None
        self._cooldown_deadline = None
        self._last_cooldown_ui_second = None
        if self._copy_batch_cancelled:
            self._finish_copy_batch(cancelled=True)
            return
        QTimer.singleShot(0, self._launch_next_copy_after_cooldown)

    def _launch_next_copy_after_cooldown(self) -> None:
        if not self._copy_batch_active or self._copy_batch_cancelled:
            return
        if self._tasks.is_running():
            return
        if not self._launch_generation_job():
            self._finish_copy_batch()

    def _remove_aspect_pad_temps(self) -> None:
        if self._aspect_pad_temp_paths:
            remove_edit_aspect_pad_temps(self._aspect_pad_temp_paths)
            self._aspect_pad_temp_paths = []

    def _cleanup_infill_batch_assets(self) -> None:
        plugin = self._active_plugin
        if plugin is None or plugin.pipeline_id != "mflux_fill_infill":
            return
        from imagegen_plugins.pixelmator_export import remove_persisted_pixelmator_batch

        remove_persisted_pixelmator_batch(self._pending_values)

    def _finish_copy_batch(self, *, cancelled: bool = False) -> None:
        self._stop_copy_cooldown_timer()
        self._remove_aspect_pad_temps()
        self._cleanup_infill_batch_assets()
        self._copy_batch_active = False
        self._copies_total = 0
        self._copies_done = 0
        self._copy_batch_cancelled = False
        self._active_queue_job_id = ""
        self._active_thumbnail_paths = []
        self._update_status_bar_indicator(None)
        self._reset_generation_state()
        self.queue_changed.emit()
        self._sync_cancel_menu()
        QTimer.singleShot(0, self._try_start_next_queued_job)

    def _try_start_next_queued_job(self) -> None:
        if self.is_running() or not self._queue:
            return
        job = self._queue.pop(0)
        self.queue_changed.emit()
        self._start_generation_now(
            job.plugin,
            job.values,
            job_id=job.job_id,
            status_html=job.status_html,
            thumbnail_paths=job.thumbnail_paths,
        )

    def _reset_generation_state(self) -> None:
        self._suppress_task_failure_ui = False
        self._active_plugin = None
        self._output_path = ""
        self._pending_values = {}
        self._progressive_browse_opened = False
        self._task_status_info_html = ""
        self._step_progress_start_time = None
        self._expand_source_path = ""
        self._expand_base_path = ""
        self._aspect_pad_temp_paths = []
        self._task_reference_paths = []
        self._live_step = 0
        self._live_step_total = 0
        self._live_elapsed_seconds = None
        self._live_estimate_seconds = None
        self._step_seconds_per_step = None
        self._frozen_elapsed_seconds = None
        self._cooldown_deadline = None
        self._last_cooldown_ui_second = None

    def _sync_cancel_menu(self) -> None:
        action = getattr(self.main_window, "imagegen_cancel_action", None)
        if action is not None:
            action.setEnabled(self.has_pending_work())

    def _update_status_bar_indicator(self, task_kind: str | None) -> None:
        mgr = getattr(self.main_window, "status_bar_manager", None)
        if mgr is None:
            return
        if task_kind in ("generate", "caption", "cooldown"):
            mgr.show_model_task_indicator(task_kind)
        else:
            mgr.hide_model_task_indicator()


def get_imagegen_controller(main_window) -> ImageGenController:
    ctrl = getattr(main_window, "_imagegen_controller", None)
    if ctrl is None:
        ctrl = ImageGenController(main_window)
        main_window._imagegen_controller = ctrl
    return ctrl
