#!/usr/bin/env python3
"""Shared job queue helpers (action buttons, previews, row HTML)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_dialog import connect_import_button_with_option_modifier
from imagegen_plugins.image_gen_source_nav import open_image_in_browse
from config import (
    job_queue_action_bar_background_hex,
    job_queue_action_bar_background_qcolor,
    job_queue_cell_background_hex,
)
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

_ACTION_COL_WIDTH = 36
_ICON_BTN_SIZE = 22


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
    edit_btn.setStyleSheet(_edit_button_stylesheet())
    edit_btn.clicked.connect(
        lambda _checked=False, r=row_idx: job_queue_edit_row(main_window, controller, r)
    )
    cancel_btn = QPushButton()
    cancel_btn.setToolTip(
        "Cancel job\n"
        "Option+click to cancel this job and all jobs after it (no confirmation)."
    )
    cancel_btn.setStyleSheet(_trash_button_stylesheet())
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
    plus_btn.setStyleSheet(_series_plus_button_stylesheet())
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
        minus_btn.setStyleSheet(_series_minus_button_stylesheet())
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
            "Refinement: replace the first source image with each new result "
            "for later copies; other source images keep their order."
        )
        refine_btn.setStyleSheet(_series_refinement_button_stylesheet())
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
