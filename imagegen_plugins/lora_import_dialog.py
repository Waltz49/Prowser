#!/usr/bin/env python3
"""Import or edit LoRA metadata; probe compatibility on import."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCursor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.hf_model_ids import lora_model_display_name
from imagegen_plugins.lora_compatibility_checker import (
    LoraProbeChoice,
    discover_find_lora_choices,
    probe_lora_on_model,
)
from imagegen_plugins.lora_model_registry import host_id_for_lora_model, klein_lora_model_aliases, lora_probe_model_is_local
from imagegen_plugins.lora_user_entries import (
    build_user_lora_entry,
    display_name_from_path,
    find_user_lora_for_source,
    validate_safetensors_source,
)
from theme.theme_service import get_active_theme
from utils import (
    apply_standard_dialog_layout,
    display_to_path,
    get_button_style,
    get_dialog_shell_stylesheet,
    normalize_path_for_display,
    show_styled_information,
    show_styled_warning,
)

_FORM_CONTROL_HEIGHT = 36
_DEFAULT_REFERENCE_PROMPT = "test image of person standing"
_IMPORT_PROBE_PROMPT_DISPLAY_MAX = 60
_IMPORT_PROGRESS_PROBE_STEPS = 6
_IMPORT_PROGRESS_SKIP_PROBE_STEPS = 3


def _probe_fallback_prompt(reference_prompt: str) -> str:
    return (reference_prompt or "test").strip() or "test"


def _resolve_browser_main_window(widget: Optional[QWidget]):
    """Find the image browser host from a settings/import dialog parent chain."""
    from imagegen_plugins.image_gen_source_nav import resolve_image_gen_main_window

    return resolve_image_gen_main_window(widget) if widget is not None else None


def _open_profile_temp_thumbnails(main_window) -> str:
    """Open profile tmp as a normal thumbnail level (ESC goes back), date newest-first."""
    from prowser_temp_files import ensure_temporary_files_directory
    from sort_mode import SortMode

    temp_dir = ensure_temporary_files_directory()
    mode = getattr(main_window, "current_view_mode", "")
    if mode in ("thumbnail", "browse", "list") and hasattr(main_window, "set_date_sort"):
        # Also converts list → thumbnail.
        main_window.set_date_sort(reverse=False, notify=False)
    else:
        # Slideshow/etc.: set sort for the upcoming load; load exits those modes.
        main_window.current_sort_mode = SortMode.DATE
        main_window.is_reversed = False
        sorting_manager = getattr(main_window, "sorting_manager", None)
        if sorting_manager is not None and hasattr(sorting_manager, "save_sorting_settings"):
            sorting_manager.save_sorting_settings()
        if hasattr(main_window, "update_sort_menu_checkmarks"):
            main_window.update_sort_menu_checkmarks()
    fth = getattr(main_window, "file_tree_handler", None)
    if fth is not None and hasattr(fth, "request_directory_opening"):
        fth.request_directory_opening(temp_dir)
    elif hasattr(main_window, "open_directory"):
        main_window.open_directory(temp_dir)
    return temp_dir


def _highlight_newest_thumbnail(main_window) -> None:
    """Highlight the first displayed image (newest when date-sorted newest-first)."""
    displayed = []
    if hasattr(main_window, "get_displayed_images"):
        displayed = main_window.get_displayed_images() or []
    if not displayed:
        return
    newest = displayed[0]
    if hasattr(main_window, "set_current_image_by_path"):
        main_window.set_current_image_by_path(newest, fallback_index=0)
    if hasattr(main_window, "highlight_image"):
        main_window.highlight_image()


def _refresh_temp_and_highlight_newest(main_window) -> None:
    """If still viewing profile tmp, refresh and highlight the newest thumbnail."""
    from prowser_temp_files import resolve_temporary_files_directory

    current = os.path.normpath(getattr(main_window, "current_directory", "") or "")
    temp_dir = os.path.normpath(resolve_temporary_files_directory())
    if not current or current != temp_dir:
        return
    if hasattr(main_window, "refresh_directory"):
        main_window.refresh_directory(force=True)
    _highlight_newest_thumbnail(main_window)


def _format_import_progress_html(
    *,
    model_key: str,
    lora_name: str,
    activity: str,
    probe_prompt: str = "",
) -> str:
    lines = [
        f"Model: <b>{html.escape(lora_model_display_name(model_key))}</b>",
        f"LoRA: <b>{html.escape((lora_name or '').strip() or '—')}</b>",
    ]
    prompt = (probe_prompt or "").strip()
    if prompt:
        if len(prompt) <= _IMPORT_PROBE_PROMPT_DISPLAY_MAX:
            prompt_display = prompt
        else:
            prompt_display = prompt[:_IMPORT_PROBE_PROMPT_DISPLAY_MAX] + "…"
        lines.append(f"Prompt: {html.escape(prompt_display)}")
    if activity:
        lines.append(f"<b>{html.escape(activity)}</b>")
    return "<br/>".join(lines)


class _LoraImportProgressDialog(QDialog):
    """Granular progress for Test & Add (mirrors Check LoRAs status + bar)."""

    canceled = Signal()

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        model_key: str,
        lora_name: str,
        probe_prompt: str,
        maximum: int,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add LoRA")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        self.resize(520, 180)
        self._model_key = model_key
        self._lora_name = lora_name
        self._probe_prompt = probe_prompt
        self._cancel_requested = False
        self._closing = False
        self._last_activity = "Starting…"

        self.status_label = QLabel()
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(480)

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, int(maximum)))
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v / %m")

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._request_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(self.status_label)
        layout.addWidget(self.bar)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)
        self.update_progress("Starting…", 0, maximum)

    def update_progress(
        self,
        activity: str,
        value: int,
        maximum: Optional[int] = None,
    ) -> None:
        self._last_activity = (activity or "").strip() or self._last_activity
        if maximum is not None:
            self.bar.setMaximum(max(1, int(maximum)))
        val = max(0, min(int(value), self.bar.maximum()))
        self.bar.setValue(val)
        prefix = ""
        if self._cancel_requested and not self._closing:
            prefix = "<b>Cancelling…</b><br/>"
        body = _format_import_progress_html(
            model_key=self._model_key,
            lora_name=self._lora_name,
            activity=self._last_activity,
            probe_prompt=self._probe_prompt,
        )
        self.status_label.setText(prefix + body)

    def _request_cancel(self) -> None:
        if self._closing:
            return
        if self._cancel_requested:
            self.finish_and_close()
            return
        self._cancel_requested = True
        self._cancel_btn.setText("Close now")
        self.update_progress(self._last_activity, self.bar.value())
        self.canceled.emit()

    def reject(self) -> None:  # noqa: N802
        self._request_cancel()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        self._request_cancel()
        if self._closing:
            event.accept()
        else:
            event.ignore()

    def finish_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.blockSignals(True)
        self.hide()
        self.close()


class _LoraFindNameButton(QPushButton):
    """Squared name button; double-click selects."""

    double_activated = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_activated.emit()
        super().mouseDoubleClickEvent(event)


class LoraFindDialog(QDialog):
    """Pick a known on-disk LoRA (lightweight path scan for Add LoRA)."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        choices: Optional[List[LoraProbeChoice]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find LoRA")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(420, 360)
        self.resize(520, 520)
        self._selected: Optional[LoraProbeChoice] = None

        if choices is None:
            from config import get_config

            # Lightweight path listing (no MD5) — still can take a moment on large caches.
            scan_parent = parent if isinstance(parent, QWidget) else self
            progress = QProgressDialog(
                "Looking up on-disk LoRA files…",
                None,
                0,
                0,
                scan_parent,
            )
            progress.setWindowTitle("Find LoRA")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setCancelButton(None)
            progress.setMinimumWidth(360)
            progress.show()
            QApplication.processEvents()
            try:
                choices = discover_find_lora_choices(get_config().load_settings())
            finally:
                progress.close()
        items = sorted(
            choices or [],
            key=lambda c: ((c.display_name or c.label or "").lower()),
        )

        th = get_active_theme()
        item_style = (
            f"QPushButton#loraFindNameButton {{"
            f"  background-color: {th.dialog_background_hex};"
            f"  color: {th.dialog_text_color_hex};"
            f"  border: 1px solid {th.border_default_hex};"
            f"  border-radius: 0px;"
            f"  padding: 6px 10px;"
            f"  text-align: left;"
            f"  min-width: 0px;"
            f"}}"
            f"QPushButton#loraFindNameButton:hover {{"
            f"  background-color: {th.dialog_background_hex};"
            f"  border: 1px solid {th.border_hover_hex};"
            f"}}"
            f"QPushButton#loraFindNameButton:pressed {{"
            f"  background-color: {th.dialog_background_hex};"
            f"}}"
        )
        self.setStyleSheet(
            get_dialog_shell_stylesheet() + get_button_style() + item_style
        )
        layout = QVBoxLayout(self)
        apply_standard_dialog_layout(layout)

        hint = QLabel("Double-click a LoRA name to fill the Add LoRA form.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(4)

        if not items:
            empty = QLabel("No LoRA weights found on disk.")
            host_layout.addWidget(empty)
        else:
            for choice in items:
                name = (choice.display_name or choice.label or choice.key).strip()
                btn = _LoraFindNameButton(name)
                btn.setObjectName("loraFindNameButton")
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                tips = []
                if choice.from_downloads:
                    tips.append("Unregistered .safetensors (cache or Downloads)")
                trigger = (choice.trigger_word or "").strip()
                if trigger:
                    tips.append(f"Trigger: {trigger}")
                if tips:
                    btn.setToolTip("\n".join(tips))
                btn.double_activated.connect(
                    lambda c=choice: self._accept_choice(c)
                )
                host_layout.addWidget(btn)
        host_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        layout.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def selected_choice(self) -> Optional[LoraProbeChoice]:
        return self._selected

    def _accept_choice(self, choice: LoraProbeChoice) -> None:
        self._selected = choice
        self.accept()


def _lora_path_for_display(path: str | Path) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return normalize_path_for_display(display_to_path(text))


def _lora_path_for_validation(path: str) -> str:
    return display_to_path(str(path or "").strip())


def _pin_row_height(widget: QWidget, *, width_policy=QSizePolicy.Policy.Expanding) -> None:
    widget.setFixedHeight(_FORM_CONTROL_HEIGHT)
    widget.setMinimumWidth(0)
    widget.setSizePolicy(width_policy, QSizePolicy.Policy.Fixed)


def _pin_line_edit(edit: QLineEdit) -> None:
    """Fixed row height; allow shrink so long text scrolls inside the field."""
    _pin_row_height(edit)
    # Qt sizeHint for long text can outgrow the dialog; without min-width 0 the
    # field expands past the window and horizontal caret scrolling never runs.
    edit.setMinimumWidth(0)


class _SafetensorsPathLineEdit(QLineEdit):
    """Path field that accepts a single .safetensors file via drag and drop."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        _pin_line_edit(self)
        self.setPlaceholderText("Drop a .safetensors file here or paste a path…")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is None:
            event.ignore()
            return
        self.setText(_lora_path_for_display(path))
        event.acceptProposedAction()


def _path_from_mime(mime) -> Optional[Path]:
    if not mime.hasUrls():
        return None
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() == ".safetensors" and path.is_file():
            return path
    return None


def safetensors_path_from_mime(mime) -> Optional[Path]:
    """Return the first local .safetensors file path from a drag-and-drop mime payload."""
    return _path_from_mime(mime)


class _ImportLoraWorker(QThread):
    finished_result = Signal(bool, str, object)
    progress_update = Signal(str, int, int)

    def __init__(
        self,
        *,
        source_path: str,
        display_name: str,
        model_key: str,
        trigger_word: str,
        scale: float,
        best_guess: float,
        comment: str,
        reference_prompt: str,
        cancel_flag: List[bool],
        reuse_lora_id: Optional[str] = None,
        repo_id: str = "",
        filename: str = "",
        recovery_source_path: str = "",
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._display_name = display_name
        self._model_key = model_key
        self._trigger_word = trigger_word
        self._scale = scale
        self._best_guess = best_guess
        self._comment = comment
        self._reference_prompt = reference_prompt
        self._cancel_flag = cancel_flag
        self._reuse_lora_id = (reuse_lora_id or "").strip() or None
        self._repo_id = (repo_id or "").strip()
        self._filename = (filename or "").strip()
        self._recovery_source_path = (recovery_source_path or "").strip()
        self._created_new_entry = False
        self._progress_max = _IMPORT_PROGRESS_PROBE_STEPS
        self._probe_step = 1

    def _cancelled(self) -> bool:
        return bool(self._cancel_flag[0])

    def _emit_progress(
        self,
        activity: str,
        step: int,
        *,
        maximum: Optional[int] = None,
    ) -> None:
        if maximum is not None:
            self._progress_max = max(1, int(maximum))
        self.progress_update.emit(activity, step, self._progress_max)

    def _probe_activity_callback(self, message: str) -> None:
        lower = message.lower()
        if "base image" in lower:
            step = 2
        elif "test image" in lower:
            step = 3
        elif "similarity" in lower:
            step = 4
        else:
            step = self._probe_step
        self._probe_step = max(self._probe_step, step)
        self._emit_progress(message, self._probe_step)

    def _model_already_supported(self, lora_id: str) -> bool:
        from imagegen_plugins.lora_catalog import lora_model_support

        support = lora_model_support().get(lora_id, ())
        aliases = klein_lora_model_aliases(self._model_key)
        return any(m in support for m in aliases)

    def run(self) -> None:
        entry = None
        try:
            if self._cancelled():
                self.finished_result.emit(False, "Cancelled", None)
                return
            self._emit_progress("Validating LoRA weights…", 0)
            source = validate_safetensors_source(self._source_path)
            if not lora_probe_model_is_local(self._model_key):
                raise RuntimeError(
                    f"The base model ({lora_model_display_name(self._model_key)}) "
                    "is not installed locally. Download it first, then import the LoRA."
                )
            host_id = host_id_for_lora_model(self._model_key)
            if not host_id:
                raise ValueError(f"LoRAs are not supported for model {self._model_key!r}.")
            self._emit_progress("Preparing LoRA entry…", 1)
            if self._reuse_lora_id:
                from imagegen_plugins.lora_catalog import get_lora_entry
                from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

                entry = get_lora_entry(self._reuse_lora_id)
                if entry is None:
                    raise ValueError(f"LoRA {self._reuse_lora_id!r} was not found.")
                if entry.host_id != host_id:
                    raise ValueError(
                        "This LoRA file is already imported for a different model family."
                    )
                update_lora_entry_metadata(
                    entry.lora_id,
                    display_name=self._display_name,
                    trigger_word=self._trigger_word or None,
                    best_guess=self._best_guess,
                    comment=self._comment or None,
                    reference_prompt=self._reference_prompt,
                    repo_id=self._repo_id,
                    filename=self._filename,
                    source_path=self._recovery_source_path or None,
                )
                entry = get_lora_entry(entry.lora_id)
                if entry is None:
                    raise ValueError(f"LoRA {self._reuse_lora_id!r} was not found.")
            else:
                existing = find_user_lora_for_source(source, host_id=host_id)
                if existing is not None:
                    from imagegen_plugins.lora_catalog import get_lora_entry
                    from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

                    update_lora_entry_metadata(
                        existing.lora_id,
                        display_name=self._display_name,
                        trigger_word=self._trigger_word or None,
                        best_guess=self._best_guess,
                        comment=self._comment or None,
                        reference_prompt=self._reference_prompt,
                        repo_id=self._repo_id,
                        filename=self._filename,
                        source_path=self._recovery_source_path or None,
                    )
                    entry = get_lora_entry(existing.lora_id)
                    if entry is None:
                        raise ValueError(f"LoRA {existing.lora_id!r} was not found.")
                else:
                    entry = build_user_lora_entry(
                        source_path=source,
                        display_name=self._display_name,
                        model_key=self._model_key,
                        trigger_word=self._trigger_word or None,
                        scale=self._scale,
                        best_guess=self._best_guess,
                        comment=self._comment or None,
                        reference_prompt=self._reference_prompt,
                        repo_id=self._repo_id,
                        filename=self._filename,
                    )
                    if self._recovery_source_path:
                        from dataclasses import replace

                        entry = replace(entry, source_path=self._recovery_source_path)
                    self._created_new_entry = True
            from imagegen_plugins.mflux_lora_presets import assert_lora_compatible_for_model

            assert_lora_compatible_for_model(
                entry.local_path or "",
                self._model_key,
                catalog_host_id=entry.host_id,
            )
            if not self._model_already_supported(entry.lora_id):
                from imagegen_plugins.lora_catalog import lora_probe_prompt

                self._emit_progress(
                    f"Testing compatibility on {lora_model_display_name(self._model_key)}…",
                    1,
                    maximum=_IMPORT_PROGRESS_PROBE_STEPS,
                )
                ok = probe_lora_on_model(
                    self._model_key,
                    entry.local_path or "",
                    entry.scale,
                    self._cancelled,
                    entry=entry,
                    probe_prompt=lora_probe_prompt(
                        entry,
                        fallback=_probe_fallback_prompt(self._reference_prompt),
                        weights_path=entry.local_path or "",
                        allow_online=False,
                    ),
                    activity_callback=self._probe_activity_callback,
                )
                if self._cancelled():
                    self.finished_result.emit(False, "Cancelled", entry)
                    return
                if not ok:
                    self.finished_result.emit(
                        False,
                        f"LoRA «{entry.display_name}» failed the compatibility test for "
                        f"{lora_model_display_name(self._model_key)}.",
                        entry,
                    )
                    return
            else:
                self._emit_progress(
                    "LoRA already tested for this model; skipping probe…",
                    2,
                    maximum=_IMPORT_PROGRESS_SKIP_PROBE_STEPS,
                )
            from imagegen_plugins.image_gen_persistence import register_user_lora

            self._emit_progress("Adding to library…", self._progress_max - 1)
            register_user_lora(
                entry,
                model_key=self._model_key,
                supported_models=[self._model_key],
            )
            try:
                from imagegen_plugins.image_gen_persistence import enrich_lora_origin_metadata

                self._emit_progress("Looking up source metadata…", self._progress_max)
                enrich_lora_origin_metadata(entry.lora_id)
                from imagegen_plugins.lora_catalog import get_lora_entry

                refreshed = get_lora_entry(entry.lora_id)
                if refreshed is not None:
                    entry = refreshed
            except Exception:
                pass
            self.finished_result.emit(True, "", entry)
        except Exception as exc:
            self.finished_result.emit(False, str(exc), entry)


class _FindOriginWorker(QThread):
    finished_result = Signal(bool, str, object)

    def __init__(self, lora_id: str) -> None:
        super().__init__()
        self._lora_id = lora_id

    def run(self) -> None:
        try:
            from imagegen_plugins.image_gen_persistence import enrich_lora_origin_metadata

            match = enrich_lora_origin_metadata(self._lora_id)
            if match is None:
                self.finished_result.emit(
                    False,
                    "No matching Civitai or Hugging Face source was found.",
                    None,
                )
                return
            self.finished_result.emit(True, "", match)
        except Exception as exc:
            self.finished_result.emit(False, str(exc), None)



class LoraEntryDialog(QDialog):
    """Add downloaded LoRA or edit metadata for any catalog entry."""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        model_key: str,
        mode: str = "add",
        lora_id: Optional[str] = None,
        initial_source_path: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._model_key = model_key
        self._mode = mode
        self._lora_id = lora_id
        self._edit_entry = None
        if mode == "edit":
            if not lora_id:
                raise ValueError("lora_id is required for edit mode.")
            from imagegen_plugins.lora_catalog import get_lora_entry

            self._edit_entry = get_lora_entry(lora_id)
            if self._edit_entry is None:
                raise ValueError(f"LoRA {lora_id!r} was not found.")

        is_edit = mode == "edit"
        self.setWindowTitle("Edit LoRA" if is_edit else "Add Downloaded LoRA")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(580, 450 if is_edit else 430)
        self.setStyleSheet(
            get_dialog_shell_stylesheet()
            + get_button_style()
            + "QPushButton#loraImportBrowseButton { min-width: 96px; padding: 4px 10px; }"
            # Vertical padding + fixed height was crushing the content rect so
            # long values could not scroll/caret to the start.
            + "QDialog QLineEdit { padding: 2px 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        if is_edit:
            intro = QLabel(
                f"Edit LoRA details for <b>{lora_model_display_name(model_key)}</b>."
            )
        else:
            intro = QLabel(
                f"Import a .safetensors LoRA for <b>{lora_model_display_name(model_key)}</b>. "
                "The file is copied into the app cache and tested before it is added."
            )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._intro_label = intro
        self._reuse_lora_id: Optional[str] = None

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._path_edit = _SafetensorsPathLineEdit(self)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setObjectName("loraImportBrowseButton")
        self._browse_btn.setFixedWidth(96)
        _pin_row_height(self._browse_btn, width_policy=QSizePolicy.Policy.Fixed)
        self._browse_btn.clicked.connect(self._browse)
        self._find_btn = None
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(self._browse_btn)
        if not is_edit:
            self._find_btn = QPushButton("Find")
            self._find_btn.setObjectName("loraImportBrowseButton")
            self._find_btn.setFixedWidth(72)
            _pin_row_height(self._find_btn, width_policy=QSizePolicy.Policy.Fixed)
            self._find_btn.setToolTip(
                "Pick a known on-disk LoRA from the catalog and cache/Downloads"
            )
            self._find_btn.clicked.connect(self._find_known_lora)
            path_row.addWidget(self._find_btn)
        self._path_wrap = QWidget()
        self._path_wrap.setLayout(path_row)
        self._path_wrap.setMinimumWidth(0)
        self._path_wrap.setFixedHeight(_FORM_CONTROL_HEIGHT)
        self._path_wrap.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._path_label = "File:"
        form.addRow(self._path_label, self._path_wrap)

        self._name_edit = QLineEdit()
        _pin_line_edit(self._name_edit)
        self._name_edit.setPlaceholderText("Display name in LoRA menus")
        form.addRow("Name:", self._name_edit)

        self._trigger_edit = QLineEdit()
        _pin_line_edit(self._trigger_edit)
        self._trigger_edit.setPlaceholderText("Optional trigger word for prompts")
        form.addRow("Trigger:", self._trigger_edit)

        self._reference_prompt_edit = QLineEdit()
        _pin_line_edit(self._reference_prompt_edit)
        self._reference_prompt_edit.setPlaceholderText(_DEFAULT_REFERENCE_PROMPT)
        self._reference_prompt_edit.setToolTip(
            "Prompt used for compatibility test images when adding this LoRA"
        )
        form.addRow("Reference prompt:", self._reference_prompt_edit)

        self._current_scale_spin = QDoubleSpinBox()
        _pin_row_height(self._current_scale_spin, width_policy=QSizePolicy.Policy.Fixed)
        self._current_scale_spin.setRange(0.1, 2.0)
        self._current_scale_spin.setSingleStep(0.1)
        self._current_scale_spin.setDecimals(2)
        self._current_scale_spin.setValue(1.0)
        self._current_scale_spin.setReadOnly(True)
        self._current_scale_spin.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self._current_scale_spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._current_scale_spin.setToolTip(
            "Current weight from the image-gen LoRA pulldown (read-only here)"
        )

        self._best_guess_spin = QDoubleSpinBox()
        _pin_row_height(self._best_guess_spin, width_policy=QSizePolicy.Policy.Fixed)
        self._best_guess_spin.setRange(0.1, 2.0)
        self._best_guess_spin.setSingleStep(0.1)
        self._best_guess_spin.setDecimals(2)
        self._best_guess_spin.setValue(1.0)
        self._best_guess_spin.setToolTip(
            "Default weight restored when the LoRA pulldown weight field is left blank"
        )

        scale_row = QWidget()
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        scale_layout.setSpacing(8)
        current_label = QLabel("Current:")
        guess_label = QLabel("Best guess:")
        scale_layout.addWidget(current_label)
        scale_layout.addWidget(self._current_scale_spin)
        scale_layout.addWidget(guess_label)
        scale_layout.addWidget(self._best_guess_spin)
        scale_layout.addStretch(1)
        scale_row.setFixedHeight(_FORM_CONTROL_HEIGHT)
        scale_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Scale:", scale_row)
        # Keep a private alias used by older call sites in this module.
        self._scale_spin = self._best_guess_spin
        if not is_edit:
            def _sync_current_from_guess(value: float) -> None:
                if self._reuse_lora_id:
                    return
                self._current_scale_spin.setValue(float(value))

            self._best_guess_spin.valueChanged.connect(_sync_current_from_guess)

        self._comment_edit = QLineEdit()
        _pin_line_edit(self._comment_edit)
        self._comment_edit.setPlaceholderText("Optional notes (Settings tab only)")
        form.addRow("Comment:", self._comment_edit)

        self._repo_edit = QLineEdit()
        _pin_line_edit(self._repo_edit)
        self._repo_edit.setPlaceholderText("Optional Hugging Face repo for reinstall")
        form.addRow("HF repo:", self._repo_edit)

        self._filename_edit = QLineEdit()
        _pin_line_edit(self._filename_edit)
        self._filename_edit.setPlaceholderText("Optional .safetensors filename on Hugging Face")
        form.addRow("HF file:", self._filename_edit)

        self._recovery_path_edit = _SafetensorsPathLineEdit(self)
        self._recovery_path_edit.setPlaceholderText(
            "Local path or download URL for reinstall (Civitai / Hugging Face)"
        )
        form.addRow("Recovery path:", self._recovery_path_edit)
        layout.addLayout(form)
        self._form = form

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._find_origin_btn = None
        if is_edit:
            self._find_origin_btn = QPushButton("Find source online")
            _pin_row_height(self._find_origin_btn, width_policy=QSizePolicy.Policy.Fixed)
            self._find_origin_btn.setToolTip(
                "Search Civitai (file hash) and Hugging Face for reinstall metadata"
            )
            self._find_origin_btn.clicked.connect(self._find_origin_online)
            btn_row.addWidget(self._find_origin_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        _pin_row_height(cancel_btn, width_policy=QSizePolicy.Policy.Fixed)
        cancel_btn.clicked.connect(self.reject)
        self._action_btn = QPushButton("Save" if is_edit else "Test && Add")
        _pin_row_height(self._action_btn, width_policy=QSizePolicy.Policy.Fixed)
        self._action_btn.setDefault(True)
        self._action_btn.clicked.connect(
            self._save_edit if is_edit else self._start_import
        )
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._action_btn)
        layout.addLayout(btn_row)

        if is_edit:
            self._prime_edit_fields()
        else:
            self._reference_prompt_edit.setText(_DEFAULT_REFERENCE_PROMPT)
            self._path_edit.textChanged.connect(self._on_path_changed)
            initial_path = str(initial_source_path or "").strip()
            if initial_path:
                self._path_edit.setText(_lora_path_for_display(initial_path))
                self._on_path_changed(self._path_edit.text())

    def _update_add_intro(self, *, reusing: bool) -> None:
        if self._mode != "add":
            return
        model_label = lora_model_display_name(self._model_key)
        if reusing:
            self._intro_label.setText(
                f"This file is already imported. Adding will enable it for "
                f"<b>{model_label}</b> using the existing LoRA entry."
            )
            return
        self._intro_label.setText(
            f"Import a .safetensors LoRA for <b>{model_label}</b>. "
            "The file is copied into the app cache and tested before it is added."
        )

    def _prime_edit_fields(self) -> None:
        entry = self._edit_entry
        if entry is None:
            return
        path = (entry.local_path or "").strip()
        if path:
            self._path_edit.setText(_lora_path_for_display(path))
            self._path_edit.setReadOnly(True)
            self._path_edit.setAcceptDrops(False)
            self._browse_btn.setEnabled(False)
        else:
            self._form.removeRow(self._path_wrap)
        self._name_edit.setText(entry.display_name)
        self._trigger_edit.setText(entry.trigger_word or "")
        self._reference_prompt_edit.setText(
            (entry.reference_prompt or "").strip() or _DEFAULT_REFERENCE_PROMPT
        )
        self._current_scale_spin.setValue(float(entry.scale))
        self._best_guess_spin.setValue(float(entry.best_guess))
        self._comment_edit.setText(entry.comment or "")
        self._repo_edit.setText(entry.repo_id or "")
        self._filename_edit.setText(entry.filename or "")
        recovery = (entry.source_path or entry.local_path or "").strip()
        if recovery:
            self._recovery_path_edit.setText(_lora_path_for_display(recovery))

    def _find_origin_online(self) -> None:
        if not self._lora_id or self._edit_entry is None:
            return
        from imagegen_plugins.lora_origin_lookup import entry_needs_origin_lookup

        if not entry_needs_origin_lookup(self._edit_entry):
            show_styled_information(
                self,
                "Find source online",
                "This LoRA already has Hugging Face or download URL metadata.",
            )
            return
        if self._find_origin_btn is not None:
            self._find_origin_btn.setEnabled(False)

        progress = QProgressDialog(
            "Searching Civitai and Hugging Face…",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("Find source online")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        worker = _FindOriginWorker(self._lora_id)

        def on_done(ok: bool, err: str, match: object) -> None:
            progress.close()
            if self._find_origin_btn is not None:
                self._find_origin_btn.setEnabled(True)
            if ok and match is not None:
                from imagegen_plugins.lora_catalog import get_lora_entry

                refreshed = get_lora_entry(self._lora_id)
                if refreshed is not None:
                    self._edit_entry = refreshed
                    self._trigger_edit.setText(refreshed.trigger_word or "")
                    self._comment_edit.setText(refreshed.comment or "")
                    self._repo_edit.setText(refreshed.repo_id or "")
                    self._filename_edit.setText(refreshed.filename or "")
                    recovery = (refreshed.source_path or refreshed.local_path or "").strip()
                    if recovery:
                        self._recovery_path_edit.setText(_lora_path_for_display(recovery))
                note = str(getattr(match, "note", "") or "").strip()
                source = (
                    str(getattr(match, "page_url", "") or "").strip()
                    or str(getattr(match, "download_url", "") or "").strip()
                )
                msg = "Reinstall metadata was updated."
                if source:
                    msg += f"\n\nSource: {source}"
                if note:
                    msg += f"\n({note})"
                show_styled_information(self, "Find source online", msg)
                return
            if err:
                show_styled_warning(self, "Find source online", err)

        worker.finished_result.connect(on_done)
        worker.start()
        self._origin_worker = worker

    def _on_path_changed(self, text: str) -> None:
        if self._mode != "add":
            return
        path = (text or "").strip()
        if not path:
            self._reuse_lora_id = None
            self._update_add_intro(reusing=False)
            return
        host_id = host_id_for_lora_model(self._model_key)
        if not host_id:
            return
        resolved_path = _lora_path_for_validation(path)
        try:
            source = validate_safetensors_source(resolved_path)
            display_path = _lora_path_for_display(source)
            if display_path and display_path != path:
                self._set_path_edit_text(display_path)
                path = display_path
            existing = find_user_lora_for_source(source, host_id=host_id)
        except Exception:
            existing = None
            if not self._name_edit.text().strip():
                try:
                    self._name_edit.setText(
                        display_name_from_path(Path(resolved_path).expanduser())
                    )
                except Exception:
                    pass
            self._reuse_lora_id = None
            self._update_add_intro(reusing=False)
            return
        if existing is not None:
            self._reuse_lora_id = existing.lora_id
            self._name_edit.setText(existing.display_name)
            self._trigger_edit.setText(existing.trigger_word or "")
            if (existing.reference_prompt or "").strip():
                self._reference_prompt_edit.setText(existing.reference_prompt or "")
            self._current_scale_spin.setValue(float(existing.scale))
            self._best_guess_spin.setValue(float(existing.best_guess))
            self._comment_edit.setText(existing.comment or "")
            self._update_add_intro(reusing=True)
            return
        self._reuse_lora_id = None
        if not self._name_edit.text().strip():
            self._name_edit.setText(display_name_from_path(source))
        self._update_add_intro(reusing=False)

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select LoRA weights",
            str(Path.home() / "Downloads"),
            "Safetensors (*.safetensors);;All Files (*)",
        )
        if path:
            self._path_edit.setText(_lora_path_for_display(path))

    def _find_known_lora(self) -> None:
        if self._mode != "add":
            return
        dialog = LoraFindDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        choice = dialog.selected_choice()
        if choice is None:
            return
        self._apply_found_lora(choice)

    def _apply_found_lora(self, choice: LoraProbeChoice) -> None:
        """Fill Add LoRA fields from a Check-LoRAs scan choice."""
        path = (choice.weights_path or "").strip()
        if path:
            # Let path-change reuse detection run, then overlay known metadata.
            self._path_edit.setText(_lora_path_for_display(path))
        name = (choice.display_name or "").strip()
        if name:
            self._name_edit.setText(name)
        elif path and not self._name_edit.text().strip():
            try:
                self._name_edit.setText(
                    display_name_from_path(Path(_lora_path_for_validation(path)).expanduser())
                )
            except Exception:
                pass
        self._trigger_edit.setText((choice.trigger_word or "").strip())
        try:
            current = float(choice.scale)
        except Exception:
            current = 1.0
        if self._reuse_lora_id:
            # Path-change already primed Current / Best guess from the existing entry.
            pass
        else:
            self._current_scale_spin.setValue(current)
            self._best_guess_spin.setValue(1.0)
        self._comment_edit.setText((choice.comment or "").strip())
        self._repo_edit.setText((choice.repo_id or "").strip())
        self._filename_edit.setText((choice.filename or "").strip())
        recovery = (choice.source_path or choice.weights_path or "").strip()
        if recovery:
            self._recovery_path_edit.setText(_lora_path_for_display(recovery))
        # Show the start of long paths (caret scrolling needs a constrained width).
        self._path_edit.setCursorPosition(0)
        self._recovery_path_edit.setCursorPosition(0)
        self._name_edit.setCursorPosition(0)

    def _set_path_edit_text(self, text: str) -> None:
        self._path_edit.blockSignals(True)
        self._path_edit.setText(text)
        self._path_edit.blockSignals(False)

    def _save_edit(self) -> None:
        if self._edit_entry is None or not self._lora_id:
            return
        name = self._name_edit.text().strip()
        if not name:
            show_styled_warning(self, "Edit LoRA", "Enter a display name.")
            return
        from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

        try:
            update_lora_entry_metadata(
                self._lora_id,
                display_name=name,
                trigger_word=self._trigger_edit.text().strip() or None,
                best_guess=float(self._best_guess_spin.value()),
                comment=self._comment_edit.text().strip() or None,
                reference_prompt=self._reference_prompt_edit.text().strip(),
                repo_id=self._repo_edit.text().strip(),
                filename=self._filename_edit.text().strip(),
                source_path=self._recovery_path_edit.text().strip() or None,
            )
        except ValueError as exc:
            show_styled_warning(self, "Edit LoRA", str(exc))
            return
        except Exception as exc:
            show_styled_warning(self, "Edit LoRA", str(exc))
            return
        self.accept()

    def _start_import(self) -> None:
        path = self._path_edit.text().strip()
        name = self._name_edit.text().strip()
        if not path:
            show_styled_warning(self, "Add LoRA", "Choose a .safetensors file.")
            return
        if not name:
            show_styled_warning(self, "Add LoRA", "Enter a display name.")
            return
        resolved_path = _lora_path_for_validation(path)
        recovery_path = self._recovery_path_edit.text().strip()
        download_source_url = ""
        if resolved_path.lower().startswith(("http://", "https://")):
            download_source_url = resolved_path
            try:
                from imagegen_plugins.civitai_client import download_url_to_path
                import tempfile

                tmp_dir = Path(tempfile.mkdtemp(prefix="prowser_lora_import_"))
                downloaded = download_url_to_path(
                    resolved_path,
                    tmp_dir / "import.safetensors",
                )
                resolved_path = str(downloaded)
            except ValueError as exc:
                show_styled_warning(self, "Add LoRA", str(exc))
                return
            except Exception as exc:
                show_styled_warning(self, "Add LoRA", str(exc))
                return
        else:
            try:
                validate_safetensors_source(resolved_path)
            except (OSError, ValueError) as exc:
                show_styled_warning(self, "Add LoRA", str(exc))
                return
        display_path = _lora_path_for_display(resolved_path)
        if display_path and display_path != path:
            self._set_path_edit_text(display_path)

        host_id = host_id_for_lora_model(self._model_key)
        reuse_lora_id = self._reuse_lora_id
        if not reuse_lora_id and host_id:
            try:
                source = validate_safetensors_source(resolved_path)
                existing = find_user_lora_for_source(source, host_id=host_id)
                if existing is not None:
                    reuse_lora_id = existing.lora_id
            except Exception:
                pass
        if reuse_lora_id and host_id:
            from config import get_config
            from imagegen_plugins.lora_catalog_settings import model_state

            st = model_state(get_config().load_settings(), self._model_key)
            enabled = set(st.get("enabled_ids") or [])
            deleted = set(st.get("deleted_ids") or st.get("hidden_ids") or [])
            if reuse_lora_id in enabled and reuse_lora_id not in deleted:
                show_styled_information(
                    self,
                    "Add LoRA",
                    f"«{name}» is already enabled for "
                    f"{lora_model_display_name(self._model_key)}.",
                )
                self.accept()
                return

        # Show profile tmp thumbnails (date newest-first) as a normal ESC level
        # so probe images appear while Test & Add runs.
        main_window = _resolve_browser_main_window(self)
        if main_window is not None:
            try:
                _open_profile_temp_thumbnails(main_window)
                _highlight_newest_thumbnail(main_window)
            except Exception as exc:
                print(f"DEBUG Test & Add: could not open profile temp thumbnails: {exc}")

        progress = _LoraImportProgressDialog(
            self,
            model_key=self._model_key,
            lora_name=name,
            probe_prompt=_probe_fallback_prompt(
                self._reference_prompt_edit.text().strip()
            ),
            maximum=_IMPORT_PROGRESS_PROBE_STEPS,
        )
        progress.show()
        progress.raise_()
        progress.activateWindow()
        QApplication.processEvents()

        cancel_flag: List[bool] = [False]

        def on_probe_user_cancel() -> None:
            cancel_flag[0] = True

        progress.canceled.connect(on_probe_user_cancel)

        recovery_path = recovery_path or download_source_url or resolved_path

        worker = _ImportLoraWorker(
            source_path=resolved_path,
            display_name=name,
            model_key=self._model_key,
            trigger_word=self._trigger_edit.text().strip(),
            scale=float(self._best_guess_spin.value()),
            best_guess=float(self._best_guess_spin.value()),
            comment=self._comment_edit.text().strip(),
            reference_prompt=self._reference_prompt_edit.text().strip(),
            cancel_flag=cancel_flag,
            reuse_lora_id=reuse_lora_id,
            repo_id=self._repo_edit.text().strip(),
            filename=self._filename_edit.text().strip(),
            recovery_source_path=recovery_path,
        )

        def on_progress(activity: str, step: int, maximum: int) -> None:
            progress.update_progress(activity, step, maximum)

        def on_done(ok: bool, err: str, entry: object) -> None:
            progress.finish_and_close()
            if main_window is not None:
                try:
                    _refresh_temp_and_highlight_newest(main_window)
                except Exception as exc:
                    print(
                        "DEBUG Test & Add: could not highlight newest temp thumbnail: "
                        f"{exc}"
                    )
            if ok:
                show_styled_information(
                    self,
                    "Add LoRA",
                    f"«{getattr(entry, 'display_name', name)}» was added and enabled.",
                )
                self.accept()
                return
            if entry is not None and getattr(worker, "_created_new_entry", False):
                from imagegen_plugins.lora_user_entries import remove_user_lora_files

                remove_user_lora_files(entry)
            if err and err != "Cancelled":
                show_styled_warning(self, "Add LoRA", err)

        worker.progress_update.connect(on_progress)
        worker.finished_result.connect(on_done)
        worker.start()
        self._worker = worker


# Back-compat alias
AddDownloadedLoraDialog = LoraEntryDialog


def run_add_downloaded_lora_dialog(
    parent: Optional[QWidget],
    *,
    model_key: str,
    initial_source_path: Optional[str] = None,
) -> bool:
    """Open import dialog; return True if a LoRA was registered."""
    dlg = LoraEntryDialog(
        parent,
        model_key=model_key,
        mode="add",
        initial_source_path=initial_source_path,
    )
    return dlg.exec() == QDialog.DialogCode.Accepted


def run_edit_lora_dialog(
    parent: Optional[QWidget],
    *,
    lora_id: str,
    model_key: str,
) -> bool:
    """Open edit dialog; return True if metadata was saved."""
    try:
        dlg = LoraEntryDialog(
            parent,
            model_key=model_key,
            mode="edit",
            lora_id=lora_id,
        )
    except ValueError as exc:
        show_styled_warning(parent, "Edit LoRA", str(exc))
        return False
    return dlg.exec() == QDialog.DialogCode.Accepted
