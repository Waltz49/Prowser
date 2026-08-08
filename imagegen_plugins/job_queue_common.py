#!/usr/bin/env python3
"""Shared job queue helpers (action buttons, previews, row HTML)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_dialog import connect_import_button_with_option_modifier
from imagegen_plugins.image_gen_source_nav import open_image_in_browse
from config import (
    job_queue_action_bar_background_hex,
    job_queue_action_bar_background_qcolor,
    job_queue_cell_background_hex,
    job_queue_running_cell_background_hex,
)
from theme.theme_service import get_active_theme
from theme.titlebar_icons import titlebar_chip_colors
from widgets.icon_hover_swap import attach_icon_hover_swap, icon_pair_from_assets

_ACTION_COL_WIDTH = 36  # legacy export; cards no longer use side action column
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
        _apply_job_queue_action_bar_background(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        self._layout = layout

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
            "Other source images keep their order."
        )
        _configure_series_toggle_push_button(
            self._image_refine_btn, "series_image_refinement_icon.png"
        )
        self._image_refine_btn.toggled.connect(self._on_image_refine_toggled)
        self._image_refine_btn.toggled.connect(
            lambda _checked: _sync_series_toggle_button_style(
                self._image_refine_btn, "series_image_refinement_icon.png"
            )
        )

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
        self._text_refine_btn.toggled.connect(
            lambda _checked: _sync_series_toggle_button_style(
                self._text_refine_btn, "series_text_refinement_icon.png"
            )
        )

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
        if self._row_idx >= 0:
            self._controller.set_series_refinement_for_row(self._row_idx, checked)

    def _on_text_refine_toggled(self, checked: bool) -> None:
        if self._row_idx >= 0:
            self._controller.set_series_prompt_refinement_for_row(
                self._row_idx, checked
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

    def refresh_theme_styles(self) -> None:
        rows = self._controller.queue_snapshot()
        running = (
            self._row_idx >= 0
            and self._row_idx < len(rows)
            and rows[self._row_idx].is_active
        )
        _apply_job_queue_action_bar_background(self, running=running)
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


def build_job_queue_action_widget(
    main_window,
    controller,
    row_idx: int,
    *,
    is_active: bool,
) -> QWidget:
    """Action column: series controls, edit, cancel (active and queued rows)."""
    _ = is_active
    edit_btn = QPushButton()
    edit_btn.setToolTip(
        "Replicate job settings…\n"
        "For a pending job, use Replace in the dialog to update it in place.\n"
        "For a running batch job, use Update to change remaining copies."
    )
    _configure_icon_push_button(edit_btn, "edit_icon.png")
    edit_btn.clicked.connect(
        lambda _checked=False, r=row_idx: job_queue_edit_row(main_window, controller, r)
    )
    cancel_btn = QPushButton()
    cancel_btn.setToolTip(
        "Cancel job\n"
        "Option+click to cancel this job and all jobs after it (no confirmation)."
    )
    _configure_icon_push_button(
        cancel_btn, "trash_icon.png", hover_icon_name="trash_icon_hover.png"
    )
    connect_import_button_with_option_modifier(
        cancel_btn,
        lambda option_held=False, r=row_idx: job_queue_cancel_row(
            main_window, controller, r, option_held=option_held
        ),
    )
    action_wrap = QWidget()
    action_wrap.setObjectName(_ACTION_BAR_OBJECT_NAME)
    _apply_job_queue_action_bar_background(action_wrap)
    action_layout = QVBoxLayout(action_wrap)
    action_layout.setContentsMargins(2, 0, 2, 0)
    action_layout.setSpacing(2)

    plus_btn = QPushButton()
    plus_btn.setToolTip("Add another image to this series")
    _configure_icon_push_button(plus_btn, "series_plus_icon.png")
    plus_btn.setEnabled(controller.can_add_series_cycle_for_row(row_idx))
    plus_btn.clicked.connect(
        lambda _checked=False, r=row_idx: controller.add_series_cycle_for_row(r)
    )
    has_waiting_cycles = controller.series_remaining_after_for_row(row_idx) > 0
    action_layout.addWidget(plus_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    if has_waiting_cycles:
        minus_btn = QPushButton()
        minus_btn.setToolTip(
            "Remove one pending image from the series.\n"
            "Option+click to remove all remaining images."
        )
        _configure_icon_push_button(minus_btn, "series_minus_icon.png")
        connect_import_button_with_option_modifier(
            minus_btn,
            lambda option_held=False, r=row_idx: (
                controller.clear_series_remaining_for_row(r)
                if option_held
                else controller.subtract_series_remaining_for_row(r)
            ),
        )
        image_ok = controller.job_row_supports_image_series_refinement(row_idx)
        text_ok = controller.job_row_supports_text_series_refinement(row_idx)
        action_layout.addWidget(minus_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        if image_ok:
            image_refine_btn = QPushButton()
            image_refine_btn.setToolTip(
                "Image Based Refinement:\n\n"
                "Base subsequent image copies on previous result image.\n\n"
                "Other source images keep their order."
            )
            _configure_series_toggle_push_button(
                image_refine_btn, "series_image_refinement_icon.png"
            )
            image_refine_btn.blockSignals(True)
            image_refine_btn.setChecked(
                controller.series_refinement_enabled_for_row(row_idx)
            )
            image_refine_btn.blockSignals(False)
            image_refine_btn.toggled.connect(
                lambda checked, r=row_idx: controller.set_series_refinement_for_row(
                    r, checked
                )
            )
            image_refine_btn.toggled.connect(
                lambda _checked, btn=image_refine_btn: _sync_series_toggle_button_style(
                    btn, "series_image_refinement_icon.png"
                )
            )
            _sync_series_toggle_button_style(
                image_refine_btn, "series_image_refinement_icon.png"
            )
            action_layout.addWidget(
                image_refine_btn, alignment=Qt.AlignmentFlag.AlignCenter
            )
        if text_ok:
            text_refine_btn = QPushButton()
            text_refine_btn.setToolTip(
                "Text Based Refinement:\n\n"
                "Re-run the previous prompt through Gen Prompt AI before each\n"
                "subsequent copy in the series."
            )
            _configure_series_toggle_push_button(
                text_refine_btn, "series_text_refinement_icon.png"
            )
            text_refine_btn.blockSignals(True)
            text_refine_btn.setChecked(
                controller.series_prompt_refinement_enabled_for_row(row_idx)
            )
            text_refine_btn.blockSignals(False)
            text_refine_btn.toggled.connect(
                lambda checked, r=row_idx: controller.set_series_prompt_refinement_for_row(
                    r, checked
                )
            )
            text_refine_btn.toggled.connect(
                lambda _checked, btn=text_refine_btn: _sync_series_toggle_button_style(
                    btn, "series_text_refinement_icon.png"
                )
            )
            _sync_series_toggle_button_style(
                text_refine_btn, "series_text_refinement_icon.png"
            )
            action_layout.addWidget(
                text_refine_btn, alignment=Qt.AlignmentFlag.AlignCenter
            )
    action_layout.addWidget(edit_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    action_layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    action_wrap.setFixedWidth(_ACTION_COL_WIDTH)
    return action_wrap


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


def _trash_button_stylesheet() -> str:
    return _job_queue_action_button_stylesheet()


def _edit_button_stylesheet() -> str:
    return _job_queue_action_button_stylesheet()


def _series_plus_button_stylesheet() -> str:
    return _job_queue_action_button_stylesheet()


def _series_minus_button_stylesheet() -> str:
    return _job_queue_action_button_stylesheet()


def _series_refinement_button_stylesheet() -> str:
    return _job_queue_action_button_stylesheet()
