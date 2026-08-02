#!/usr/bin/env python3
"""Shared job queue helpers (action buttons, previews, row HTML)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_dialog import connect_import_button_with_option_modifier
from imagegen_plugins.image_gen_source_nav import open_image_in_browse
from config import (
    job_queue_action_bar_background_hex,
    job_queue_action_bar_background_qcolor,
    job_queue_cell_background_hex,
)
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

_ACTION_COL_WIDTH = 36  # legacy export; cards no longer use side action column
_ICON_BTN_SIZE = 22
_ACTION_BAR_HEIGHT = 28


def _job_queue_cell_background_stylesheet() -> str:
    bg = job_queue_cell_background_hex()
    return f"background-color: {bg};"


def _job_queue_action_bar_background_stylesheet() -> str:
    bg = job_queue_action_bar_background_hex()
    return f"background-color: {bg};"


def _apply_job_queue_cell_background(widget: QWidget) -> None:
    widget.setStyleSheet(_job_queue_cell_background_stylesheet())
    widget.setAutoFillBackground(True)


def _apply_job_queue_action_bar_background(widget: QWidget) -> None:
    widget.setStyleSheet(_job_queue_action_bar_background_stylesheet())
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

        self._refine_btn = QPushButton()
        self._refine_btn.setCheckable(True)
        self._refine_btn.setToolTip(
            "Image Based Refinement:\n\n"
            "Base subsequent image copies on previous result image.\n\n"
            "Other source images keep their order."
        )
        self._refine_btn.setStyleSheet(_series_refinement_button_stylesheet())
        self._refine_btn.setProperty("_tooltip_icon_asset", "series_refinement_icon.png")
        self._refine_btn.toggled.connect(self._on_refine_toggled)

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
            self._plus_btn,
            self._minus_btn,
            self._refine_btn,
            self._edit_btn,
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

    def _on_refine_toggled(self, checked: bool) -> None:
        if self._row_idx >= 0:
            self._controller.set_series_refinement_for_row(self._row_idx, checked)

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
        self._plus_btn.setEnabled(
            has_row and controller.can_add_series_cycle_for_row(row_idx)
        )
        remaining = (
            controller.series_remaining_after_for_row(row_idx) if has_row else 0
        )
        self._minus_btn.setEnabled(has_row and remaining > 0)
        refine_ok = (
            has_row
            and remaining > 0
            and controller.job_row_supports_image_refinement(row_idx)
        )
        self._refine_btn.blockSignals(True)
        self._refine_btn.setEnabled(refine_ok)
        if refine_ok:
            self._refine_btn.setChecked(
                controller.series_refinement_enabled_for_row(row_idx)
            )
        else:
            self._refine_btn.setChecked(False)
        self._refine_btn.blockSignals(False)
        self._edit_btn.setEnabled(has_row)
        self._cancel_btn.setEnabled(has_row)

    def refresh_theme_styles(self) -> None:
        _apply_job_queue_action_bar_background(self)
        _configure_icon_push_button(self._plus_btn, "series_plus_icon.png")
        _configure_icon_push_button(self._minus_btn, "series_minus_icon.png")
        self._refine_btn.setStyleSheet(_series_refinement_button_stylesheet())
        self._refine_btn.setProperty("_tooltip_icon_asset", "series_refinement_icon.png")
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
        refine_btn = QPushButton()
        refine_btn.setCheckable(True)
        refine_btn.setToolTip(
            "Image Based Refinement:\n\n"
            "Base subsequent image copies on previous result image.\n\n"
            "Other source images keep their order."
        )
        refine_btn.setStyleSheet(_series_refinement_button_stylesheet())
        refine_btn.setProperty("_tooltip_icon_asset", "series_refinement_icon.png")
        refine_btn.blockSignals(True)
        refine_btn.setChecked(controller.series_refinement_enabled_for_row(row_idx))
        refine_btn.blockSignals(False)
        refine_btn.toggled.connect(
            lambda checked, r=row_idx: controller.set_series_refinement_for_row(
                r, checked
            )
        )
        action_layout.addWidget(minus_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(refine_btn, alignment=Qt.AlignmentFlag.AlignCenter)
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


def _icon_push_button_stylesheet(icon_name: str, *, hover_icon_name: str | None = None) -> str:
    t = get_active_theme()
    icon_url = f"url({asset_path(icon_name)})"
    hover_name = hover_icon_name or icon_name.replace(".png", "_hover.png")
    hover_url = f"url({asset_path(hover_name)})"
    sz = _ICON_BTN_SIZE
    btn_bg = job_queue_action_bar_background_hex()
    btn_hover = job_queue_cell_background_hex()
    btn_pressed = job_queue_action_bar_background_qcolor().darker(120).name()
    return f"""
        QPushButton {{
            background-color: {btn_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {btn_hover};
            border: 1px solid {t.border_default_hex};
            image: {hover_url};
        }}
        QPushButton:pressed {{
            background-color: {btn_pressed};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def _configure_icon_push_button(
    btn: QPushButton, icon_name: str, *, hover_icon_name: str | None = None
) -> None:
    btn.setStyleSheet(_icon_push_button_stylesheet(icon_name, hover_icon_name=hover_icon_name))
    btn.setProperty("_tooltip_icon_asset", icon_name)


def _trash_button_stylesheet() -> str:
    return _icon_push_button_stylesheet(
        "trash_icon.png", hover_icon_name="trash_icon_hover.png"
    )


def _edit_button_stylesheet() -> str:
    return _icon_push_button_stylesheet("edit_icon.png")


def _series_plus_button_stylesheet() -> str:
    return _icon_push_button_stylesheet("series_plus_icon.png")


def _series_minus_button_stylesheet() -> str:
    return _icon_push_button_stylesheet("series_minus_icon.png")


def _series_refinement_button_stylesheet() -> str:
    active_url = f"url({asset_path('series_refinement_icon_active.png')})"
    active_hover_url = f"url({asset_path('series_refinement_icon_active_hover.png')})"
    btn_hover = job_queue_cell_background_hex()
    return _icon_push_button_stylesheet("series_refinement_icon.png") + f"""
        QPushButton:checked:hover {{
            background-color: {btn_hover};
            border: 1px solid {get_active_theme().border_default_hex};
            image: {active_hover_url};
        }}
        QPushButton:checked {{
            image: {active_url};
        }}
    """
