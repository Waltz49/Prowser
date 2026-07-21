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
    make_readable_user_comment_before_browse,
    next_imagegen_path,
    apply_refinement_source_for_next_copy,
    reference_entries_for_source_paths,
    resolve_source_image_paths,
    source_paths_for_generation_exif,
    resolve_generation_elapsed_seconds,
    write_exif_user_comment,
)
from imagegen_plugins.generation_timing_stats import (
    build_generation_timing_key,
    lookup_average,
    record_run,
)
from imagegen_plugins.mflux_lora_presets import lora_name_for_exif_from_values
from imagegen_plugins.image_gen_persistence import (
    load_hold_job_queue,
    load_job_queue_records,
    load_show_progressive_images,
    save_hold_job_queue,
    save_job_queue_records,
    save_show_progressive_images,
    serialize_queued_job_record,
)
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.image_gen_seed_persistence import (
    extract_used_seed_from_worker_result,
    parse_worker_stdout,
)
from imagegen_plugins.model_task_queue import (
    QueuedGenerateJob,
    QueueRowSnapshot,
    apply_payload_model_fields_to_values,
    job_references_invalid,
    make_queued_generate_job,
    refresh_queued_job_status,
    restore_queued_generate_job,
    thumbnail_paths_for_values,
)
from imagegen_plugins.model_task_status_info import (
    apply_cooldown_to_status_html,
    cooldown_skip_icon_html,
    format_caption_status_html,
    format_image_generation_queue_status_html,
    freeze_status_html_generation_elapsed,
    refresh_expand_task_status_html_for_display,
    remove_elapsed_row,
    strip_cooldown_from_status_html,
    update_status_html_steps_progress,
)
from workers.model_tasks_controller import ModelTasksController, get_model_tasks_controller
from imagegen_plugins.image_gen_dialog import (
    prompt_enable_random_seed_for_copies,
    sync_random_seed_setting,
)
from utils import show_styled_critical, show_styled_question, styled_message_box

_COPIES_MIN = 1
_COPIES_MAX = 200
_CANCEL_PROCEED_NOTE = "Canceling..."
_REMOVE_PROCEED_NOTE = "Removing..."


