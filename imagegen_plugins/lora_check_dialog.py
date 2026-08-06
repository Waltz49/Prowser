#!/usr/bin/env python3
"""Tools > Debug > Check LoRAs — progress UI and background worker."""

from __future__ import annotations

import html
import sys
import threading
import time
from dataclasses import replace
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import get_config
from imagegen_plugins.check_loras_debug import probe_elapsed_footer_lines
from imagegen_plugins.hf_model_ids import FLUX1_DEV, lora_model_display_name
from imagegen_plugins.lora_catalog import (
    LORA_CATALOG,
    get_lora_entry,
    lora_choice_label,
    lora_probe_history,
)
from imagegen_plugins.image_gen_persistence import (
    clear_lora_probe_history,
    save_lora_catalog_state,
)
from imagegen_plugins.lora_compatibility_checker import (
    CheckLorasOptions,
    LoraCheckChange,
    LoraCheckResult,
    LoraCheckStats,
    LoraProbeChoice,
    MODEL_SCOPE_ALL,
    MODEL_SCOPE_SELECTED,
    LORA_SCOPE_ALL,
    LORA_SCOPE_SELECTED,
    PreparedLoraProbePlan,
    REGISTRATION_IGNORE_PREVIOUS,
    REGISTRATION_ONLY_REGISTERED,
    REGISTRATION_SKIP_REGISTERED,
    check_loras_options_from_settings,
    discover_check_lora_choices,
    installed_probeable_models,
    lora_check_work_total,
    persist_check_loras_options,
    plan_disk_lora_probes,
    run_lora_compatibility_check,
)
from utils import (
    get_button_style,
    get_dialog_shell_stylesheet,
    show_styled_information,
    show_styled_question,
    show_styled_warning,
)

FLUX_LORA_CATALOG = LORA_CATALOG


class _LoraCheckWorkerBridge(QObject):
    progress_signal = Signal(int, int, str, str, str, object)
    finished_result = Signal(object)


