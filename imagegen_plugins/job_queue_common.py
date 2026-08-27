#!/usr/bin/env python3
"""Shared job queue helpers (action buttons, previews, row HTML)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from imagegen_plugins.image_gen_dialog import connect_import_button_with_option_modifier
from imagegen_plugins.image_gen_source_nav import open_image_in_browse
from imagegen_plugins.model_task_queue import refresh_queued_job_status
from config import (
    job_queue_action_bar_background_hex,
    job_queue_action_bar_background_qcolor,
    job_queue_cell_background_hex,
    job_queue_running_cell_background_hex,
)
from theme.theme_service import get_active_theme
from theme.titlebar_icons import titlebar_chip_colors
from widgets.icon_hover_swap import attach_icon_hover_swap, icon_pair_from_assets

_ICON_BTN_SIZE = 22
_ACTION_BAR_HEIGHT = 28
_ACTION_BAR_OBJECT_NAME = "jobQueueActionBar"


def _job_queue_cell_background_stylesheet(*, running: bool = False) -> str:
    bg = (
        job_queue_running_cell_background_hex()
        if running
        else job_queue_cell_background_hex()
    )
    return f"background-color: {bg};"


def _job_queue_action_bar_background_stylesheet(*, running: bool = False) -> str:
    bg = (
        job_queue_running_cell_background_hex()
        if running
        else job_queue_action_bar_background_hex()
    )
    return f"QWidget#{_ACTION_BAR_OBJECT_NAME} {{ background-color: {bg}; }}"


def _apply_job_queue_cell_background(widget: QWidget, *, running: bool = False) -> None:
    widget.setStyleSheet(_job_queue_cell_background_stylesheet(running=running))
    widget.setAutoFillBackground(True)


def _apply_job_queue_action_bar_background(
    widget: QWidget, *, running: bool = False
) -> None:
    widget.setStyleSheet(
        _job_queue_action_bar_background_stylesheet(running=running)
    )
    widget.setAutoFillBackground(True)


def _valid_preview_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for raw in paths:
        p = str(raw or "").strip()
        if p and os.path.isfile(p):
            out.append(p)
    return out


def create_invalid_job_preview_label(size: int) -> QLabel:
    from PySide6.QtGui import QPixmap

    from theme.theme_base import invalid_job_preview_path

    thumb = QLabel()
    thumb.setFixedSize(size, size)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    thumb.setStyleSheet(_job_queue_cell_background_stylesheet())
    px = QPixmap(invalid_job_preview_path())
    if not px.isNull():
        thumb.setPixmap(
            px.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return thumb


def info_html_for_queue_row(
    controller, row_idx: int, row, *, for_sidebar: bool = False
) -> str:
    if row.is_active:
        return controller.get_task_queue_status_info_html(
            omit_live_steps_row=for_sidebar
        )
    job = controller._queued_job_by_id(row.job_id)
    if job is not None:
        refresh_queued_job_status(job)
        return job.status_html or ""
    return row.status_html or ""


def job_queue_edit_row(main_window, controller, row: int) -> None:
    rows = controller.queue_snapshot()
    if row < 0 or row >= len(rows):
        return
    entry = rows[row]
    record = controller.job_record_for_row(row)
    if record is None:
        return
    plugin, values = record
    from imagegen_plugins.image_gen_menu import open_imagegen_dialog_from_job

    replace_job_id = entry.job_id
    if entry.is_active and not controller.is_active_job_remaining_updatable(
        entry.job_id
    ):
        replace_job_id = None
    open_imagegen_dialog_from_job(
        main_window, plugin, values, replace_job_id=replace_job_id
    )


def job_queue_cancel_row(
    main_window, controller, row: int, *, option_held: bool = False
) -> None:
    if option_held:
        controller.cancel_jobs_from_row_and_subsequent(row)
    else:
        controller.confirm_cancel_job_at_row(main_window, row)


class JobQueueActionBar(QWidget):
    """Shared horizontal action bar for the selected queue row."""

    def __init__(self, main_window, controller, parent=None):
        super().__init__(parent)
        self.setObjectName(_ACTION_BAR_OBJECT_NAME)
        self._main_window = main_window
        self._controller = controller
        self._row_idx = -1
        self._speak_highlighted = False
        self._speak_btn: QPushButton | None = None
        _apply_job_queue_action_bar_background(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        self._layout = layout

        self._speak_btn = self._create_speak_button()
        if self._speak_btn is not None:
            layout.addWidget(self._speak_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._plus_btn = QPushButton()
        self._plus_btn.setToolTip("Add another image to this series")
        _configure_icon_push_button(self._plus_btn, "series_plus_icon.png")
        self._plus_btn.clicked.connect(self._on_plus)

        self._minus_btn = QPushButton()
        self._minus_btn.setToolTip(
            "Remove one pending image from the series.\n"
            "Option+click to remove all remaining images."
        )
        _configure_icon_push_button(self._minus_btn, "series_minus_icon.png")
        connect_import_button_with_option_modifier(
            self._minus_btn, self._on_minus
        )

        self._image_refine_btn = QPushButton()
        self._image_refine_btn.setToolTip(
            "Image Based Refinement:\n\n"
            "Base subsequent image copies on previous result image.\n\n"
            "Other source images, if any, keep their order."
        )
        _configure_series_toggle_push_button(
            self._image_refine_btn, "series_image_refinement_icon.png"
        )
        self._image_refine_btn.toggled.connect(self._on_image_refine_toggled)

        self._text_refine_btn = QPushButton()
        self._text_refine_btn.setToolTip(
            "Text Based Refinement:\n\n"
            "Re-run the previous prompt through Gen Prompt AI before each\n"
            "subsequent copy in the series."
        )
        _configure_series_toggle_push_button(
            self._text_refine_btn, "series_text_refinement_icon.png"
        )
        self._text_refine_btn.toggled.connect(self._on_text_refine_toggled)

        self._edit_btn = QPushButton()
        self._edit_btn.setToolTip(
            "Replicate job settings…\n"
            "For a pending job, use Replace in the dialog to update it in place.\n"
            "For a running batch job, use Update to change remaining copies."
        )
        _configure_icon_push_button(self._edit_btn, "edit_icon.png")
        self._edit_btn.clicked.connect(self._on_edit)

        self._cancel_btn = QPushButton()
        self._cancel_btn.setToolTip(
            "Cancel job\n"
            "Option+click to cancel this job and all jobs after it (no confirmation)."
        )
        _configure_icon_push_button(
            self._cancel_btn, "trash_icon.png", hover_icon_name="trash_icon_hover.png"
        )
        connect_import_button_with_option_modifier(
            self._cancel_btn, self._on_cancel
        )

        layout.addStretch(1)
        for btn in (
            self._image_refine_btn,
            self._text_refine_btn,
            self._edit_btn,
            self._plus_btn,
            self._minus_btn,
            self._cancel_btn,
        ):
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(_ACTION_BAR_HEIGHT)

    def _create_speak_button(self) -> QPushButton | None:
        from chat_plugins.chat_ui_common import (
            chat_audio_output_ui_enabled,
            create_chat_speak_button,
        )

        if not chat_audio_output_ui_enabled():
            return None
        btn = create_chat_speak_button(self)
        btn.setObjectName("jobQueueSpeakBtn")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(self._on_speak)
        from speech_utils import (
            is_speaking,
            register_speech_state_listener,
            unregister_speech_state_listener,
        )

        self._speak_highlighted = is_speaking()
        self._apply_speak_button_style()
        register_speech_state_listener(self._on_speech_state_changed)
        btn.destroyed.connect(
            lambda: unregister_speech_state_listener(self._on_speech_state_changed)
        )
        return btn

    def _full_prompt_for_row(self) -> str:
        if self._row_idx < 0:
            return ""
        rows = self._controller.queue_snapshot()
        if self._row_idx >= len(rows):
            return ""
        return str(rows[self._row_idx].full_prompt or "").strip()

    def _on_speak(self, _checked: bool = False) -> None:
        from speech_utils import is_speaking, speak_or_stop

        text = self._full_prompt_for_row()
        if not text and not is_speaking():
            return
        speak_or_stop(text)
        QTimer.singleShot(0, self._sync_speak_highlight)

    def _on_speech_state_changed(self, _speaking: bool) -> None:
        QTimer.singleShot(0, self._sync_speak_highlight)

    def _sync_speak_highlight(self) -> None:
        from speech_utils import is_speaking

        highlighted = is_speaking()
        if highlighted == self._speak_highlighted:
            return
        self._speak_highlighted = highlighted
        self._apply_speak_button_style()

    def _apply_speak_button_style(self) -> None:
        btn = self._speak_btn
        if btn is None:
            return
        from chat_plugins.chat_ui_common import chat_speak_button_stylesheet

        btn.setStyleSheet(
            chat_speak_button_stylesheet(highlighted=self._speak_highlighted)
        )

    def _on_plus(self, _checked: bool = False) -> None:
        if self._row_idx >= 0:
            self._controller.add_series_cycle_for_row(self._row_idx)

    def _on_minus(self, option_held: bool = False) -> None:
        if self._row_idx < 0:
            return
        if option_held:
            self._controller.clear_series_remaining_for_row(self._row_idx)
        else:
            self._controller.subtract_series_remaining_for_row(self._row_idx)

    def _on_image_refine_toggled(self, checked: bool) -> None:
        def apply_fn(enabled: bool) -> bool:
            if self._row_idx < 0:
                return False
            return self._controller.set_series_refinement_for_row(
                self._row_idx, enabled
            )

        _apply_series_refinement_toggle(
            self._image_refine_btn,
            "series_image_refinement_icon.png",
            checked,
            apply_fn,
        )

    def _on_text_refine_toggled(self, checked: bool) -> None:
        def apply_fn(enabled: bool) -> bool:
            if self._row_idx < 0:
                return False
            return self._controller.set_series_prompt_refinement_for_row(
                self._row_idx, enabled
            )

        _apply_series_refinement_toggle(
            self._text_refine_btn,
            "series_text_refinement_icon.png",
            checked,
            apply_fn,
        )

    def _on_edit(self, _checked: bool = False) -> None:
        if self._row_idx >= 0:
            job_queue_edit_row(self._main_window, self._controller, self._row_idx)

    def _on_cancel(self, option_held: bool = False) -> None:
        if self._row_idx >= 0:
            job_queue_cancel_row(
                self._main_window,
                self._controller,
                self._row_idx,
                option_held=option_held,
            )

    def update_for_row(self, row_idx: int) -> None:
        self._row_idx = row_idx
        controller = self._controller
        has_row = row_idx >= 0
        rows = controller.queue_snapshot() if has_row else []
        running = (
            has_row
            and row_idx < len(rows)
            and rows[row_idx].is_active
        )
        _apply_job_queue_action_bar_background(self, running=running)
        for btn in (
            self._edit_btn,
            self._plus_btn,
            self._minus_btn,
            self._cancel_btn,
        ):
            btn.setVisible(True)
        self._plus_btn.setEnabled(
            has_row and controller.can_add_series_cycle_for_row(row_idx)
        )
        remaining = (
            controller.series_remaining_after_for_row(row_idx) if has_row else 0
        )
        self._minus_btn.setEnabled(has_row and remaining > 0)
        image_ok = (
            has_row
            and remaining > 0
            and controller.job_row_supports_image_series_refinement(row_idx)
        )
        text_ok = (
            has_row
            and remaining > 0
            and controller.job_row_supports_text_series_refinement(row_idx)
        )
        self._image_refine_btn.blockSignals(True)
        self._image_refine_btn.setVisible(image_ok)
        if image_ok:
            self._image_refine_btn.setChecked(
                controller.series_refinement_enabled_for_row(row_idx)
            )
        else:
            self._image_refine_btn.setChecked(False)
        self._image_refine_btn.blockSignals(False)
        _sync_series_toggle_button_style(
            self._image_refine_btn, "series_image_refinement_icon.png"
        )
        self._text_refine_btn.blockSignals(True)
        self._text_refine_btn.setVisible(text_ok)
        if text_ok:
            self._text_refine_btn.setChecked(
                controller.series_prompt_refinement_enabled_for_row(row_idx)
            )
        else:
            self._text_refine_btn.setChecked(False)
        self._text_refine_btn.blockSignals(False)
        _sync_series_toggle_button_style(
            self._text_refine_btn, "series_text_refinement_icon.png"
        )
        self._edit_btn.setEnabled(has_row)
        self._cancel_btn.setEnabled(has_row)
        if self._speak_btn is not None:
            from speech_utils import is_speaking

            prompt = self._full_prompt_for_row()
            self._speak_btn.setEnabled(bool(prompt) or is_speaking())
            self._sync_speak_highlight()

    def refresh_theme_styles(self) -> None:
        rows = self._controller.queue_snapshot()
        running = (
            self._row_idx >= 0
            and self._row_idx < len(rows)
            and rows[self._row_idx].is_active
        )
        _apply_job_queue_action_bar_background(self, running=running)
        if self._speak_btn is not None:
            self._apply_speak_button_style()
        _configure_icon_push_button(self._plus_btn, "series_plus_icon.png")
        _configure_icon_push_button(self._minus_btn, "series_minus_icon.png")
        _configure_series_toggle_push_button(
            self._image_refine_btn, "series_image_refinement_icon.png"
        )
        _sync_series_toggle_button_style(
            self._image_refine_btn, "series_image_refinement_icon.png"
        )
        _configure_series_toggle_push_button(
            self._text_refine_btn, "series_text_refinement_icon.png"
        )
        _sync_series_toggle_button_style(
            self._text_refine_btn, "series_text_refinement_icon.png"
        )
        _configure_icon_push_button(self._edit_btn, "edit_icon.png")
        _configure_icon_push_button(
            self._cancel_btn, "trash_icon.png", hover_icon_name="trash_icon_hover.png"
        )


def open_reference_thumbnail_paths(main_window, paths: list[str]) -> None:
    """One image → browse; multiple → new thumbnail level."""
    valid = _valid_preview_paths(paths)
    if not valid:
        return
    if len(valid) == 1:
        open_image_in_browse(main_window, valid[0])
        return
    if hasattr(main_window, "directory_stack_history_handler"):
        main_window.directory_stack_history_handler.save_current_state(
            "open_reference_thumbnail_paths", delay=0.0
        )
    if hasattr(main_window, "refresh_from_configuration"):
        main_window.refresh_from_configuration(
            {"files": valid, "sort_mode": "custom"}
        )


def _job_queue_action_button_stylesheet(*, highlighted: bool = False) -> str:
    """Match File Information action buttons: accent border on hover."""
    th = get_active_theme()
    sz = _ICON_BTN_SIZE
    hover_border = getattr(th, "button_border_hover_hex", th.accent_color_hex)
    if highlighted:
        chip_bg, chip_hover, _, chip_border, chip_border_hover = titlebar_chip_colors()
        bg = chip_bg
        border = chip_border
        hover_bg = chip_hover
        hover_border = chip_border_hover
    else:
        bg = job_queue_action_bar_background_hex()
        border = th.information_icon_cell_border_muted_hex
        hover_bg = job_queue_cell_background_hex()
    pressed_bg = job_queue_action_bar_background_qcolor().darker(120).name()
    return f"""
        QPushButton {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            border: 1px solid {hover_border};
        }}
        QPushButton:focus {{
            border: 1px solid {th.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton:pressed {{
            background-color: {pressed_bg};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def _attach_icon_hover_swap(
    btn: QPushButton, normal_name: str, hover_name: str | None = None
) -> None:
    normal, hover = icon_pair_from_assets(normal_name, hover_name)
    swap = getattr(btn, "_icon_hover_swap", None)
    if swap is None:
        btn._icon_hover_swap = attach_icon_hover_swap(btn, normal, hover)
    else:
        swap.set_icons(normal, hover)


def _prepare_job_queue_icon_button(btn: QPushButton) -> None:
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setFixedSize(_ICON_BTN_SIZE, _ICON_BTN_SIZE)
    btn.setIconSize(QSize(_ICON_BTN_SIZE - 4, _ICON_BTN_SIZE - 4))
    btn.setFlat(False)


def _configure_icon_push_button(
    btn: QPushButton, icon_name: str, *, hover_icon_name: str | None = None
) -> None:
    _prepare_job_queue_icon_button(btn)
    btn.setStyleSheet(_job_queue_action_button_stylesheet())
    btn.setProperty("_tooltip_icon_asset", icon_name)
    _attach_icon_hover_swap(btn, icon_name, hover_icon_name)


def _apply_series_refinement_toggle(
    btn: QPushButton,
    icon_name: str,
    checked: bool,
    apply_fn,
) -> None:
    """Apply a series refinement toggle; revert the button if the controller rejects it."""
    if not apply_fn(checked):
        btn.blockSignals(True)
        btn.setChecked(not checked)
        btn.blockSignals(False)
    _sync_series_toggle_button_style(btn, icon_name)


def _configure_series_toggle_push_button(btn: QPushButton, icon_name: str) -> None:
    btn.setCheckable(True)
    btn.setProperty("_series_toggle_icon", icon_name)
    _prepare_job_queue_icon_button(btn)
    _sync_series_toggle_button_style(btn, icon_name)


def _sync_series_toggle_button_style(btn: QPushButton, icon_name: str) -> None:
    highlighted = btn.isChecked()
    btn.setStyleSheet(_job_queue_action_button_stylesheet(highlighted=highlighted))
    btn.setProperty("_tooltip_icon_asset", icon_name)
    base = icon_name.replace(".png", "")
    if highlighted:
        _attach_icon_hover_swap(
            btn,
            f"{base}_active.png",
            f"{base}_active_hover.png",
        )
    else:
        _attach_icon_hover_swap(btn, icon_name)