class ImageGenController(QObject):
    """UI façade for model tasks (generation + caption) on one background worker."""

    generation_started = Signal()
    generation_finished = Signal(bool, str, str)  # success, output_path, error_message
    task_status_info_changed = Signal()
    queue_changed = Signal()
    hold_job_queue_changed = Signal()
    jobs_pane_title_changed = Signal()

    caption_chunk = Signal(str)
    caption_ready = Signal(str)
    caption_error = Signal(str)
    caption_finished = Signal()

    flux_prompt_chunk = Signal(str)
    flux_prompt_ready = Signal(str)
    flux_prompt_error = Signal(str)
    flux_prompt_finished = Signal()

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
        self._tasks.flux_prompt_chunk.connect(self._on_flux_prompt_chunk_from_worker)
        self._tasks.flux_prompt_ready.connect(self._on_flux_prompt_ready_from_worker)
        self._tasks.flux_prompt_error.connect(self._on_flux_prompt_error_from_worker)
        self._tasks.task_started.connect(self._on_task_started)
        self._tasks.job_processing_started.connect(self._on_job_processing_started)
        self._tasks.task_finished.connect(self._on_task_finished)

        # Second worker for text tasks (caption, flux prompt) while generation runs.
        self._foreground_tasks = ModelTasksController(self)
        self._foreground_tasks.caption_chunk.connect(self.caption_chunk.emit)
        self._foreground_tasks.caption_ready.connect(self.caption_ready.emit)
        self._foreground_tasks.caption_error.connect(self._on_caption_error)
        self._foreground_tasks.flux_prompt_chunk.connect(self.flux_prompt_chunk.emit)
        self._foreground_tasks.flux_prompt_ready.connect(self.flux_prompt_ready.emit)
        self._foreground_tasks.flux_prompt_error.connect(self._on_flux_prompt_error)
        self._foreground_tasks.task_finished.connect(self._on_foreground_task_finished)

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
        self._copy_cycle_plugin: Optional[ImageGenModelPlugin] = None
        self._copy_cycle_values: Dict[str, Any] = {}
        self._copy_cycle_reference_paths: list[str] = []
        self._copy_cycle_expand_source_path: str = ""
        self._suppress_task_failure_ui = False
        self._copies_total = 0
        self._copies_done = 0
        self._copy_batch_active = False
        self._copy_batch_cancelled = False
        self._skip_series_copy_requested = False
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
        self._generation_timing_key = None
        self._historical_avg_total_seconds: Optional[float] = None
        self._job_ai_stage_active = False
        self._active_job_with_ai = False
        self._job_ai_chars_received = 0
        self._job_ai_last_progress_bucket = -1
        self._hold_job_queue = load_hold_job_queue()
        self._queue_advance_suppressed = False
        self._quit_after_current_worker = False
        self._deferred_quit_wait_all_jobs = False
        self._deferred_quit_dialog = None
        self._deferred_quit_status_label = None
        self._deferred_quit_toggle_btn = None
        self._exit_queue_persisted = False
        self._queue_persist_suppressed = False
        self._queue_persist_timer = QTimer(self)
        self._queue_persist_timer.setSingleShot(True)
        self._queue_persist_timer.timeout.connect(self._persist_job_queue_now)
        self._restore_persisted_job_queue()

    def is_running(self) -> bool:
        if self._copy_batch_active and not self._copy_batch_cancelled:
            return True
        timer = self._cooldown_timer
        if timer is not None and timer.isActive():
            return True
        return self._tasks.is_running()

    def hold_job_queue(self) -> bool:
        return bool(self._hold_job_queue)

    def set_hold_job_queue(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._hold_job_queue:
            return
        self._hold_job_queue = enabled
        save_hold_job_queue(enabled)
        self.hold_job_queue_changed.emit()
        self._schedule_persist_job_queue()
        self._emit_jobs_pane_title_changed()
        if not enabled:
            self._resume_after_hold_released()

    def _resume_after_hold_released(self) -> None:
        if self._queue_advance_suppressed:
            return
        if (
            self._copy_batch_active
            and not self._copy_batch_cancelled
            and self._pending_batch_copies() > 0
            and not self._tasks.is_running()
            and not self._is_in_copy_cooldown()
        ):
            QTimer.singleShot(0, self._launch_next_copy_after_cooldown)
            return
        if not self.is_running():
            QTimer.singleShot(0, self._try_start_next_queued_job)

    def _generation_pipeline_idle(self) -> bool:
        return not self._tasks.is_running() and not self._is_in_copy_cooldown()

    def jobs_pane_title_suffix(self) -> str:
        """Title-bar suffix for hold / quiesce state, or '' when unheld."""
        if not self._hold_job_queue:
            return ""
        if self._active_queue_job_id and (
            self._tasks.is_running() or self._is_in_copy_cooldown()
        ):
            return " - Quiesce"
        return " - HOLD"

    def _emit_jobs_pane_title_changed(self) -> None:
        self.jobs_pane_title_changed.emit()

    def has_pending_work(self) -> bool:
        return bool(self._queue) or self.is_running()

    @property
    def active_queue_job_id(self) -> str:
        return self._active_queue_job_id

    def active_job_full_prompt(self) -> str:
        from imagegen_plugins.flux_prompt_job import effective_job_prompt_for_tooltip

        return effective_job_prompt_for_tooltip(self._pending_values)

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
                    references_invalid=job.references_invalid,
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
                if job.plugin is None:
                    return None
                return job.plugin, dict(job.values)
        return None

    def start_generation(
        self, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        values["copies"] = copies
        from imagegen_plugins.flux_prompt_job import strip_flux_prompt_ai_job_if_ui_inactive

        strip_flux_prompt_ai_job_if_ui_inactive(self._imagegen_submit_owner(), values)
        if copies > 1 and not values.get("random_seed"):
            if not prompt_enable_random_seed_for_copies(self.main_window):
                return False
            values["random_seed"] = True
            sync_random_seed_setting(self.main_window, True)

        if self.is_running():
            return self.enqueue_generation(plugin, values)

        if self._hold_job_queue and self._generation_pipeline_idle():
            return self.enqueue_generation(plugin, values)

        return self._start_generation_now(plugin, values)

    def _imagegen_submit_owner(self) -> Any | None:
        """Open image-gen dialog or active unified panel (for flux AI UI gating)."""
        dlg = getattr(self.main_window, "_imagegen_function_dialog", None)
        if dlg is None:
            return None
        panel = getattr(dlg, "_current_panel", None)
        return panel if panel is not None else dlg

    def enqueue_generation(
        self, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        values["copies"] = copies
        from imagegen_plugins.flux_prompt_job import strip_flux_prompt_ai_job_if_ui_inactive

        strip_flux_prompt_ai_job_if_ui_inactive(self._imagegen_submit_owner(), values)
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
        self._persist_job_queue_now()
        return True

    def is_queued_job_replaceable(self, job_id: str) -> bool:
        return bool(job_id) and self._queued_job_by_id(job_id) is not None

    def active_job_future_copies_updatable(self) -> int:
        """Batch copies not yet finished that can still pick up updated settings."""
        if not self._active_queue_job_id:
            return 0
        pending = self._pending_batch_copies()
        if pending <= 0:
            return 0
        if self._tasks.is_running():
            return max(0, pending - 1)
        return pending

    def is_active_job_remaining_updatable(self, job_id: str) -> bool:
        return (
            bool(job_id)
            and job_id == self._active_queue_job_id
            and self.active_job_future_copies_updatable() > 0
        )

    def update_active_job_remaining(
        self, job_id: str, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        """Update settings for pending copies in the active batch (not the in-flight copy)."""
        if not self.is_active_job_remaining_updatable(job_id):
            return False
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        in_progress = 1 if self._tasks.is_running() else 0
        min_total = self._copies_done + in_progress
        copies = max(min_total, copies)
        values["copies"] = copies
        future = copies - self._copies_done - in_progress
        if future > 1 and not values.get("random_seed"):
            if not prompt_enable_random_seed_for_copies(self.main_window):
                return False
            values["random_seed"] = True
            sync_random_seed_setting(self.main_window, True)
        self._active_plugin = plugin
        self._pending_values = values
        self._copies_total = copies
        self._copy_batch_active = copies > 1 or self._copies_done > 0
        self._active_thumbnail_paths = thumbnail_paths_for_values(plugin, values)
        self._task_status_info_html = self.get_task_queue_status_info_html()
        self.task_status_info_changed.emit()
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
        return True

    def replace_queued_job(
        self, job_id: str, plugin: ImageGenModelPlugin, values: Dict[str, Any]
    ) -> bool:
        """Update a pending queue entry in place (same job_id and position)."""
        from imagegen_plugins.flux_prompt_job import effective_job_prompt_for_tooltip

        job = self._queued_job_by_id(job_id)
        if job is None:
            return False
        copies = self._normalize_copies(values.get("copies", 1))
        values = dict(values)
        values["copies"] = copies
        if copies > 1 and not values.get("random_seed"):
            if not prompt_enable_random_seed_for_copies(self.main_window):
                return False
            values["random_seed"] = True
            sync_random_seed_setting(self.main_window, True)
        job.plugin = plugin
        job.plugin_id = plugin.plugin_id
        job.function = plugin.function
        job.plugin_unavailable = False
        job.values = values
        job.copies_total = copies
        job.thumbnail_paths = thumbnail_paths_for_values(plugin, values)
        job.full_prompt = effective_job_prompt_for_tooltip(values)
        job.references_invalid = job_references_invalid(plugin, values)
        refresh_queued_job_status(job)
        self.queue_changed.emit()
        self._sync_cancel_menu()
        self._schedule_persist_job_queue()
        return True

    def cancel_queued_job(self, job_id: str) -> None:
        before = len(self._queue)
        self._queue = [job for job in self._queue if job.job_id != job_id]
        if len(self._queue) != before:
            self.queue_changed.emit()
            self._sync_cancel_menu()
            self._schedule_persist_job_queue()

    def cancel_job_at_row(self, row: int) -> None:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return
        entry = rows[row]
        if entry.is_active:
            self.cancel_active_job()
        else:
            self.cancel_queued_job(entry.job_id)

    def cancel_jobs_from_row_and_subsequent(self, row: int) -> None:
        """Remove the queue row and every row after it (no confirmation)."""
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return
        if rows[row].is_active:
            self._queue.clear()
            self.queue_changed.emit()
            self._sync_cancel_menu()
            self._schedule_persist_job_queue()
            self.cancel_active_job()
            return
        queue_offset = 1 if rows[0].is_active else 0
        queue_index = row - queue_offset
        if queue_index < 0 or queue_index >= len(self._queue):
            return
        self._queue = self._queue[:queue_index]
        self.queue_changed.emit()
        self._sync_cancel_menu()
        self._schedule_persist_job_queue()

    def confirm_cancel_job_at_row(self, parent=None, row: int = -1) -> bool:
        """Confirm cancel/remove for a queue row; runs the action if user chooses Yes."""
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        entry = rows[row]
        if entry.is_active:
            prompt = "Cancel the running job?"
            proceed_note = _CANCEL_PROCEED_NOTE
        else:
            prompt = "Remove this job from the queue?"
            proceed_note = _REMOVE_PROCEED_NOTE
        parent = parent or self.main_window
        answer = show_styled_question(
            parent,
            "Cancel job?",
            prompt,
            default_no=True,
            proceed_note=proceed_note,
            on_proceed=lambda r=row: self.cancel_job_at_row(r),
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_cancel_generation(self, parent=None) -> bool:
        """Confirm cancel of the active generation/caption; runs cancel if user chooses Yes."""
        if not self.is_running():
            return False
        parent = parent or self.main_window
        answer = show_styled_question(
            parent,
            "Cancel job?",
            "Cancel the running job?",
            default_no=True,
            proceed_note=_CANCEL_PROCEED_NOTE,
            on_proceed=self.cancel_generation,
        )
        return answer == QMessageBox.StandardButton.Yes

    def cancel_active_job(self) -> None:
        self.cancel_generation()

    @staticmethod
    def _normalize_copies(raw: Any) -> int:
        try:
            copies = int(raw)
        except (TypeError, ValueError):
            copies = 1
        return max(_COPIES_MIN, min(_COPIES_MAX, copies))

    @staticmethod
    def _pipeline_supports_quantization(plugin: ImageGenModelPlugin) -> bool:
        return plugin.pipeline_reports_quantization()

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
        self._skip_series_copy_requested = False
        self._stop_copy_cooldown_timer()
        self._reset_active_job_progress_tracking()
        self._job_ai_stage_active = False
        self._active_job_with_ai = False
        self._task_status_info_html = ""

        self._active_plugin = plugin
        self._pending_values = values
        self._progressive_browse_opened = False

        if status_html:
            pass  # queue pane rebuilds compact HTML from live controller state

        self.queue_changed.emit()
        self.task_status_info_changed.emit()
        if self._pending_job_needs_ai_stage():
            return self._begin_job_ai_stage()
        return self._launch_generation_job()

    def _pending_job_needs_ai_stage(self) -> bool:
        from imagegen_plugins.flux_prompt_job import has_flux_prompt_ai_job

        return has_flux_prompt_ai_job(self._pending_values)

    def active_job_timing_steps_label(self) -> str:
        return "AI:" if self._job_ai_stage_active else "Steps:"

    def _start_job_ai_progress_tracking(self) -> None:
        from imagegen_plugins.model_task_status_info import _AI_REFINE_PROGRESS_TOTAL

        self._reset_active_job_progress_tracking()
        self._step_progress_start_time = time.perf_counter()
        self._live_step = 0
        self._live_step_total = _AI_REFINE_PROGRESS_TOTAL

    def _refresh_job_ai_stage_status_html(self, *, running: bool) -> None:
        from imagegen_plugins.model_task_status_info import (
            format_job_ai_stage_queue_status_html,
        )

        plugin = self._active_plugin
        if plugin is None:
            return
        elapsed, estimate = self._snapshot_live_timing(in_cooldown=False)
        if elapsed is None:
            elapsed = self._wall_clock_elapsed_seconds(in_cooldown=False)
        step = self._live_step if self._live_step_total > 0 else None
        step_total = self._live_step_total if self._live_step_total > 0 else None
        self._task_status_info_html = format_job_ai_stage_queue_status_html(
            plugin,
            self._pending_values,
            running=running,
            step=step,
            step_total=step_total,
            elapsed_seconds=elapsed,
            estimate_seconds=estimate,
        )
        self.task_status_info_changed.emit()

    def _begin_job_ai_stage(self) -> bool:
        from imagegen_plugins.flux_prompt_job import flux_prompt_ai_job_meta

        meta = flux_prompt_ai_job_meta(self._pending_values)
        plugin = self._active_plugin
        if meta is None or plugin is None:
            return self._launch_generation_job()

        self._job_ai_stage_active = True
        self._active_job_with_ai = True
        self._start_job_ai_progress_tracking()

        system_prompt = str(meta.get("system_prompt") or "")
        user_prompt = str(meta.get("user_prompt") or "")
        image_paths = list(meta.get("image_paths") or [])
        if image_paths:
            from imagegen_plugins.image_gen_naming import resolve_source_image_paths

            refreshed = [
                p
                for p in resolve_source_image_paths(self._pending_values)
                if p and os.path.isfile(p)
            ]
            if refreshed:
                image_paths = refreshed
        thumb_paths = [
            os.path.normpath(p)
            for p in image_paths
            if p and os.path.isfile(str(p))
        ]
        if thumb_paths:
            self._active_thumbnail_paths = list(thumb_paths)
        self._refresh_job_ai_stage_status_html(running=False)
        self.generation_started.emit()

        if not self._tasks.start_flux_prompt_job(
            system_prompt,
            user_prompt,
            image_paths=image_paths,
        ):
            self._fail_job_ai_stage("Could not start AI prompt refinement for the job.")
            return False
        return True

    def _complete_job_ai_stage(self, refined_prompt: str) -> None:
        from imagegen_plugins.model_task_status_info import (
            format_image_generation_queue_status_html,
        )

        self._job_ai_stage_active = False
        text = (refined_prompt or "").strip()
        if text:
            self._pending_values["prompt"] = text
        plugin = self._active_plugin
        if plugin is not None:
            try:
                from imagegen_plugins.model_task_queue import _preview_output_path

                preview_path = _preview_output_path()
                payload = plugin.build_payload(self._pending_values, preview_path)
                apply_payload_model_fields_to_values(
                    self._pending_values, payload, sync_prompt=False
                )
            except Exception:
                payload = None
            self._task_status_info_html = format_image_generation_queue_status_html(
                plugin,
                self._pending_values,
                payload,
                series_copies_total=self._copies_total if self._copies_total > 1 else None,
                with_ai=self._active_job_with_ai,
            )
            self.task_status_info_changed.emit()
        QTimer.singleShot(0, self._launch_generation_after_job_ai)

    def _launch_generation_after_job_ai(self) -> None:
        if self._active_plugin is None:
            self._finish_copy_batch()
            return
        if not self._launch_generation_job():
            self._finish_copy_batch()

    def _start_next_copy_cycle(self) -> bool:
        """Run AI prompt refinement (when configured) then the next generation copy."""
        if self._pending_job_needs_ai_stage():
            return self._begin_job_ai_stage()
        return self._launch_generation_job()

    def _fail_job_ai_stage(self, error_message: str) -> None:
        self._job_ai_stage_active = False
        if (
            not self._suppress_task_failure_ui
            and error_message
            and error_message != "Cancelled"
        ):
            show_styled_critical(
                self.main_window,
                "AI prompt job failed",
                error_message[:4000],
            )
        self.generation_finished.emit(False, "", error_message)
        self._finish_copy_batch(cancelled=True)

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
            canonical_from_payload = payload.pop("_canonical_source_image_paths", None)
            self._expand_base_path = ""
            if plugin.pipeline_id == "mflux_fill_expand":
                from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

                expand_values = dict(values)
                expand_values["max_generation_dimension"] = effective_max_for_plugin(
                    plugin
                )
                base_path = prepare_and_save_expand_base(expand_values, output_path)
                payload["prepared_fill_image_path"] = base_path
                self._expand_base_path = base_path
            elif plugin.pipeline_id == "mflux_fill_infill":
                from imagegen_plugins.pixelmator_export import (
                    missing_infill_export_paths,
                )

                missing_infill = missing_infill_export_paths(values)
                if missing_infill:
                    preview = "\n".join(f"• {p}" for p in missing_infill[:4])
                    show_styled_critical(
                        self.main_window,
                        "Infill",
                        "Infill base image or mask is missing on disk. "
                        "Paint a mask and generate again, or re-export from Pixelmator Pro.\n\n"
                        f"{preview}",
                    )
                    self._finish_copy_batch()
                    return False
            if get_pipeline(plugin.pipeline_id).requires_source_image:
                worker_source_paths = source_paths_for_generation_exif(payload)
                if isinstance(canonical_from_payload, list) and canonical_from_payload:
                    canonical_source_paths = source_paths_for_generation_exif(
                        {"source_image_paths": canonical_from_payload}
                    )
                else:
                    canonical_source_paths = source_paths_for_generation_exif(values)
                display_paths = canonical_source_paths or worker_source_paths
                if canonical_source_paths:
                    self._pending_values["_canonical_source_image_paths"] = list(
                        canonical_source_paths
                    )
                    self._pending_values["source_image_path"] = (
                        canonical_source_paths[0]
                    )
                    self._pending_values["source_image_paths"] = list(
                        canonical_source_paths
                    )
                if display_paths:
                    self._expand_source_path = display_paths[0]
                    self._task_reference_paths = list(display_paths)
                else:
                    self._expand_source_path = ""
                    self._task_reference_paths = []
            else:
                from imagegen_plugins.flux_prompt_job import (
                    flux_prompt_ai_reference_image_paths,
                )

                ai_ref_paths = flux_prompt_ai_reference_image_paths(values)
                if ai_ref_paths:
                    display_paths = source_paths_for_generation_exif(
                        values, extra_paths=ai_ref_paths
                    )
                    if display_paths:
                        self._expand_source_path = display_paths[0]
                        self._task_reference_paths = list(display_paths)
                    else:
                        self._expand_source_path = ""
                        self._task_reference_paths = []
                else:
                    self._expand_source_path = ""
                    self._task_reference_paths = []
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
        apply_payload_model_fields_to_values(
            self._pending_values, payload, sync_prompt=False
        )
        if self._copies_done == 0:
            from imagegen_plugins.model_task_status_info import (
                format_image_generation_queue_status_html,
            )

            self._task_status_info_html = format_image_generation_queue_status_html(
                plugin,
                values,
                payload,
                series_copies_total=self._copies_total if self._copies_total > 1 else None,
                with_ai=self._active_job_with_ai,
            )
            self.task_status_info_changed.emit()

        from config import get_config

        payload["debug_mode"] = bool(
            get_config().load_settings().get("debug_mode", False)
        )

        self._snapshot_copy_cycle_for_exif(plugin)
        if not self._tasks.start_generate_job(payload):
            show_styled_critical(
                self.main_window,
                "Generation failed",
                "Could not start the model worker process.",
            )
            self._finish_copy_batch()
            return False
        return True

    def _snapshot_copy_cycle_for_exif(self, plugin: ImageGenModelPlugin) -> None:
        """Freeze the settings for the in-flight copy (survives mid-run Update)."""
        self._copy_cycle_plugin = plugin
        self._copy_cycle_values = dict(self._pending_values)
        self._copy_cycle_reference_paths = list(self._task_reference_paths)
        self._copy_cycle_expand_source_path = self._expand_source_path

    def _clear_copy_cycle_exif_snapshot(self) -> None:
        self._copy_cycle_plugin = None
        self._copy_cycle_values = {}
        self._copy_cycle_reference_paths = []
        self._copy_cycle_expand_source_path = ""

    def _copy_cycle_exif_plugin(self) -> Optional[ImageGenModelPlugin]:
        if self._copy_cycle_plugin is not None:
            return self._copy_cycle_plugin
        return self._active_plugin

    def _copy_cycle_exif_values(self) -> Dict[str, Any]:
        if self._copy_cycle_values:
            return self._copy_cycle_values
        return self._pending_values

    def _live_generation_elapsed_seconds(self) -> Optional[float]:
        start = self._step_progress_start_time
        if start is None:
            return None
        return time.perf_counter() - start

    def _snapshot_live_timing(
        self, *, in_cooldown: bool = False
    ) -> tuple[Optional[float], Optional[float]]:
        """Elapsed and estimate from one clock read (kept in sync for display)."""
        if in_cooldown:
            elapsed = self._frozen_elapsed_seconds
            return (elapsed, None) if elapsed is not None else (None, None)
        elapsed = self._live_generation_elapsed_seconds()
        if elapsed is None:
            return None, None
        estimate = None
        if self._live_step > 0 and self._live_step_total > 0:
            estimate = self._estimate_remaining_seconds(
                elapsed=elapsed,
                completed_steps=self._live_step,
                total_steps=self._live_step_total,
                seconds_per_step=self._step_seconds_per_step,
            )
        elif (
            self._historical_avg_total_seconds is not None
            and self._historical_avg_total_seconds > 0
        ):
            estimate = max(0.0, self._historical_avg_total_seconds - elapsed)
        self._live_elapsed_seconds = elapsed
        self._live_estimate_seconds = estimate
        return elapsed, estimate

    def _wall_clock_elapsed_seconds(self, *, in_cooldown: bool) -> Optional[float]:
        """Elapsed since job processing started (before first step completes)."""
        if self._step_progress_start_time is None:
            return None
        if in_cooldown and self._frozen_elapsed_seconds is not None:
            return self._frozen_elapsed_seconds
        return time.perf_counter() - self._step_progress_start_time

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
        elapsed, estimate = self._snapshot_live_timing(
            in_cooldown=self._is_in_copy_cooldown()
        )
        if elapsed is None:
            return html
        return update_status_html_steps_progress(
            html,
            self._live_step,
            self._live_step_total,
            elapsed_seconds=elapsed,
            estimate_seconds=estimate,
        )

    def _copy_cooldown_ms(self) -> int:
        from config import get_config
        from imagegen_plugins.image_gen_dim_limits import app_series_cooldown_seconds

        return app_series_cooldown_seconds(get_config().load_settings()) * 1000

    def _is_in_copy_cooldown(self) -> bool:
        timer = self._cooldown_timer
        return timer is not None and timer.isActive()

    def _cooldown_seconds_remaining(self) -> int:
        deadline = self._cooldown_deadline
        if deadline is None:
            return 0
        return max(0, int(round(deadline - time.perf_counter())))

    def copy_cooldown_seconds_remaining(self) -> int:
        """Seconds left in inter-copy cooldown (0 when not cooling down)."""
        if not self._is_in_copy_cooldown():
            return 0
        return self._cooldown_seconds_remaining()

    def task_status_display_needs_refresh(self) -> bool:
        """False when only the cooldown countdown second is unchanged (timer polls)."""
        if not self._is_in_copy_cooldown():
            return True
        remaining = self._cooldown_seconds_remaining()
        return remaining != self._last_cooldown_ui_second

    def mark_task_status_display_refreshed(self) -> None:
        """Record cooldown countdown after all task-status UI consumers have updated."""
        if self._is_in_copy_cooldown():
            self._last_cooldown_ui_second = self._cooldown_seconds_remaining()
        else:
            self._last_cooldown_ui_second = None

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

    def can_skip_active_series_copy(self) -> bool:
        """True when an in-flight series copy may be ended early for the next copy."""
        if self._copies_total <= 1:
            return False
        if self.active_series_remaining_after() <= 0:
            return False
        if not self._tasks.is_running() or self._tasks.active_kind != "generate":
            return False
        if self._is_in_copy_cooldown():
            return False
        return True

    def skip_active_series_copy(self) -> None:
        """End the current series copy and advance to the next in the same job."""
        if not self.can_skip_active_series_copy():
            return
        self._skip_series_copy_requested = True
        self._tasks.cancel_task()

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
        return bool(self._pending_values.get("series_refinement", False))

    def set_active_series_refinement(self, enabled: bool) -> bool:
        """Toggle whether remaining copies replace the first source with each result."""
        if not self._active_queue_job_id or self.active_series_remaining_after() <= 0:
            return False
        enabled = bool(enabled)
        if self.active_series_refinement_enabled() == enabled:
            return False
        self._pending_values["series_refinement"] = enabled
        self.task_status_info_changed.emit()
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
        return True

    def _queued_job_by_id(self, job_id: str) -> QueuedGenerateJob | None:
        for job in self._queue:
            if job.job_id == job_id:
                return job
        return None

    def _resolve_plugin_for_record(
        self, plugin_id: str, function: str
    ) -> ImageGenModelPlugin | None:
        from imagegen_plugins import create_menu_plugins

        for plugin in create_menu_plugins():
            if plugin.plugin_id == plugin_id and plugin.function == function:
                return plugin
        return None

    def _restore_persisted_job_queue(self) -> None:
        records = load_job_queue_records()
        if not records:
            return
        restored: List[QueuedGenerateJob] = []
        for record in records:
            plugin = None
            plugin_unavailable = bool(record.get("plugin_unavailable"))
            if not plugin_unavailable:
                plugin = self._resolve_plugin_for_record(
                    record["plugin_id"], record["function"]
                )
                if plugin is None:
                    plugin_unavailable = True
            job = restore_queued_generate_job(
                job_id=record["job_id"],
                plugin=plugin,
                plugin_id=record["plugin_id"],
                function=record["function"],
                values=record["values"],
                copies_total=record["copies_total"],
                full_prompt=record.get("full_prompt") or "",
                plugin_unavailable=plugin_unavailable,
                skip_status_html=True,
            )
            restored.append(job)
        self._queue = restored
        if restored:
            self.queue_changed.emit()
            self._sync_cancel_menu()
            QTimer.singleShot(0, self._refresh_restored_job_status_html)
        if restored and not self._hold_job_queue:
            QTimer.singleShot(0, self._try_start_next_queued_job)

    def _refresh_restored_job_status_html(self) -> None:
        for job in self._queue:
            refresh_queued_job_status(job)
        if self._queue:
            self.queue_changed.emit()

    def _active_job_persist_record(self) -> dict | None:
        """Serializable queue head for the in-flight job (not stored in _queue)."""
        plugin = self._active_plugin
        if plugin is None or not self._active_queue_job_id:
            return None
        remaining = max(1, self._copies_total - self._copies_done)
        values = dict(self._pending_values)
        values["copies"] = remaining
        from imagegen_plugins.flux_prompt_job import effective_job_prompt_for_tooltip

        job = restore_queued_generate_job(
            job_id=self._active_queue_job_id,
            plugin=plugin,
            plugin_id=plugin.plugin_id,
            function=plugin.function,
            values=values,
            copies_total=remaining,
            full_prompt=effective_job_prompt_for_tooltip(values),
        )
        thumbs = list(self._active_thumbnail_paths) or list(job.thumbnail_paths)
        if thumbs:
            job.thumbnail_paths = thumbs
        return serialize_queued_job_record(job)

    def _job_queue_records_for_persist(self) -> list:
        """Pending queue plus active job snapshot (active first, same as shutdown fold)."""
        records: list = []
        active_id = self._active_queue_job_id or ""
        active_rec = self._active_job_persist_record()
        if active_rec is not None:
            records.append(active_rec)
        for job in self._queue:
            if job.job_id == active_id:
                continue
            records.append(serialize_queued_job_record(job))
        return records

    def _schedule_persist_job_queue(self) -> None:
        if self._queue_persist_suppressed:
            return
        self._queue_persist_timer.start(300)

    def _persist_job_queue_now(self) -> None:
        if self._queue_persist_suppressed:
            return
        self._queue_persist_timer.stop()
        save_job_queue_records(self._job_queue_records_for_persist())

    def _persist_job_queue_for_exit(self) -> None:
        """Persist queue snapshot once at shutdown; block later empty overwrites."""
        self._queue_persist_timer.stop()
        if self._exit_queue_persisted:
            return
        save_job_queue_records(self._job_queue_records_for_persist())
        self._exit_queue_persisted = True
        self._queue_persist_suppressed = True

    def series_remaining_after_for_row(self, row: int) -> int:
        """Pending images after the current one (active) or after the first (queued)."""
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return 0
        entry = rows[row]
        if entry.is_active:
            return self.active_series_remaining_after()
        job = self._queued_job_by_id(entry.job_id)
        if job is None:
            return 0
        return max(0, job.copies_total - 1)

    def can_add_series_cycle_for_row(self, row: int) -> bool:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        if rows[row].is_active:
            return self.can_add_active_series_cycle()
        job = self._queued_job_by_id(rows[row].job_id)
        return job is not None and job.copies_total < _COPIES_MAX

    def add_series_cycle_for_row(self, row: int) -> bool:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        if rows[row].is_active:
            return self.add_active_series_cycle()
        return self._adjust_queued_series_total(row, 1)

    def subtract_series_remaining_for_row(self, row: int) -> bool:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        if rows[row].is_active:
            return self.subtract_active_series_remaining()
        return self._adjust_queued_series_total(row, -1)

    def clear_active_series_remaining(self) -> bool:
        """Remove all pending images from the active batch after the current one."""
        if self.active_series_remaining_after() <= 0:
            return False
        self._set_active_series_remaining_after(0)
        return True

    def clear_series_remaining_for_row(self, row: int) -> bool:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        if rows[row].is_active:
            return self.clear_active_series_remaining()
        job = self._queued_job_by_id(rows[row].job_id)
        if job is None or job.copies_total <= 1:
            return False
        job.copies_total = 1
        job.values["copies"] = 1
        refresh_queued_job_status(job)
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
        return True

    def series_refinement_enabled_for_row(self, row: int) -> bool:
        record = self.job_record_for_row(row)
        if record is None:
            return False
        _, values = record
        return bool(values.get("series_refinement", False))

    def set_series_refinement_for_row(self, row: int, enabled: bool) -> bool:
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows):
            return False
        if rows[row].is_active:
            return self.set_active_series_refinement(enabled)
        if self.series_remaining_after_for_row(row) <= 0:
            return False
        job = self._queued_job_by_id(rows[row].job_id)
        if job is None:
            return False
        enabled = bool(enabled)
        if bool(job.values.get("series_refinement", False)) == enabled:
            return False
        job.values["series_refinement"] = enabled
        refresh_queued_job_status(job)
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
        return True

    def _adjust_queued_series_total(self, row: int, delta: int) -> bool:
        if delta == 0:
            return False
        rows = self.queue_snapshot()
        if row < 0 or row >= len(rows) or rows[row].is_active:
            return False
        job = self._queued_job_by_id(rows[row].job_id)
        if job is None:
            return False
        remaining = max(0, job.copies_total - 1)
        if delta > 0:
            if job.copies_total >= _COPIES_MAX:
                return False
            new_total = job.copies_total + 1
        else:
            if remaining <= 0:
                return False
            new_total = job.copies_total - 1
        if new_total == job.copies_total:
            return False
        job.copies_total = new_total
        job.values["copies"] = new_total
        refresh_queued_job_status(job)
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
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
        self._schedule_persist_job_queue()
        if self._is_in_copy_cooldown() and self._pending_batch_copies() <= 0:
            self._stop_copy_cooldown_timer()
            self._finish_copy_batch()

    def _reset_live_queue_progress(self) -> None:
        self._live_step = 0
        self._live_step_total = 0
        self._live_elapsed_seconds = None
        self._live_estimate_seconds = None
        self._step_seconds_per_step = None
        self._generation_timing_key = None
        self._historical_avg_total_seconds = None

    def _reset_active_job_progress_tracking(self) -> None:
        """Clear step/elapsed/timing used by progress bars (not copy-batch counters)."""
        self._reset_live_queue_progress()
        self._step_progress_start_time = None
        self._frozen_elapsed_seconds = None
        self._job_ai_chars_received = 0
        self._job_ai_last_progress_bucket = -1
        self._last_cooldown_ui_second = None

    def get_task_queue_status_info_html(self, *, omit_live_steps_row: bool = False) -> str:
        """Compact info table for the job queue pane and sidebar (rebuilt from live state)."""
        plugin = self._active_plugin
        if plugin is None:
            return ""

        if self._job_ai_stage_active:
            from imagegen_plugins.model_task_status_info import (
                format_job_ai_stage_queue_status_html,
            )

            elapsed, estimate = self._snapshot_live_timing(in_cooldown=False)
            if elapsed is None:
                elapsed = self._wall_clock_elapsed_seconds(in_cooldown=False)
            step = None
            step_total = None
            if not omit_live_steps_row and self._live_step_total > 0:
                step = self._live_step
                step_total = self._live_step_total
            return format_job_ai_stage_queue_status_html(
                plugin,
                self._pending_values,
                running=self._tasks.is_running(),
                step=step,
                step_total=step_total,
                elapsed_seconds=elapsed,
                estimate_seconds=estimate,
            )

        in_cooldown = self._is_in_copy_cooldown()
        elapsed, estimate = self._snapshot_live_timing(in_cooldown=in_cooldown)
        step = self._live_step if self._live_step_total > 0 else None
        step_total = self._live_step_total if self._live_step_total > 0 else None

        html = format_image_generation_queue_status_html(
            plugin,
            self._pending_values,
            source_path=self._expand_source_path,
            base_path=self._expand_base_path,
            step=step,
            step_total=step_total,
            elapsed_seconds=elapsed,
            estimate_seconds=estimate,
            running=self._tasks.is_running(),
            omit_live_steps_row=omit_live_steps_row,
            with_ai=self._active_job_with_ai,
        )
        if not html:
            return ""

        if (
            self._task_reference_paths
            or self._expand_source_path
            or self._expand_base_path
        ):
            show_elapsed = bool(self._expand_source_path or self._expand_base_path)
            expand_elapsed = None
            expand_estimate = None
            if show_elapsed:
                if elapsed is not None:
                    expand_elapsed = elapsed
                    expand_estimate = estimate
                else:
                    expand_elapsed = self._wall_clock_elapsed_seconds(
                        in_cooldown=in_cooldown
                    )
            html, self._task_reference_paths = refresh_expand_task_status_html_for_display(
                html,
                elapsed_seconds=expand_elapsed,
                estimate_seconds=expand_estimate,
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
        if (
            not omit_live_steps_row
            and self._step_progress_start_time is not None
            and self._live_step_total > 0
        ):
            display_elapsed = elapsed
            if display_elapsed is None:
                display_elapsed = self._wall_clock_elapsed_seconds(
                    in_cooldown=in_cooldown
                )
            html = update_status_html_steps_progress(
                html,
                self._live_step,
                self._live_step_total,
                elapsed_seconds=display_elapsed,
                estimate_seconds=estimate,
            )
        return html

    def get_show_progressive_images_menu_state(self) -> Optional[tuple[bool, bool]]:
        """Return (supported, enabled) for the active image-generation task, or None."""
        plugin = self._active_plugin
        if plugin is None:
            return None
        if not get_pipeline(plugin.pipeline_id).supports_progressive_images:
            return None
        return True, load_show_progressive_images()

    def set_show_progressive_images(self, enabled: bool) -> None:
        """Persist global show_progressive_images for supported pipelines."""
        plugin = self._active_plugin
        if plugin is None:
            return
        if not get_pipeline(plugin.pipeline_id).supports_progressive_images:
            return
        enabled = bool(enabled)
        save_show_progressive_images(enabled)
        self._pending_values["show_progressive_images"] = enabled
        if enabled and self._tasks.is_running() and self._output_path:
            self._refresh_progressive_image(self._output_path)

    def _show_progressive_images_enabled(self) -> bool:
        return load_show_progressive_images()

    def _active_generation_in_progress_or_cooldown(self) -> bool:
        return self._tasks.is_running() or (
            self._is_in_copy_cooldown() and self._copy_batch_active
        )

    def _paths_associated_with_active_generation(self) -> set[str]:
        """Output, expand source/base, and reference thumbnails for the active job."""
        paths: list[str] = []
        if self._output_path:
            paths.append(self._output_path)
        if self._expand_source_path:
            paths.append(self._expand_source_path)
        if self._expand_base_path:
            paths.append(self._expand_base_path)
        paths.extend(self._task_reference_paths)
        paths.extend(self._active_thumbnail_paths)
        out: set[str] = set()
        for p in paths:
            if p:
                out.add(os.path.normpath(p))
        return out

    def viewing_path_matches_active_generation(self, path: str) -> bool:
        """True when *path* is tied to the active job (output, sources, or cooldown)."""
        if not path or self._active_plugin is None:
            return False
        if not self._active_generation_in_progress_or_cooldown():
            return False
        associated = self._paths_associated_with_active_generation()
        if not associated:
            return False
        return os.path.normpath(path) in associated

    def snapshot_generation_timing_for_info_panel(
        self,
    ) -> tuple[Optional[float], Optional[float], Optional[int], Optional[int]]:
        """Elapsed, estimate, and step progress for File Information active-job box."""
        if not self._active_generation_in_progress_or_cooldown():
            return None, None, None, None
        if not self._tasks.is_running():
            return None, None, None, None
        in_cooldown = self._is_in_copy_cooldown()
        elapsed, estimate = self._snapshot_live_timing(in_cooldown=in_cooldown)
        if elapsed is None:
            elapsed = self._wall_clock_elapsed_seconds(in_cooldown=in_cooldown)
        step = self._live_step if self._live_step_total > 0 else None
        step_total = self._live_step_total if self._live_step_total > 0 else None
        return elapsed, estimate, step, step_total

    def snapshot_series_progress_for_active_job_strip(
        self,
    ) -> tuple[int, int] | None:
        """Completed and total images for the jobs-pane series progress bar."""
        if not self._copy_batch_active or self._copies_total <= 1:
            return None
        if not self._tasks.is_running() and not self._is_in_copy_cooldown():
            return None
        return self._copies_done, self._copies_total

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

    def start_caption_foreground(
        self, file_path: str, user_prompt_override: str | None = None
    ) -> bool:
        """Caption via a second worker while generation may be running."""
        if self._foreground_tasks.is_running():
            return False
        return self._foreground_tasks.start_caption_job(
            file_path, user_prompt_override
        )

    def is_foreground_caption_running(self) -> bool:
        return self._foreground_tasks.is_running()

    def cancel_caption(self) -> None:
        """Stop in-flight AI caption jobs without cancelling image generation."""
        if self._tasks.is_running() and self._tasks.active_kind == "caption":
            self._tasks.cancel_task()
        if (
            self._foreground_tasks.is_running()
            and self._foreground_tasks.active_kind == "caption"
        ):
            self._foreground_tasks.cancel_task()
        self._task_status_info_html = ""
        self.task_status_info_changed.emit()
        if self._tasks.is_running():
            self._update_status_bar_indicator(self._tasks.active_kind)
        else:
            self._update_status_bar_indicator(None)
        self._sync_cancel_menu()

    def cancel_flux_prompt_refine(self) -> None:
        """Stop dialog Gen Prompt refinement; never cancel a submitted job's AI stage."""
        if self._job_ai_stage_active:
            return
        if self._tasks.is_running() and self._tasks.active_kind == "flux_prompt":
            self._tasks.cancel_task()
        if (
            self._foreground_tasks.is_running()
            and self._foreground_tasks.active_kind == "flux_prompt"
        ):
            self._foreground_tasks.cancel_task()

    def start_flux_prompt_refine(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        image_paths: list[str] | None = None,
    ) -> bool:
        # IMPORTANT: Keep this background-worker path on the primary _tasks worker.
        # start_flux_prompt_refine_foreground covers concurrent use during generation,
        # but future AI refinement will increase job complexity (multi-step / chained
        # refinement) and must continue to use the main background text pipeline.
        if self.has_pending_work():
            return False
        if not self._tasks.start_flux_prompt_job(
            system_prompt,
            user_prompt,
            image_path=image_path,
            image_paths=image_paths,
        ):
            return False
        return True

    def start_flux_prompt_refine_foreground(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        image_paths: list[str] | None = None,
    ) -> bool:
        """Refine prompt via a second worker while generation may be running."""
        if self._foreground_tasks.is_running():
            return False
        return self._foreground_tasks.start_flux_prompt_job(
            system_prompt,
            user_prompt,
            image_path=image_path,
            image_paths=image_paths,
        )

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
        self._quit_after_current_worker = False
        self._deferred_quit_wait_all_jobs = False
        self._dismiss_deferred_quit_dialog()
        if suppress_failure_ui:
            self._suppress_task_failure_ui = True
        self._queue_advance_suppressed = True
        self._persist_job_queue_for_exit()
        self._abort_active_generation_for_shutdown()
        if self._foreground_tasks.is_running():
            self._foreground_tasks.cancel_task()

    def _abort_active_generation_for_shutdown(self) -> None:
        if not self.is_running():
            self._clear_active_generation_state()
            return
        self._copy_batch_cancelled = True
        timer = self._cooldown_timer
        if timer is not None and timer.isActive():
            self._stop_copy_cooldown_timer()
        self._tasks.cancel_task()
        self._clear_active_generation_state()

    def _clear_active_generation_state(self) -> None:
        self._remove_aspect_pad_temps()
        self._copy_batch_active = False
        self._copies_total = 0
        self._copies_done = 0
        self._copy_batch_cancelled = False
        self._skip_series_copy_requested = False
        self._active_queue_job_id = ""
        self._active_thumbnail_paths = []
        self._reset_generation_state()
        self._update_status_bar_indicator(None)

    def _quit_interrupts_active_worker(self) -> bool:
        """True when quitting would cancel an in-flight model worker task."""
        return self._tasks.is_running() or self._foreground_tasks.is_running()

    def _deferred_quit_status_message(self) -> str:
        if self._deferred_quit_wait_all_jobs:
            return "Prowser will shut down after all queued jobs finish."
        if self._copy_batch_active:
            return (
                "Prowser will shut down after the current copy completes.\n"
                "Existing jobs will be requeued on the next startup."
            )
        return "Prowser will shut down after the current task completes."

    def _deferred_quit_toggle_button_label(self) -> str:
        if self._deferred_quit_wait_all_jobs:
            return "Quit after current copy"
        return "Wait for all jobs"

    def _refresh_deferred_quit_dialog(self) -> None:
        label = self._deferred_quit_status_label
        if label is not None:
            label.setText(self._deferred_quit_status_message())
        toggle_btn = self._deferred_quit_toggle_btn
        if toggle_btn is not None:
            toggle_btn.setText(self._deferred_quit_toggle_button_label())

    def _show_deferred_quit_dialog(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
        from utils import get_button_style, get_dialog_shell_stylesheet

        self._dismiss_deferred_quit_dialog()
        parent = self.main_window
        dialog = QDialog(parent)
        dialog.setWindowTitle("Shutting down")
        dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(18)
        layout.setContentsMargins(22, 18, 22, 18)
        status_label = QLabel(self._deferred_quit_status_message())
        layout.addWidget(status_label)
        from imagegen_plugins.active_job_strip_widget import ActiveJobStripWidget

        progress_strip = ActiveJobStripWidget(
            self.main_window,
            dialog,
            pause_when_imagegen_dialog_building=False,
            layout_width_px=336,
        )
        layout.addWidget(progress_strip, 0, Qt.AlignmentFlag.AlignHCenter)
        button_row = QHBoxLayout()
        toggle_btn = QPushButton(self._deferred_quit_toggle_button_label())
        toggle_btn.clicked.connect(self._toggle_deferred_quit_mode)
        button_row.addWidget(toggle_btn)
        button_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(dialog.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)
        dialog.finished.connect(self._on_deferred_quit_dialog_finished)
        self._deferred_quit_dialog = dialog
        self._deferred_quit_status_label = status_label
        self._deferred_quit_toggle_btn = toggle_btn
        progress_strip.refresh(force=True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _dismiss_deferred_quit_dialog(self) -> None:
        dialog = self._deferred_quit_dialog
        if dialog is None:
            return
        self._deferred_quit_dialog = None
        self._deferred_quit_status_label = None
        self._deferred_quit_toggle_btn = None
        try:
            dialog.blockSignals(True)
            dialog.hide()
            dialog.deleteLater()
        except RuntimeError:
            pass

    def _on_deferred_quit_dialog_finished(self, _result: int) -> None:
        if self._deferred_quit_dialog is not None:
            self._deferred_quit_dialog = None
        self._deferred_quit_status_label = None
        self._deferred_quit_toggle_btn = None
        if not self._quit_after_current_worker:
            return
        self._quit_after_current_worker = False
        self._deferred_quit_wait_all_jobs = False
        self._queue_advance_suppressed = False

    def _resume_deferred_quit_queue_advance(self) -> None:
        if not self._quit_after_current_worker or not self._deferred_quit_wait_all_jobs:
            return
        if self._hold_job_queue:
            return
        if (
            self._copy_batch_active
            and not self._copy_batch_cancelled
            and self._pending_batch_copies() > 0
            and not self._tasks.is_running()
            and not self._is_in_copy_cooldown()
        ):
            QTimer.singleShot(0, self._launch_next_copy_after_cooldown)
            return
        if not self.is_running():
            QTimer.singleShot(0, self._try_start_next_queued_job)

    def _set_deferred_quit_wait_all_jobs(self) -> None:
        self._deferred_quit_wait_all_jobs = True
        self._queue_advance_suppressed = False
        self._exit_queue_persisted = False
        self._queue_persist_suppressed = False
        self._refresh_deferred_quit_dialog()
        QTimer.singleShot(0, self._resume_deferred_quit_queue_advance)

    def _try_complete_deferred_quit_after_current_copy(self) -> None:
        """If quit-after-current was requested and the active unit is done, shut down."""
        if not self._quit_after_current_worker:
            return
        if self._deferred_quit_wait_all_jobs:
            return
        if (
            self._job_ai_stage_active
            or self._tasks.is_running()
            or self._foreground_tasks.is_running()
            or self._is_in_copy_cooldown()
        ):
            if self._deferred_quit_dialog is None:
                self._show_deferred_quit_dialog()
            else:
                self._refresh_deferred_quit_dialog()
            return
        if self._copy_batch_active:
            self._finish_copy_batch()
        self._maybe_quit_after_current_worker()

    def _set_deferred_quit_after_current_copy(self) -> None:
        self._deferred_quit_wait_all_jobs = False
        self._queue_advance_suppressed = True
        self._persist_job_queue_for_exit()
        self._refresh_deferred_quit_dialog()
        self._try_complete_deferred_quit_after_current_copy()

    def _toggle_deferred_quit_mode(self) -> None:
        if self._deferred_quit_wait_all_jobs:
            self._set_deferred_quit_after_current_copy()
        else:
            self._set_deferred_quit_wait_all_jobs()

    def _begin_quit_after_current_worker(self) -> None:
        """Finish the in-flight copy or job, then quit (see _maybe_quit_after_current_worker)."""
        self._quit_after_current_worker = True
        self._deferred_quit_wait_all_jobs = False
        self._queue_advance_suppressed = True
        self._persist_job_queue_for_exit()
        QTimer.singleShot(0, self._try_complete_deferred_quit_after_current_copy)

    def _deferred_quit_pipeline_idle(self) -> bool:
        if self._job_ai_stage_active:
            return False
        if self._tasks.is_running() or self._foreground_tasks.is_running():
            return False
        return not self.has_pending_work()

    def _maybe_quit_after_current_worker(self) -> None:
        if not self._quit_after_current_worker:
            return
        if self._job_ai_stage_active:
            return
        if self._tasks.is_running() or self._foreground_tasks.is_running():
            # Worker job id is cleared after generation_finished / task_finished handlers.
            QTimer.singleShot(0, self._maybe_quit_after_current_worker)
            return
        if self._deferred_quit_wait_all_jobs:
            if not self._deferred_quit_pipeline_idle():
                return
        self._quit_after_current_worker = False
        self._deferred_quit_wait_all_jobs = False
        self._dismiss_deferred_quit_dialog()
        mw = self.main_window
        if mw is not None:
            QTimer.singleShot(0, mw.close)

    def _finish_current_unit_and_maybe_quit(self) -> bool:
        """End the active copy batch when deferred quit was requested."""
        if not self._quit_after_current_worker:
            return False
        if self._deferred_quit_wait_all_jobs:
            return False
        self._finish_copy_batch()
        self._maybe_quit_after_current_worker()
        return True

    def confirm_quit_if_running(self, parent=None) -> bool:
        """Return True if quit may proceed (not running, or user confirmed)."""
        if getattr(self.main_window, "_api_quit_in_progress", False):
            self.prepare_for_shutdown()
            return True
        if self._quit_after_current_worker:
            if self._quit_interrupts_active_worker():
                return False
            if self._deferred_quit_wait_all_jobs and not self._deferred_quit_pipeline_idle():
                return False
            return True
        if not self._quit_interrupts_active_worker():
            return True
        parent = parent or self.main_window
        from imagegen_plugins.active_job_strip_widget import ActiveJobStripWidget

        progress_strip = ActiveJobStripWidget(
            self.main_window,
            None,
            pause_when_imagegen_dialog_building=False,
        )
        msg_box = styled_message_box(
            parent,
            QMessageBox.Question,
            "AI task running",
            "Image generation or an AI caption is in progress.\nQuit anyway?",
            buttons=(
                QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Apply
            ),
            default_button=QMessageBox.StandardButton.No,
            button_label_overrides={
                QMessageBox.StandardButton.Yes: "Quit anyway",
                QMessageBox.StandardButton.Apply: "Wait and quit",
            },
            proceed_handlers={
                QMessageBox.StandardButton.Yes: (
                    _CANCEL_PROCEED_NOTE,
                    self.prepare_for_shutdown,
                ),
            },
            middle_widget=progress_strip,
        )
        progress_strip.refresh(force=True)
        msg_box.exec()
        answer = msg_box.result_data["button"]
        if answer == QMessageBox.StandardButton.Apply:
            self._begin_quit_after_current_worker()
            return False
        return answer == QMessageBox.StandardButton.Yes

    def cleanup(self) -> None:
        self._dismiss_deferred_quit_dialog()
        self._quit_after_current_worker = False
        self._deferred_quit_wait_all_jobs = False
        self._queue_advance_suppressed = True
        self._persist_job_queue_for_exit()
        self._copy_batch_cancelled = True
        self._stop_copy_cooldown_timer()
        self._tasks.cleanup()
        self._foreground_tasks.cleanup()
        self._queue.clear()
        self._active_queue_job_id = ""
        self._active_thumbnail_paths = []
        self._reset_generation_state()

    def _on_foreground_task_finished(self, kind: str, _success: bool, _err: str) -> None:
        if kind == "caption":
            self.caption_finished.emit()
        elif kind == "flux_prompt":
            self.flux_prompt_finished.emit()
        self._maybe_quit_after_current_worker()

    def _on_flux_prompt_chunk_from_worker(self, chunk: str) -> None:
        if self._job_ai_stage_active:
            from imagegen_plugins.model_task_status_info import (
                ai_refine_progress_bucket,
                ai_refine_progress_display_step,
                ai_refine_progress_step_from_chars,
            )

            self._job_ai_chars_received += len(chunk or "")
            raw_step = ai_refine_progress_step_from_chars(self._job_ai_chars_received)
            bucket = ai_refine_progress_bucket(raw_step)
            if bucket > self._job_ai_last_progress_bucket:
                self._job_ai_last_progress_bucket = bucket
                if self._live_step_total > 0:
                    self._live_step = ai_refine_progress_display_step(raw_step)
                self._refresh_job_ai_stage_status_html(running=True)
            return
        self.flux_prompt_chunk.emit(chunk)

    def _on_flux_prompt_ready_from_worker(self, text: str) -> None:
        if self._job_ai_stage_active:
            self._complete_job_ai_stage(text)
            return
        self.flux_prompt_ready.emit(text)

    def _on_flux_prompt_error_from_worker(self, error_message: str) -> None:
        if self._job_ai_stage_active:
            cancelled = error_message == "Cancelled" or self._copy_batch_cancelled
            if cancelled:
                self._fail_job_ai_stage("Cancelled")
            else:
                self._fail_job_ai_stage(error_message)
            return
        self._on_flux_prompt_error(error_message)

    def _on_caption_error(self, error_message: str) -> None:
        if self._suppress_task_failure_ui:
            return
        self.caption_error.emit(error_message)

    def _on_flux_prompt_error(self, error_message: str) -> None:
        if self._suppress_task_failure_ui:
            return
        self.flux_prompt_error.emit(error_message)

    def _on_generation_started(self) -> None:
        self.generation_started.emit()

    def _on_task_started(self, _kind: str) -> None:
        self._sync_cancel_menu()

    def _on_job_processing_started(self, kind: str) -> None:
        if kind == "flux_prompt" and self._job_ai_stage_active:
            self._refresh_job_ai_stage_status_html(running=True)
            self._update_status_bar_indicator(kind)
            return
        if kind == "generate":
            if self._task_status_info_html:
                self._task_status_info_html = strip_cooldown_from_status_html(
                    self._task_status_info_html
                )
                if not (self._expand_source_path or self._expand_base_path):
                    self._task_status_info_html = remove_elapsed_row(
                        self._task_status_info_html
                    )
            self._reset_active_job_progress_tracking()
            self._step_progress_start_time = time.perf_counter()
            plugin = self._active_plugin
            if plugin is not None:
                self._generation_timing_key = build_generation_timing_key(
                    plugin, self._pending_values
                )
                self._historical_avg_total_seconds = lookup_average(
                    self._generation_timing_key
                )
            try:
                self._live_step_total = int(self._pending_values.get("steps") or 0)
            except (TypeError, ValueError):
                self._live_step_total = 0
            if self._live_step_total > 0 and self._task_status_info_html:
                self._task_status_info_html = update_status_html_steps_progress(
                    self._task_status_info_html,
                    0,
                    self._live_step_total,
                )
                self.task_status_info_changed.emit()
        self._update_status_bar_indicator(kind)
        if kind == "generate" and self._hold_job_queue:
            self._emit_jobs_pane_title_changed()

    def _on_task_finished(self, kind: str, _success: bool, _err: str) -> None:
        if kind == "flux_prompt" and self._job_ai_stage_active:
            if not _success:
                cancelled = _err == "Cancelled" or self._copy_batch_cancelled
                if cancelled:
                    self._fail_job_ai_stage("Cancelled")
                else:
                    self._fail_job_ai_stage(_err or "AI prompt job failed")
            self._sync_cancel_menu()
            return
        if kind == "caption":
            self.caption_finished.emit()
        if kind == "flux_prompt":
            self.flux_prompt_finished.emit()
        if self._copy_batch_active or self._tasks.is_running():
            if self._copy_batch_active:
                self._sync_cancel_menu()
            if self._quit_after_current_worker:
                QTimer.singleShot(0, self._maybe_quit_after_current_worker)
            return
        if not self._tasks.is_running():
            self._sync_cancel_menu()
            if not self._copy_batch_active:
                if not self._queue:
                    self._update_status_bar_indicator(None)
                    self._task_status_info_html = ""
        self._maybe_quit_after_current_worker()

    def _on_generation_finished(
        self, success: bool, output_path: str, error_message: str
    ) -> None:
        plugin = self._copy_cycle_exif_plugin()
        values = self._copy_cycle_exif_values()
        if not output_path:
            output_path = self._output_path
        worker_result = self._tasks.pop_worker_result()
        if worker_result is None and not success:
            worker_result = parse_worker_stdout(self._tasks.stderr_text())

        if self._skip_series_copy_requested:
            self._skip_series_copy_requested = False
            self._remove_partial_output()
            if plugin and plugin.pipeline_id == "mflux_fill_expand":
                remove_expand_base_temp(self._expand_base_path)
                self._expand_base_path = ""
            self._remove_aspect_pad_temps()
            self._copies_done += 1
            self.generation_finished.emit(False, output_path, "")
            if self._finish_current_unit_and_maybe_quit():
                return
            remaining = self._copies_total - self._copies_done
            if (
                remaining > 0
                and self._copy_batch_active
                and not self._copy_batch_cancelled
            ):
                self._reset_active_job_progress_tracking()
                self.queue_changed.emit()
                self.task_status_info_changed.emit()
                self._schedule_persist_job_queue()
                self._emit_jobs_pane_title_changed()
                if self._hold_job_queue:
                    return
                QTimer.singleShot(0, self._launch_next_copy_after_cooldown)
                return
            self._finish_copy_batch()
            return

        if success and plugin and output_path:
            try:
                include_quantization = self._pipeline_supports_quantization(plugin)
                local_elapsed = self._live_elapsed_seconds
                if local_elapsed is None and self._step_progress_start_time is not None:
                    local_elapsed = (
                        time.perf_counter() - self._step_progress_start_time
                    )
                elapsed_seconds = resolve_generation_elapsed_seconds(
                    worker_result,
                    output_path,
                    local_elapsed=local_elapsed,
                )
                if elapsed_seconds and elapsed_seconds > 0:
                    timing_key = build_generation_timing_key(plugin, values)
                    if timing_key is not None:
                        record_run(timing_key, elapsed_seconds)
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
                    elapsed_seconds=elapsed_seconds,
                    seed=used_seed,
                    steps=values.get("steps"),
                    quantization=(
                        plugin.quantize_for_exif(values)
                        if include_quantization
                        else None
                    ),
                    lora=lora_name_for_exif_from_values(
                        values, pipeline_id=plugin.pipeline_id
                    ),
                    guidance=values.get("guidance_scale"),
                )
                ref_entries, allow_cross_dir = self._exif_reference_entries_for_output(
                    plugin,
                    values,
                    output_path,
                    fallback_source_paths=self._exif_fallback_source_paths(),
                )
                if get_pipeline(plugin.pipeline_id).requires_source_image:
                    will_refine_next = (
                        self._copy_batch_active
                        and not self._copy_batch_cancelled
                        and bool(values.get("series_refinement"))
                        and (self._copies_done + 1 < self._copies_total)
                    )
                    if ref_entries and not will_refine_next:
                        self._task_reference_paths = source_paths_for_generation_exif(
                            values
                        )
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
            if self._finish_current_unit_and_maybe_quit():
                return
            remaining = self._copies_total - self._copies_done
            if (
                remaining > 0
                and self._copy_batch_active
                and not self._copy_batch_cancelled
            ):
                if values.get("series_refinement"):
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
            self._repair_cancelled_output_exif_references(output_path)
            self._finish_copy_batch(cancelled=True)
            self.generation_finished.emit(False, output_path, err)
            self._maybe_quit_after_current_worker()
            return
        if not self._suppress_task_failure_ui:
            show_styled_critical(
                self.main_window,
                "Generation failed",
                err[:4000] if err else "Image generation failed.",
            )
        self.generation_finished.emit(False, output_path, err)
        self._finish_copy_batch()
        self._maybe_quit_after_current_worker()

    def _open_in_browse(self, output_path: str) -> None:
        self._refresh_progressive_image(output_path, force_fullscreen=True)

    def _repair_cancelled_output_exif_references(self, output_path: str) -> None:
        """Fix progressive-preview References when a job is cancelled mid-run."""
        plugin = self._copy_cycle_exif_plugin()
        if plugin is None or not output_path or not os.path.isfile(output_path):
            return
        try:
            from exif.exif_utils import decode_usercomment, get_usercomment_from_path

            raw = get_usercomment_from_path(output_path)
            if not raw:
                return
            comment = decode_usercomment(raw).strip()
            if not comment.startswith("Image Model:"):
                return
            ref_entries, allow_cross_dir = self._exif_reference_entries_for_output(
                plugin,
                self._copy_cycle_exif_values(),
                output_path,
                fallback_source_paths=self._exif_fallback_source_paths(),
            )
            if not ref_entries:
                return
            write_exif_user_comment(
                output_path,
                comment,
                reference_entries=ref_entries,
                allow_cross_directory_references=allow_cross_dir,
            )
        except Exception:
            pass

    def _exif_fallback_source_paths(self) -> List[str]:
        """Source paths captured at job launch when dialog values omit them."""
        values = self._copy_cycle_exif_values()
        canonical = values.get("_canonical_source_image_paths")
        if isinstance(canonical, list) and canonical:
            paths = source_paths_for_generation_exif(
                {"_canonical_source_image_paths": canonical}
            )
            if paths:
                return paths
        ref_paths = (
            self._copy_cycle_reference_paths
            if self._copy_cycle_values
            else self._task_reference_paths
        )
        expand_src = (
            self._copy_cycle_expand_source_path
            if self._copy_cycle_values
            else self._expand_source_path
        )
        paths: List[str] = []
        seen: set[str] = set()
        for raw in (*ref_paths, expand_src):
            ap = os.path.normpath(os.path.abspath(str(raw or "")))
            if ap and os.path.isfile(ap) and ap not in seen:
                seen.add(ap)
                paths.append(ap)
        return paths

    def _exif_reference_entries_for_output(
        self,
        plugin: ImageGenModelPlugin,
        values: Dict[str, Any],
        output_path: str,
        *,
        fallback_source_paths: Optional[List[str]] = None,
    ) -> tuple[Optional[list], bool]:
        ref_entries = None
        allow_cross_dir = False
        if plugin.pipeline_id == "mflux_fill_infill":
            from imagegen_plugins.pixelmator_export import resolve_infill_reference

            resolved = resolve_infill_reference(
                output_path,
                values.get("pixelmator_doc_name"),
                pixelmator_file_path=values.get("pixelmator_doc_path"),
                fallback_paths=fallback_source_paths,
            )
            if resolved is not None:
                ref_entries = [resolved]
                allow_cross_dir = True
        else:
            from imagegen_plugins.flux_prompt_job import (
                flux_prompt_ai_reference_image_paths,
            )

            extra_paths: List[str] = []
            if fallback_source_paths:
                extra_paths.extend(fallback_source_paths)
            extra_paths.extend(flux_prompt_ai_reference_image_paths(values))
            if not (
                get_pipeline(plugin.pipeline_id).requires_source_image
                or extra_paths
            ):
                return ref_entries, allow_cross_dir
            source_paths = source_paths_for_generation_exif(
                values, extra_paths=extra_paths or None
            )
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
            plugin = self._copy_cycle_exif_plugin()
            values = self._copy_cycle_exif_values()
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
                            plugin,
                            values,
                            output_path,
                            fallback_source_paths=self._exif_fallback_source_paths(),
                        )
                    )
                    elapsed = self._live_generation_elapsed_seconds()
                    make_readable_user_comment_before_browse(
                        output_path,
                        model_name=plugin.menu_label(values),
                        values=values,
                        elapsed_seconds=elapsed,
                        completed_step=step,
                        total_steps=total,
                        reference_entries=ref_entries,
                        allow_cross_directory_references=allow_cross_dir,
                        include_quantization=self._pipeline_supports_quantization(
                            plugin
                        ),
                        quantization=plugin.quantize_for_exif(values),
                    )
                    cache_manager = getattr(mw, 'cache_manager', None)
                    if cache_manager:
                        cache_manager.clear_cache_for_file(
                            output_path, metadata_fields={'exif'}
                        )
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
        if not path:
            return
        from prowser_temp_files import cleanup_cancelled_generation_output_artifacts

        cleanup_cancelled_generation_output_artifacts(path)
        if os.path.isfile(path):
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
        self._schedule_persist_job_queue()
        self._emit_jobs_pane_title_changed()

    def _pending_batch_copies(self) -> int:
        """Images in the active batch still to generate (including after cooldown)."""
        if not self._copy_batch_active or not self._active_queue_job_id:
            return 0
        return max(0, self._copies_total - self._copies_done)

    def _stop_copy_cooldown_timer(self) -> None:
        timer = self._cooldown_timer
        if timer is not None:
            try:
                timer.timeout.disconnect(self._on_copy_cooldown_elapsed)
            except (TypeError, RuntimeError):
                pass
            timer.stop()
            timer.deleteLater()
        self._cooldown_timer = None
        self._cooldown_deadline = None
        self._last_cooldown_ui_second = None

    def _schedule_copy_cooldown(self) -> None:
        self._stop_copy_cooldown_timer()
        self._sync_cancel_menu()
        cooldown_ms = self._copy_cooldown_ms()
        if cooldown_ms <= 0:
            QTimer.singleShot(0, self._on_copy_cooldown_elapsed)
            return
        self._update_status_bar_indicator("cooldown")
        self._cooldown_deadline = time.perf_counter() + (cooldown_ms / 1000.0)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_copy_cooldown_elapsed)
        self._cooldown_timer = timer
        timer.start(cooldown_ms)

    def _on_copy_cooldown_elapsed(self) -> None:
        self._cooldown_timer = None
        self._cooldown_deadline = None
        self._last_cooldown_ui_second = None
        if self._quit_after_current_worker and not self._deferred_quit_wait_all_jobs:
            self._finish_copy_batch()
            self._maybe_quit_after_current_worker()
            return
        if self._copy_batch_cancelled:
            self._finish_copy_batch(cancelled=True)
            return
        if self._pending_batch_copies() <= 0:
            self._finish_copy_batch()
            return
        if self._hold_job_queue:
            self.queue_changed.emit()
            self._schedule_persist_job_queue()
            self._emit_jobs_pane_title_changed()
            return
        QTimer.singleShot(0, self._launch_next_copy_after_cooldown)

    def _launch_next_copy_after_cooldown(self) -> None:
        if self._quit_after_current_worker and not self._deferred_quit_wait_all_jobs:
            self._finish_copy_batch()
            self._maybe_quit_after_current_worker()
            return
        if self._copy_batch_cancelled:
            return
        if self._hold_job_queue:
            return
        if self._pending_batch_copies() <= 0:
            self._finish_copy_batch()
            return
        if not self._copy_batch_active:
            self._finish_copy_batch()
            return
        if self._tasks.is_running():
            return
        if not self._start_next_copy_cycle():
            self._finish_copy_batch()

    def _remove_aspect_pad_temps(self) -> None:
        if self._aspect_pad_temp_paths:
            remove_edit_aspect_pad_temps(self._aspect_pad_temp_paths)
            self._aspect_pad_temp_paths = []

    def _cleanup_cancelled_generation_temps(self) -> None:
        from prowser_temp_files import (
            cleanup_cancelled_generation_output_artifacts,
            cleanup_stale_imagegen_worker_temps,
        )

        output_path = self._output_path
        if output_path:
            cleanup_cancelled_generation_output_artifacts(output_path)
        if self._expand_base_path:
            remove_expand_base_temp(self._expand_base_path)
        cleanup_stale_imagegen_worker_temps()

    def _cleanup_infill_batch_assets(self) -> None:
        plugin = self._active_plugin
        if plugin is None or plugin.pipeline_id != "mflux_fill_infill":
            return
        from imagegen_plugins.pixelmator_export import remove_persisted_pixelmator_batch

        remove_persisted_pixelmator_batch(self._pending_values)

    def _finish_copy_batch(self, *, cancelled: bool = False) -> None:
        from imagegen_plugins.flux_prompt_job import clear_flux_prompt_ai_job

        self._stop_copy_cooldown_timer()
        clear_flux_prompt_ai_job(self._pending_values)
        if cancelled:
            self._cleanup_cancelled_generation_temps()
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
        self._schedule_persist_job_queue()
        self._emit_jobs_pane_title_changed()
        if not self._hold_job_queue and not self._queue_advance_suppressed:
            QTimer.singleShot(0, self._try_start_next_queued_job)

    def _try_start_next_queued_job(self) -> None:
        if self._quit_after_current_worker and not self._deferred_quit_wait_all_jobs:
            self._maybe_quit_after_current_worker()
            return
        if self._queue_advance_suppressed or self._hold_job_queue:
            if self._quit_after_current_worker and self._deferred_quit_wait_all_jobs:
                self._maybe_quit_after_current_worker()
            return
        if self.is_running() or not self._queue:
            if (
                self._quit_after_current_worker
                and self._deferred_quit_wait_all_jobs
                and not self.is_running()
                and not self._queue
            ):
                self._maybe_quit_after_current_worker()
            return
        job = self._queue[0]
        if job.plugin_unavailable or job.plugin is None:
            show_styled_critical(
                self.main_window,
                "Job queue",
                f"The first queued job uses an unavailable model ({job.plugin_id}). "
                "Edit or remove it to continue.",
            )
            return
        if job.references_invalid:
            show_styled_critical(
                self.main_window,
                "Job queue",
                "The first queued job has missing reference files. "
                "Edit or remove it to continue.",
            )
            return
        job = self._queue.pop(0)
        self.queue_changed.emit()
        self._schedule_persist_job_queue()
        self._start_generation_now(
            job.plugin,
            job.values,
            job_id=job.job_id,
            status_html=job.status_html,
            thumbnail_paths=job.thumbnail_paths,
        )

    def _reset_generation_state(self) -> None:
        self._stop_copy_cooldown_timer()
        self._suppress_task_failure_ui = False
        self._job_ai_stage_active = False
        self._active_job_with_ai = False
        self._active_plugin = None
        self._output_path = ""
        self._pending_values = {}
        self._progressive_browse_opened = False
        self._task_status_info_html = ""
        self._expand_source_path = ""
        self._expand_base_path = ""
        self._aspect_pad_temp_paths = []
        self._task_reference_paths = []
        self._clear_copy_cycle_exif_snapshot()
        self._reset_active_job_progress_tracking()

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