class _LoraCheckUiRelay(QObject):
    """Main-thread receiver for worker signals (bare callables drop QueuedConnection)."""

    def __init__(self, on_progress, on_finished, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_progress = on_progress
        self._on_finished = on_finished

    @Slot(int, int, str, str, str, object)
    def handle_progress(
        self,
        probe_idx: int,
        probe_total: int,
        phase: str,
        lora_id: str,
        model_key: str,
        stats: object,
    ) -> None:
        self._on_progress(probe_idx, probe_total, phase, lora_id, model_key, stats)

    @Slot(object)
    def handle_finished(self, result: object) -> None:
        self._on_finished(result)


class LoraCheckWorkerThread:
    """Runs Check LoRAs on threading.Thread — keeps MLX off Qt's QThread."""

    def __init__(
        self,
        check_options: CheckLorasOptions,
        prepared_plan: PreparedLoraProbePlan,
        *,
        cancel_check,
    ) -> None:
        self._bridge = _LoraCheckWorkerBridge()
        self.progress_signal = self._bridge.progress_signal
        self.finished_result = self._bridge.finished_result
        self._check_options = check_options
        self._prepared_plan = prepared_plan
        self._cancel_check = cancel_check
        self._thread: threading.Thread | None = None
        self._result: object = None
        self._finished_posted = False

    def isRunning(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, msec: int = 300_000) -> bool:
        if self._thread is None:
            return True
        # Never join the current thread (DirectConnection finished slots used to).
        if threading.current_thread() is self._thread:
            return not self.isRunning()
        self._thread.join(timeout=max(0, msec) / 1000.0)
        return not self.isRunning()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="LoraCheckWorker",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        result = None
        try:
            if sys.platform == "darwin":
                try:
                    import multiprocessing as mp

                    mp.set_start_method("fork", force=True)
                except (RuntimeError, ValueError):
                    pass
            cfg = get_config().load_settings()

            def report(
                probe_idx: int,
                probe_total: int,
                phase: str,
                lora_id: str,
                model_key: str,
                stats: LoraCheckStats,
            ) -> None:
                # Snapshot stats: QueuedConnection delivers later; the worker
                # mutates the live object (e.g. pass → fail) before the UI runs.
                self._bridge.progress_signal.emit(
                    probe_idx,
                    probe_total,
                    phase,
                    lora_id,
                    model_key,
                    replace(stats),
                )

            try:
                result = run_lora_compatibility_check(
                    cfg,
                    progress_callback=report,
                    cancel_check=self._cancel_check,
                    options=self._check_options,
                    prepared=self._prepared_plan,
                )
            except Exception as e:
                print(f"[Check LoRAs] fatal error: {e}")
                import traceback

                traceback.print_exc()
                result = None
        except Exception as e:
            print(f"[Check LoRAs] worker thread error: {e}")
            import traceback

            traceback.print_exc()
            result = None
        finally:
            self._result = result
            self._finished_posted = True
            try:
                self._bridge.finished_result.emit(result)
            except Exception as emit_exc:
                print(f"[Check LoRAs] finished signal emit failed: {emit_exc}")


def _lora_label(lora_id: str, *, display_label: str = "") -> str:
    if display_label:
        return display_label
    entry = get_lora_entry(lora_id) or FLUX_LORA_CATALOG.get(lora_id)
    return lora_choice_label(entry) if entry else lora_id


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total >= 3600:
        return f"{total // 3600}h {(total % 3600) // 60}m"
    if total >= 60:
        return f"{total // 60}m {total % 60}s"
    return f"{total}s"


def _format_timing_line(elapsed: float, eta: Optional[float]) -> str:
    line = f"Elapsed: <b>{_format_duration(elapsed)}</b>"
    if eta is not None:
        line += f" · Est. remaining: <b>{_format_duration(eta)}</b>"
    return line


def _format_progress_html(
    phase: str,
    lora_id: str,
    model_key: str,
    stats: LoraCheckStats,
    *,
    elapsed: float = 0.0,
    eta: Optional[float] = None,
) -> str:
    lines: List[str] = []
    if elapsed > 0 or eta is not None:
        lines.append(_format_timing_line(elapsed, eta))
    if phase == "scan":
        lines.append("<b>Scanning LoRA weights (cache + top-level Downloads)…</b>")
        if stats.loras_total or stats.skipped_not_on_disk or stats.downloads_scanned:
            lines.append(
                f"To test: <b>{stats.loras_total}</b> · "
                f"Not on disk (skipped): {stats.skipped_not_on_disk} · "
                f"Installed models: <b>{stats.models_total}</b>"
            )
            if stats.files_discovered:
                lines.append(
                    f"Discovered: {stats.files_discovered} · "
                    f"MD5 deduped: {stats.files_deduped}"
                )
            if stats.skipped_unchanged:
                lines.append(
                    f"Unchanged (reuse history): <b>{stats.skipped_unchanged}</b>"
                )
            if stats.downloads_scanned:
                lines.append(
                    f"Downloads scanned: {stats.downloads_scanned} · "
                    f"Duplicates removed: {stats.downloads_deduped}"
                )
            lines.append(f"GPU renders planned: <b>{stats.probes_total}</b>")
            if stats.skipped_unchanged_probes:
                lines.append(
                    f"History reuse planned: <b>{stats.skipped_unchanged_probes}</b>"
                )
    elif phase == "downloads":
        lines.append("<b>Removing duplicate Downloads LoRAs…</b>")
        lines.append(
            f"Downloads scanned: {stats.downloads_scanned} · "
            f"Duplicates removed: <b>{stats.downloads_deduped}</b>"
        )
    else:
        display_label = stats.current_lora_label
        lora_label = html.escape(
            _lora_label(lora_id, display_label=display_label) if lora_id else "—"
        )
        model_label = (
            html.escape(lora_model_display_name(model_key)) if model_key else "—"
        )
        lora_pos = f"{stats.lora_index}/{max(1, stats.loras_total)}"
        model_pos = (
            f"{stats.model_index_for_lora}/{max(1, stats.models_for_lora)}"
            if stats.models_for_lora
            else "—"
        )
        current = int(stats.probe_current or stats.probes_done or 0)
        work_total = max(1, lora_check_work_total(stats))
        probe_pos = f"{current}/{work_total}"
        lines.append(
            f"Model <b>{model_pos}</b> · "
            f"LoRA <b>{lora_pos}</b> on this model · "
            f"Probe <b>{probe_pos}</b> "
            f"({stats.probes_done} finished)"
        )
        lines.append(f"Testing <b>{model_label}</b> with <b>{lora_label}</b>")
        if stats.last_result == "pass":
            lines.append("Last result: <span style='color:#1a7f37'>pass</span>")
        elif stats.last_result == "fail":
            lines.append("Last result: <span style='color:#c0392b'>fail</span>")
        elif stats.last_result == "skip":
            lines.append("Last result: <span style='color:#888'>skipped (registered)</span>")
        lines.append(
            f"Installed models in plan: {stats.models_total} · "
            f"Passed probes: {stats.passed_probe_count} · "
            f"Passed LoRAs: {stats.supported_loras} · "
            f"Newly enabled: {stats.newly_enabled_count} · "
            f"Failed probes: {stats.failed_probe_count}"
        )
        if stats.skipped_registered_probes:
            lines.append(
                f"Skipped registered pairs: {stats.skipped_registered_probes}"
            )
        if stats.skipped_unchanged_probes:
            lines.append(
                f"Skipped unchanged renders: {stats.skipped_unchanged_probes}"
            )
    return "".join(f'<p style="margin:0 0 0.35em 0">{line}</p>' for line in lines)


class CheckLorasOptionsDialog(QDialog):
    """Pre-scan options: model scope, LoRA scope, and registration filtering."""

    def __init__(
        self,
        parent,
        options: CheckLorasOptions,
        lora_choices: List[LoraProbeChoice],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check LoRAs — Options")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(520, 620)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

        self._installed_models = installed_probeable_models()
        self._lora_choices = list(lora_choices)
        self._model_checkboxes: dict[str, QCheckBox] = {}
        self._lora_checkboxes: dict[str, QCheckBox] = {}
        self._result_options: Optional[CheckLorasOptions] = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<b>Models</b>"))
        self._model_scope_group = QButtonGroup(self)
        self._all_models_radio = QRadioButton("All models")
        self._selected_models_radio = QRadioButton("Selected models")
        self._model_scope_group.addButton(self._all_models_radio)
        self._model_scope_group.addButton(self._selected_models_radio)
        layout.addWidget(self._all_models_radio)
        layout.addWidget(self._selected_models_radio)

        models_host = QWidget()
        models_layout = QVBoxLayout(models_host)
        models_layout.setContentsMargins(24, 0, 0, 0)
        models_layout.setSpacing(4)
        for model_key in self._installed_models:
            cb = QCheckBox(lora_model_display_name(model_key))
            cb.setChecked(model_key in options.selected_model_keys)
            self._model_checkboxes[model_key] = cb
            models_layout.addWidget(cb)
        layout.addWidget(models_host)

        layout.addWidget(QLabel("<b>LoRAs</b>"))
        self._lora_scope_group = QButtonGroup(self)
        self._all_loras_radio = QRadioButton("All discovered LoRAs")
        self._selected_loras_radio = QRadioButton("Selected LoRAs")
        self._lora_scope_group.addButton(self._all_loras_radio)
        self._lora_scope_group.addButton(self._selected_loras_radio)
        layout.addWidget(self._all_loras_radio)
        layout.addWidget(self._selected_loras_radio)

        lora_count = len(self._lora_choices)
        self._lora_count_label = QLabel(
            f"Found {lora_count} LoRA weight file{'s' if lora_count != 1 else ''} on disk."
        )
        self._lora_count_label.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(self._lora_count_label)

        loras_toolbar = QWidget()
        loras_toolbar_layout = QHBoxLayout(loras_toolbar)
        loras_toolbar_layout.setContentsMargins(24, 0, 0, 0)
        loras_toolbar_layout.setSpacing(8)
        self._select_all_loras_btn = QPushButton("Select all")
        self._clear_loras_btn = QPushButton("Clear all")
        self._select_all_loras_btn.clicked.connect(self._select_all_loras)
        self._clear_loras_btn.clicked.connect(self._clear_all_loras)
        loras_toolbar_layout.addWidget(self._select_all_loras_btn)
        loras_toolbar_layout.addWidget(self._clear_loras_btn)
        loras_toolbar_layout.addStretch(1)
        layout.addWidget(loras_toolbar)

        loras_host = QWidget()
        loras_layout = QVBoxLayout(loras_host)
        loras_layout.setContentsMargins(24, 0, 0, 0)
        loras_layout.setSpacing(4)
        saved_lora_keys = set(options.selected_lora_keys or [])
        for choice in self._lora_choices:
            cb = QCheckBox(choice.label)
            if choice.from_downloads:
                cb.setToolTip("Unregistered .safetensors (cache or Downloads)")
            if options.lora_scope == LORA_SCOPE_SELECTED and saved_lora_keys:
                cb.setChecked(choice.key in saved_lora_keys)
            else:
                cb.setChecked(True)
            self._lora_checkboxes[choice.key] = cb
            loras_layout.addWidget(cb)
        if not self._lora_choices:
            empty_label = QLabel("No LoRA weights found on disk.")
            empty_label.setContentsMargins(24, 0, 0, 0)
            loras_layout.addWidget(empty_label)

        loras_scroll = QScrollArea()
        loras_scroll.setWidget(loras_host)
        loras_scroll.setWidgetResizable(True)
        loras_scroll.setMaximumHeight(220)
        loras_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        layout.addWidget(loras_scroll)

        layout.addWidget(QLabel("<b>Registration</b>"))
        self._registration_group = QButtonGroup(self)
        self._skip_registered_radio = QRadioButton(
            "Skip registered model/LoRA combinations"
        )
        self._only_registered_radio = QRadioButton(
            "Only registered model/LoRA combinations"
        )
        self._ignore_previous_radio = QRadioButton("Ignore previous registrations")
        for radio in (
            self._skip_registered_radio,
            self._only_registered_radio,
            self._ignore_previous_radio,
        ):
            self._registration_group.addButton(radio)
            layout.addWidget(radio)

        if options.model_scope == MODEL_SCOPE_SELECTED:
            self._selected_models_radio.setChecked(True)
        else:
            self._all_models_radio.setChecked(True)

        if options.lora_scope == LORA_SCOPE_SELECTED and saved_lora_keys:
            self._selected_loras_radio.setChecked(True)
        else:
            self._all_loras_radio.setChecked(True)

        if options.registration_mode == REGISTRATION_SKIP_REGISTERED:
            self._skip_registered_radio.setChecked(True)
        elif options.registration_mode == REGISTRATION_ONLY_REGISTERED:
            self._only_registered_radio.setChecked(True)
        else:
            self._ignore_previous_radio.setChecked(True)

        layout.addWidget(QLabel("<b>Probe prompt</b>"))
        self._probe_prompt_edit = QLineEdit()
        self._probe_prompt_edit.setPlaceholderText("test")
        self._probe_prompt_edit.setText(options.probe_prompt or "test")
        layout.addWidget(self._probe_prompt_edit)
        probe_hint = QLabel(
            "Used for every probe render (baseline and each LoRA). "
            "All known triggers from the LoRAs in this run are gathered once "
            "and ensured in this prompt so every render uses the same text; "
            "you can also include triggers here yourself."
        )
        probe_hint.setWordWrap(True)
        layout.addWidget(probe_hint)

        self._skip_unchanged_checkbox = QCheckBox(
            "Re-probe changed files only (skip unchanged weights)"
        )
        self._skip_unchanged_checkbox.setChecked(bool(options.skip_unchanged))
        layout.addWidget(self._skip_unchanged_checkbox)

        self._all_models_radio.toggled.connect(self._on_model_scope_changed)
        self._selected_models_radio.toggled.connect(self._on_model_scope_changed)
        self._all_loras_radio.toggled.connect(self._on_lora_scope_changed)
        self._selected_loras_radio.toggled.connect(self._on_lora_scope_changed)
        self._on_model_scope_changed()
        self._on_lora_scope_changed()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        outer.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        self._clear_history_btn = QPushButton("Clear probe history")
        self._clear_history_btn.clicked.connect(self._on_clear_probe_history)
        footer.addWidget(self._clear_history_btn)
        footer.addStretch(1)
        outer.addLayout(footer)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _on_model_scope_changed(self, _checked: bool = False) -> None:
        selected = self._selected_models_radio.isChecked()
        for cb in self._model_checkboxes.values():
            cb.setEnabled(selected)

    def _on_lora_scope_changed(self, _checked: bool = False) -> None:
        selected = self._selected_loras_radio.isChecked()
        has_choices = bool(self._lora_checkboxes)
        for cb in self._lora_checkboxes.values():
            cb.setEnabled(selected and has_choices)
        self._select_all_loras_btn.setEnabled(selected and has_choices)
        self._clear_loras_btn.setEnabled(selected and has_choices)
        if not has_choices:
            self._all_loras_radio.setEnabled(False)
            self._selected_loras_radio.setEnabled(False)

    def _select_all_loras(self) -> None:
        for cb in self._lora_checkboxes.values():
            cb.setChecked(True)

    def _clear_all_loras(self) -> None:
        for cb in self._lora_checkboxes.values():
            cb.setChecked(False)

    def _on_clear_probe_history(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        count = len(lora_probe_history())
        if count == 0:
            show_styled_information(
                self,
                "Check LoRAs",
                "Probe history is already empty.",
            )
            return
        if show_styled_question(
            self,
            "Clear probe history",
            (
                f"Delete {count} cached probe result{'s' if count != 1 else ''}?\n\n"
                "The next Check LoRAs run will re-render all selected LoRAs "
                "(unless you skip unchanged weights and files match a new entry)."
            ),
            default_no=True,
        ) != QMessageBox.StandardButton.Yes:
            return
        removed = clear_lora_probe_history()
        show_styled_information(
            self,
            "Check LoRAs",
            (
                f"Cleared {removed} probe history entr"
                f"{'ies' if removed != 1 else 'y'}."
            ),
        )

    def _on_accept(self) -> None:
        if self._selected_models_radio.isChecked():
            selected = [
                key for key, cb in self._model_checkboxes.items() if cb.isChecked()
            ]
            if not selected:
                show_styled_warning(
                    self,
                    "Check LoRAs",
                    "Select at least one model, or choose All models.",
                )
                return
        else:
            selected = list(self._model_checkboxes.keys())

        if self._selected_loras_radio.isChecked():
            selected_lora_keys = [
                key for key, cb in self._lora_checkboxes.items() if cb.isChecked()
            ]
            if not selected_lora_keys:
                show_styled_warning(
                    self,
                    "Check LoRAs",
                    "Select at least one LoRA, or choose All discovered LoRAs.",
                )
                return
            lora_scope = LORA_SCOPE_SELECTED
        else:
            selected_lora_keys = list(self._lora_checkboxes.keys())
            lora_scope = LORA_SCOPE_ALL

        if self._skip_registered_radio.isChecked():
            registration_mode = REGISTRATION_SKIP_REGISTERED
        elif self._only_registered_radio.isChecked():
            registration_mode = REGISTRATION_ONLY_REGISTERED
        else:
            registration_mode = REGISTRATION_IGNORE_PREVIOUS

        scope = (
            MODEL_SCOPE_SELECTED
            if self._selected_models_radio.isChecked()
            else MODEL_SCOPE_ALL
        )
        probe_prompt = self._probe_prompt_edit.text().strip() or "test"
        self._result_options = CheckLorasOptions(
            model_scope=scope,
            selected_model_keys=selected,
            lora_scope=lora_scope,
            selected_lora_keys=selected_lora_keys,
            registration_mode=registration_mode,
            probe_prompt=probe_prompt,
            skip_unchanged=self._skip_unchanged_checkbox.isChecked(),
        )
        self.accept()

    def result_options(self) -> Optional[CheckLorasOptions]:
        return self._result_options


def _changes_of(result: LoraCheckResult, kind: str) -> List[LoraCheckChange]:
    return [c for c in result.changes if c.kind == kind]


def _format_results_text_sections(result: LoraCheckResult) -> List[str]:
    st = result.stats
    lines = [
        (
            "Check LoRAs cancelled (partial results saved)."
            if result.cancelled
            else "Check LoRAs finished."
        ),
        "",
        "Summary",
        f"  On-disk LoRAs tested: {st.loras_done}/{st.loras_total}",
        f"  Installed models: {st.models_total}",
        f"  GPU renders: {st.gpu_probes_done}/{st.probes_total}",
        f"  Passed probes this run: {st.passed_probe_count}",
        f"  LoRAs with at least one pass: {st.supported_loras}",
        f"  LoRAs with no pass: {st.removed_loras}",
        f"  Newly compatible pairs: {st.newly_supported_count}",
        f"  Newly enabled in Settings: {st.newly_enabled_count}",
        f"  Failed probes: {st.failed_probe_count}",
        f"  Skipped (not on disk): {st.skipped_not_on_disk}",
        f"  Skipped (hidden — not enabled): {st.skipped_hidden_count}",
    ]
    if st.skipped_registered_probes:
        lines.append(f"  Skipped (already registered): {st.skipped_registered_probes}")
    if st.files_discovered:
        lines.append(f"  Weight files discovered: {st.files_discovered}")
        lines.append(f"  MD5 duplicates skipped: {st.files_deduped}")
    if st.skipped_unchanged:
        lines.append(f"  Unchanged (history reused): {st.skipped_unchanged}")
    if st.skipped_unchanged_probes:
        lines.append(f"  Skipped unchanged renders: {st.skipped_unchanged_probes}")
    if st.downloads_scanned:
        lines.append(f"  Downloads scanned: {st.downloads_scanned}")
        lines.append(f"  Downloads duplicates removed: {st.downloads_deduped}")
        lines.append(f"  Downloads registered: {st.downloads_registered}")
        lines.append(f"  Downloads with no passing model: {st.downloads_failed}")
    if st.skipped_model_probes:
        lines.append(
            f"  Base models not installed (not probed): {st.skipped_model_probes}"
        )

    newly_enabled = _changes_of(result, "newly_enabled")
    newly_supported = _changes_of(result, "newly_supported")
    passed = _changes_of(result, "passed")
    failed = _changes_of(result, "failed")
    lost = _changes_of(result, "lost_support")
    hidden = _changes_of(result, "skipped_hidden")
    not_disk = _changes_of(result, "skipped_not_on_disk")
    downloads_registered = _changes_of(result, "downloads_registered")
    downloads_deduped = _changes_of(result, "downloads_deduped")
    downloads_failed = _changes_of(result, "downloads_failed")
    enabled_keys = {(c.lora_id, c.model_key) for c in newly_enabled}
    hidden_keys = {(c.lora_id, c.model_key) for c in hidden}
    compat_only = [
        c
        for c in newly_supported
        if (c.lora_id, c.model_key) not in enabled_keys
        and (c.lora_id, c.model_key) not in hidden_keys
    ]

    def add_section(
        title: str,
        items: List[LoraCheckChange],
        *,
        with_model: bool = True,
        limit: int = 250,
    ) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"{title} ({len(items)})")
        for c in items[:limit]:
            if with_model and c.model_label:
                lines.append(f"  • {c.model_label} → {c.lora_label}")
            else:
                lines.append(f"  • {c.lora_label}")
        if len(items) > limit:
            lines.append(f"  … and {len(items) - limit} more")

    add_section("Passed probes", passed)
    add_section("Newly enabled", newly_enabled)
    add_section("Downloads registered", downloads_registered)
    add_section("Newly compatible (not newly enabled)", compat_only)
    add_section("Failed probes", failed)
    add_section("Lost prior compatibility", lost)
    add_section("Passed but hidden (left disabled)", hidden)
    add_section("Downloads duplicates removed", downloads_deduped, with_model=False)
    add_section("Downloads with no passing model", downloads_failed, with_model=False)
    add_section("Skipped — weights not on disk", not_disk, with_model=False, limit=80)

    lines.extend(
        [
            "",
            "Each on-disk LoRA is probed against every installed base model. Passing "
            "pairs are recorded and enabled in Settings → LoRA (unless previously Hidden).",
            "Weights are discovered under ~/.cache/image_browser/mflux_loras, "
            "~/.cache/mflux_loras (recursive), and top-level ~/Downloads "
            "*.safetensors. Duplicate files (same md5) are probed once. "
            "Unchanged files reuse prior probe history.",
            "Re-run after downloading new LoRA weights. Use Hide in Settings to "
            "keep a LoRA out of the menus.",
        ]
    )
    lines.extend(probe_elapsed_footer_lines(result))
    return lines


def _show_cancelled_dialog(parent, *, partial: bool) -> None:
    lines = ["Check LoRAs was cancelled."]
    if partial:
        lines.extend(["", "Partial results from completed probes were saved."])
    else:
        lines.extend(["", "No probes were completed."])
    show_styled_information(
        parent,
        "Check LoRAs — Cancelled",
        "\n".join(lines),
    )


def _show_results_dialog(parent, result: LoraCheckResult) -> None:
    from imagegen_plugins.check_loras_debug import LAST_REPORT_PATHS

    text = "\n".join(_format_results_text_sections(result))
    if LAST_REPORT_PATHS:
        text = (
            "Report file(s):\n"
            + "\n".join(f"  {p}" for p in LAST_REPORT_PATHS)
            + "\n\n"
            + text
        )
    dlg = QDialog(parent)
    dlg.setWindowTitle("Check LoRAs — Results")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.resize(640, 520)
    dlg.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    intro = QLabel("Changes from this Check LoRAs run:")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    body = QPlainTextEdit()
    body.setReadOnly(True)
    body.setPlainText(text)
    layout.addWidget(body, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dlg.accept)
    layout.addWidget(buttons)
    dlg.exec()


def _apply_check_result(parent, result: LoraCheckResult) -> None:
    from imagegen_plugins.check_loras_debug import write_check_loras_report

    settings_before = get_config().load_settings()
    if result.model_support or result.by_model or result.probe_history:
        save_lora_catalog_state(
            model_support=result.model_support or None,
            by_model=result.by_model or None,
            probe_history=result.probe_history or None,
        )
    settings_after = get_config().load_settings()
    try:
        write_check_loras_report(
            result,
            settings_before=settings_before,
            settings_after=settings_after,
        )
    except OSError as exc:
        print(f"[Check LoRAs] Report write failed: {exc}")
    settings = settings_after
    mw = parent
    if hasattr(mw, "refresh_open_imagegen_lora_combos"):
        mw.refresh_open_imagegen_lora_combos()

    sd = getattr(mw, "settings_dialog", None)
    if sd is not None and getattr(sd, "isVisible", lambda: False)():
        from imagegen_plugins.lora_catalog_settings import enabled_lora_ids_for_model

        model_key = (
            sd._current_lora_model_key()
            if hasattr(sd, "_current_lora_model_key")
            else FLUX1_DEV
        )
        if hasattr(sd, "_rebuild_lora_settings_grid"):
            sd._rebuild_lora_settings_grid()
        if hasattr(sd, "_apply_lora_settings_to_widgets"):
            sd._apply_lora_settings_to_widgets(
                list(enabled_lora_ids_for_model(model_key, settings))
            )


def run_check_loras_dialog(parent) -> None:
    """Tools > Debug > Check LoRAs — probe LoRAs; enable and register where they pass."""
    if not installed_probeable_models():
        show_styled_warning(
            parent,
            "Check LoRAs",
            "No installed base models were found to probe LoRAs against.\n\n"
            "Install at least one image-generation base model, then run Check LoRAs again.",
        )
        return

    settings = get_config().load_settings()
    saved_options = check_loras_options_from_settings(settings)

    prescan_dialog = QProgressDialog(
        "Looking up on-disk LoRA files…",
        "",
        0,
        0,
        parent,
    )
    prescan_dialog.setWindowTitle("Check LoRAs — Preparing")
    prescan_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    prescan_dialog.setMinimumDuration(0)
    prescan_dialog.setCancelButton(None)
    prescan_dialog.setMinimumWidth(420)
    prescan_dialog.show()
    QApplication.processEvents()
    try:
        lora_choices = discover_check_lora_choices(settings, dedupe_downloads=False)
    except Exception as exc:
        prescan_dialog.close()
        print(f"[Check LoRAs] prescan error: {exc}")
        import traceback

        traceback.print_exc()
        show_styled_warning(
            parent,
            "Check LoRAs",
            "Could not scan LoRA weights on disk. See Tools > Debug > View log.",
        )
        return
    prescan_dialog.close()

    options_dlg = CheckLorasOptionsDialog(parent, saved_options, lora_choices)
    if options_dlg.exec() != QDialog.DialogCode.Accepted:
        return
    options = options_dlg.result_options()
    if options is None:
        return
    persist_check_loras_options(options)

    prepare_cancel: List[bool] = [False]
    prepare_dialog = QProgressDialog(
        "Discovering on-disk weights, hashing, and building probe plan…",
        "Cancel",
        0,
        0,
        parent,
    )
    prepare_dialog.setWindowTitle("Check LoRAs — Preparing")
    prepare_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    prepare_dialog.setMinimumDuration(0)
    prepare_dialog.setAutoClose(False)
    prepare_dialog.setAutoReset(False)
    prepare_dialog.setMinimumWidth(480)

    prepare_finished = [False]

    def on_prepare_user_cancel() -> None:
        if prepare_cancel[0]:
            return
        prepare_cancel[0] = True
        prepare_dialog.setLabelText(
            "Cancelling… (finishing current prepare step)"
        )
        # Close immediately so WindowModal cannot trap the UI while hashing.
        prepare_dialog.blockSignals(True)
        prepare_dialog.close()

    prepare_dialog.canceled.connect(on_prepare_user_cancel)
    prepare_dialog.show()
    QApplication.processEvents()

    class PrepareWorker(QThread):
        finished_prepare = Signal(object)

        def __init__(self, check_options: CheckLorasOptions) -> None:
            super().__init__()
            self._check_options = check_options

        def run(self) -> None:
            cfg = get_config().load_settings()
            try:
                candidates, plan, plan_stats = plan_disk_lora_probes(
                    cfg,
                    dedupe=True,
                    options=self._check_options,
                )
            except Exception as exc:
                print(f"[Check LoRAs] prepare error: {exc}")
                import traceback

                traceback.print_exc()
                self.finished_prepare.emit(None)
                return
            self.finished_prepare.emit(
                PreparedLoraProbePlan(
                    candidates=candidates,
                    plan=plan,
                    stats=plan_stats,
                )
            )

    def on_prepare_finished(payload: object) -> None:
        if prepare_finished[0]:
            return
        prepare_finished[0] = True
        try:
            prepare_dialog.canceled.disconnect(on_prepare_user_cancel)
        except (TypeError, RuntimeError):
            pass
        prepare_dialog.blockSignals(True)
        prepare_dialog.close()
        if prepare_cancel[0]:
            _show_cancelled_dialog(parent, partial=False)
            return
        if not isinstance(payload, PreparedLoraProbePlan):
            show_styled_warning(
                parent,
                "Check LoRAs",
                "Could not build probe plan. See Tools > Debug > View log.",
            )
            return
        _start_probe_run(parent, options, payload)

    prepare_worker = PrepareWorker(options)
    prepare_dialog._prepare_worker = prepare_worker  # type: ignore[attr-defined]
    prepare_worker.finished_prepare.connect(on_prepare_finished)
    prepare_worker.start()


class _LoraCheckProgressDialog(QDialog):
    """Progress UI with an always-visible scrollable pass log (not QProgressDialog)."""

    canceled = Signal()

    def __init__(self, parent, probes_total: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check LoRAs")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        self.resize(580, 420)
        self._closing = False
        self._cancel_requested = False
        # True when user dismissed UI before the worker finished (abandon apply).
        self.abandoned = False

        self.status_label = QLabel()
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(520)

        pass_heading = QLabel("Passed (registered or pending):")
        self.pass_list = QPlainTextEdit()
        self.pass_list.setReadOnly(True)
        self.pass_list.setMinimumHeight(120)
        self.pass_list.setMaximumHeight(180)
        self.pass_list.setPlaceholderText("Passes will appear here…")

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, int(probes_total)))
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v / %m")

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._request_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(self.status_label)
        layout.addWidget(pass_heading)
        layout.addWidget(self.pass_list, stretch=1)
        layout.addWidget(self.bar)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def set_status_html(self, html_text: str) -> None:
        if self._cancel_requested and not self._closing:
            self.status_label.setText(
                "<b>Cancelling…</b> (Cancel again to close now)<br/>" + html_text
            )
            return
        self.status_label.setText(html_text)

    def setMaximum(self, total: int) -> None:
        total = max(1, int(total))
        self.bar.setMaximum(total)
        if self.bar.value() > total:
            self.bar.setValue(total)

    def setValue(self, value: int) -> None:
        self.bar.setValue(max(0, min(int(value), self.bar.maximum())))

    def append_pass(self, line: str) -> None:
        self.pass_list.appendPlainText(line)
        self.pass_list.moveCursor(QTextCursor.MoveOperation.End)
        self.pass_list.ensureCursorVisible()

    def _request_cancel(self) -> None:
        if self._closing:
            return
        if self._cancel_requested:
            # Second Cancel: leave UI; worker is daemon and already cancelling.
            print("[Check LoRAs] Abandoning progress dialog (worker still winding down)")
            self.abandoned = True
            self.finish_and_close()
            return
        self._cancel_requested = True
        self._cancel_btn.setText("Close now")
        self.set_status_html(self.status_label.text())
        self.canceled.emit()

    def reject(self) -> None:
        # Must not call super().reject() here: Esc must cancel the run, not
        # dismiss a WindowModal dialog while the worker is still on GPU.
        self._request_cancel()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        self._request_cancel()
        if self._closing:
            event.accept()
        else:
            # First close request: keep dialog open with Cancelling… status.
            event.ignore()

    def finish_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.blockSignals(True)
        self.hide()
        self.close()


def _start_probe_run(
    parent,
    options: CheckLorasOptions,
    prepared: PreparedLoraProbePlan,
) -> None:
    existing = getattr(parent, "_lora_check_worker", None)
    if existing is not None and getattr(existing, "isRunning", lambda: False)():
        show_styled_warning(
            parent,
            "Check LoRAs",
            "A previous Check LoRAs run is still finishing.\n\n"
            "Wait a moment (or restart the app), then try again.",
        )
        return

    plan_stats = prepared.stats
    if not prepared.plan or (
        plan_stats.probes_total == 0
        and plan_stats.skipped_unchanged_probes == 0
        and plan_stats.skipped_unchanged == 0
    ):
        show_styled_information(
            parent,
            "Check LoRAs",
            "Nothing to probe with the current options.\n\n"
            f"Catalog candidates considered: {len(prepared.candidates)}\n"
            f"Skipped (not on disk): {plan_stats.skipped_not_on_disk}\n"
            f"Weight files discovered: {plan_stats.files_discovered}\n"
            f"Downloads scanned: {plan_stats.downloads_scanned}\n"
            f"Unchanged (history): {plan_stats.skipped_unchanged}\n"
            f"Models in plan: {plan_stats.models_total}\n"
            f"Probes planned: {plan_stats.probes_total} GPU · "
            f"{plan_stats.skipped_unchanged_probes} history\n\n"
            "Adjust options, download LoRA weights (or place .safetensors in "
            "cache or ~/Downloads), or install a base model, then try again.",
        )
        return

    probes_total = max(1, lora_check_work_total(plan_stats))
    start_time = time.monotonic()
    progress = _LoraCheckProgressDialog(parent, probes_total)
    progress.set_status_html(
        _format_progress_html("scan", "", "", plan_stats, elapsed=0.0)
    )
    progress.setValue(0)

    pass_lines_seen: set[tuple[str, str]] = set()

    def _append_pass_line(model_key: str, lora_label: str) -> None:
        label = (lora_label or "").strip() or "—"
        key = (model_key, label)
        if key in pass_lines_seen:
            return
        pass_lines_seen.add(key)
        model_name = lora_model_display_name(model_key) if model_key else "—"
        progress.append_pass(f"{model_name} → {label}")

    cancel_flag: List[bool] = [False]

    def on_probe_user_cancel() -> None:
        cancel_flag[0] = True

    progress.canceled.connect(on_probe_user_cancel)
    progress.show()
    QApplication.processEvents()

    def cancel_check() -> bool:
        return bool(cancel_flag[0])

    def on_progress(
        probe_idx: int,
        probe_total: int,
        phase: str,
        lora_id: str,
        model_key: str,
        stats_obj: object,
    ) -> None:
        stats = stats_obj if isinstance(stats_obj, LoraCheckStats) else LoraCheckStats()
        elapsed = time.monotonic() - start_time
        work_total = max(1, lora_check_work_total(stats))
        eta: Optional[float] = None
        if stats.probes_done > 0 and work_total > stats.probes_done:
            eta = elapsed / stats.probes_done * (work_total - stats.probes_done)
        progress.set_status_html(
            _format_progress_html(
                phase,
                lora_id,
                model_key,
                stats,
                elapsed=elapsed,
                eta=eta,
            )
        )
        if (
            phase == "probe"
            and stats.last_result == "pass"
            and model_key
        ):
            lora_label = stats.current_lora_label or _lora_label(lora_id)
            _append_pass_line(model_key, lora_label)
        total = max(1, probe_total)
        progress.setMaximum(total)
        if phase == "probe":
            # probe_current is 1-based in-flight index; probe_idx is completed count
            # before/after callbacks. Prefer finished count for the bar.
            current = max(0, int(stats.probes_done or 0))
            if stats.probe_current and stats.probes_done == 0:
                current = max(0, int(stats.probe_current) - 1)
            val = min(current, total)
        else:
            val = 0
        progress.setValue(val)
        # Do not processEvents here: progress runs via QueuedConnection on the
        # GUI thread; pumping events from the worker thread can hang Qt/MLX.

    finished_handled = [False]
    worker_dead_ticks = [0]

    def on_finished(result: object) -> None:
        if finished_handled[0]:
            return
        finished_handled[0] = True
        watchdog.stop()
        abandoned = bool(getattr(progress, "abandoned", False))
        try:
            progress.canceled.disconnect(on_probe_user_cancel)
        except (TypeError, RuntimeError):
            pass
        progress.finish_and_close()
        if getattr(parent, "_lora_check_worker", None) is worker:
            parent._lora_check_worker = None  # type: ignore[attr-defined]
        # Short join only — never block the GUI on a stuck MLX probe.
        worker.wait(500)
        if abandoned:
            print(
                "[Check LoRAs] Progress dialog abandoned; still applying "
                "partial results if any"
            )
            if isinstance(result, LoraCheckResult) and result.stats.probes_done > 0:
                _apply_check_result(parent, result)
            return
        if result is None:
            show_styled_warning(
                parent,
                "Check LoRAs",
                "Check failed with an error. See Tools > Debug > View log.",
            )
            return

        if not isinstance(result, LoraCheckResult):
            return

        if result.cancelled:
            _show_cancelled_dialog(
                parent,
                partial=result.stats.probes_done > 0,
            )
            if result.stats.probes_done == 0:
                return

        _apply_check_result(parent, result)
        _show_results_dialog(parent, result)

    def on_worker_watchdog() -> None:
        if finished_handled[0]:
            watchdog.stop()
            return
        if worker.isRunning():
            worker_dead_ticks[0] = 0
            return
        # Thread may exit before a QueuedConnection finished slot runs — wait.
        # Keep watching even if the dialog was force-closed.
        worker_dead_ticks[0] += 1
        if worker_dead_ticks[0] < 3:
            return
        print(
            "[Check LoRAs] worker thread exited while progress dialog still open"
            + (
                " (finished was posted; delivering stored result)"
                if worker._finished_posted
                else " (no finished post)"
            )
        )
        on_finished(worker._result)

    worker = LoraCheckWorkerThread(options, prepared, cancel_check=cancel_check)
    parent._lora_check_worker = worker  # type: ignore[attr-defined]
    progress._lora_check_worker = worker  # type: ignore[attr-defined]
    # Route through a main-thread QObject: QueuedConnection to bare callables is unreliable.
    ui_relay = _LoraCheckUiRelay(on_progress, on_finished, parent=progress)
    # Keep bridge alive with the dialog for the life of queued signals.
    worker._bridge.setParent(progress)
    worker.progress_signal.connect(
        ui_relay.handle_progress, Qt.ConnectionType.QueuedConnection
    )
    worker.finished_result.connect(
        ui_relay.handle_finished, Qt.ConnectionType.QueuedConnection
    )
    watchdog = QTimer(progress)
    watchdog.setInterval(2000)
    watchdog.timeout.connect(on_worker_watchdog)
    watchdog.start()
    worker.start()
    print("[Check LoRAs] worker started")
