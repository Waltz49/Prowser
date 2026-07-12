#!/usr/bin/env python3
"""Dry-run rename plan dialog for convert format conflicts."""

import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from files.convert_conflict_auto_rename import (
    CONVERT_CONFLICT_RENAME_APPLY_ENABLED,
    ConvertConflictRenamePlanEntry,
    apply_convert_conflict_renames,
)
from theme.theme_service import get_active_theme
from utils import (
    create_dialog_thumbnail_label,
    file_string,
    get_button_style,
    show_styled_information,
)

_PLAN_THUMB_SIZE = 72


def _open_plan_thumbnail_in_browse(main_window, file_path: str) -> None:
    """Show file in browse view behind the plan dialog (dialog stays open)."""
    path = (file_path or "").strip()
    if not path or not os.path.isfile(path):
        return

    displayed = list(getattr(main_window, "displayed_images", None) or [])
    if path in displayed:
        idx = displayed.index(path)
        vm = getattr(main_window, "view_mode_manager", None)
        if vm and hasattr(vm, "open_browse_view"):
            vm.open_browse_view(idx)
        elif hasattr(main_window, "open_browse_view"):
            main_window.open_browse_view(idx)
        return

    if getattr(main_window, "current_view_mode", None) != "browse":
        if hasattr(main_window, "stacked_widget"):
            main_window.stacked_widget.setCurrentIndex(1)
        main_window.current_view_mode = "browse"
        if hasattr(main_window, "manage_sidebar_visibility_for_view_mode"):
            main_window.manage_sidebar_visibility_for_view_mode("browse")
        if hasattr(main_window, "browse_view_action"):
            main_window.browse_view_action.setEnabled(False)
        if hasattr(main_window, "view_manager"):
            main_window.view_manager._setup_cursor_manager()

    if hasattr(main_window, "_set_current_image_path_with_sync"):
        main_window._set_current_image_path_with_sync(path)
    elif hasattr(main_window, "current_image_path"):
        main_window.current_image_path = path

    if hasattr(main_window, "show_image"):
        main_window.show_image(path, 0)


def _make_clickable_plan_thumbnail(
    main_window,
    file_path: str,
    size: int,
) -> QLabel:
    thumb = create_dialog_thumbnail_label(file_path, size)
    if not main_window:
        return thumb
    thumb.setCursor(Qt.CursorShape.PointingHandCursor)
    thumb.setToolTip(
        f"{os.path.basename(file_path)}\nClick to open in browse view"
    )

    def _on_mouse_press(event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            _open_plan_thumbnail_in_browse(main_window, file_path)
            event.accept()
            return
        QLabel.mousePressEvent(thumb, event)

    thumb.mousePressEvent = _on_mouse_press
    return thumb


def _make_filename_with_thumbnail_cell(
    main_window,
    thumb_path: str,
    label_text: str,
    label_tooltip: str,
    size: int,
) -> QWidget:
    """Row cell with clickable thumbnail and filename label."""
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(4, 4, 8, 4)
    row.setSpacing(8)
    row.addWidget(_make_clickable_plan_thumbnail(main_window, thumb_path, size))
    name_label = QLabel(label_text)
    name_label.setToolTip(label_tooltip)
    name_label.setWordWrap(True)
    row.addWidget(name_label, 1)
    return wrapper


class ConvertConflictRenamePlanDialog(QDialog):
    """Table of proposed target renames with per-row selection."""

    def __init__(
        self,
        rename_plan: List[ConvertConflictRenamePlanEntry],
        unresolved: List[str],
        parent=None,
        main_window=None,
    ):
        super().__init__(parent)
        self.rename_plan = list(rename_plan)
        self.unresolved = list(unresolved)
        self.main_window = main_window
        self._row_checkboxes: List[QCheckBox] = []
        self._blocking_select_all_sync = False

        th = get_active_theme()
        bg_color = th.dialog_background_hex
        text_color = th.dialog_text_color_hex
        border_color = th.border_default_hex
        focus_border = th.current_image_border_color_hex
        button_bg_default = th.button_bg_default_hex
        button_text_default = th.button_text_default_hex
        button_border_default = th.button_border_default_hex
        button_bg_hover = th.button_bg_hover_hex
        button_text_hover = th.button_text_hover_hex
        button_border_hover = th.button_border_hover_hex
        button_bg_pressed = th.button_bg_pressed_hex
        button_focus_text = th.button_focus_text_hex
        text_disabled = th.text_disabled_hex
        widget_bg_disabled = th.widget_bg_disabled_hex
        dialog_background = th.dialog_background_hex

        self.setWindowTitle("Rename Suggestions")
        self.setMinimumWidth(900)
        self.setMinimumHeight(420)
        self.setModal(False)

        self.setStyleSheet(f"""
            QDialog, QDialog QWidget {{
                background-color: {bg_color};
                color: {text_color};
            }}
            QLabel {{
                font-size: 13px;
                color: {text_color};
            }}
            QPushButton {{
                background-color: {button_bg_default};
                color: {button_text_default};
                border: 1px solid {button_border_default};
                border-radius: 5px;
                padding: 6px 18px;
                min-width: 100px;
                font-size: 13px;
                font-family: 'Arial Narrow', Arial;
                letter-spacing: 0.5px;
            }}
            QPushButton:focus {{
                background-color: {bg_color};
                color: {button_focus_text};
                border: 1px solid {focus_border};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {button_bg_hover};
                color: {button_text_hover};
                border: 1px solid {button_border_hover};
            }}
            QPushButton:pressed {{
                background-color: {button_bg_pressed};
                color: {button_focus_text};
            }}
            QPushButton:disabled {{
                color: {text_disabled};
                background-color: {widget_bg_disabled};
                border-color: {dialog_background};
            }}
            QTableWidget {{
                background-color: {button_bg_default};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 5px;
                gridline-color: {border_color};
                font-size: 12px;
            }}
            QHeaderView::section {{
                background-color: {bg_color};
                color: {text_color};
                border: 1px solid {border_color};
                padding: 4px 8px;
                font-size: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        plan_count = len(rename_plan)
        if plan_count:
            summary = (
                f"{plan_count} source {file_string(plan_count)} can be renamed "
                f"with names based on similar images in the directory."
            )
        else:
            summary = "No rename proposals were generated."

        info_label = QLabel(summary)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        select_all_row = QHBoxLayout()
        select_all_row.setContentsMargins(4, 0, 4, 0)
        self.select_all_checkbox = QCheckBox()
        self.select_all_checkbox.setChecked(bool(rename_plan))
        self.select_all_checkbox.clicked.connect(self._on_select_all_clicked)
        select_all_row.addWidget(self.select_all_checkbox)
        select_all_label = QLabel(
            "Select all (or deselect if all are already selected)"
        )
        select_all_label.setWordWrap(True)
        select_all_row.addWidget(select_all_label, 1)
        layout.addLayout(select_all_row)

        self.table = QTableWidget(len(rename_plan), 3, self)
        self.table.setHorizontalHeaderLabels(
            ["", "Filename", "Like named image"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        thumb_row_height = _PLAN_THUMB_SIZE + 12
        self.table.verticalHeader().setDefaultSectionSize(thumb_row_height)

        for row, entry in enumerate(rename_plan):
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_row_checkbox_changed)
            self._row_checkboxes.append(cb)
            self.table.setCellWidget(row, 0, self._center_checkbox(cb))

            old_name = os.path.basename(entry.old_path)
            new_name = os.path.basename(entry.new_path)
            rename_label = f"{old_name} → {new_name}"
            rename_tooltip = f"{entry.old_path}\n→\n{entry.new_path}"

            self.table.setCellWidget(
                row,
                1,
                _make_filename_with_thumbnail_cell(
                    main_window,
                    entry.old_path,
                    rename_label,
                    rename_tooltip,
                    _PLAN_THUMB_SIZE,
                ),
            )

            self.table.setCellWidget(
                row,
                2,
                _make_filename_with_thumbnail_cell(
                    main_window,
                    entry.similar_path,
                    os.path.basename(entry.similar_path),
                    entry.similar_path,
                    _PLAN_THUMB_SIZE,
                ),
            )

        layout.addWidget(self.table)

        if unresolved:
            unresolved_label = QLabel(
                "Unresolved (no similar image in directory):\n"
                + "\n".join(f"  • {os.path.basename(p)}" for p in unresolved)
            )
            unresolved_label.setWordWrap(True)
            layout.addWidget(unresolved_label)

        button_row = QHBoxLayout()

        close_button = QPushButton("Close")
        close_button.setStyleSheet(get_button_style())
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        button_row.addStretch()

        self.rename_button = QPushButton("Rename")
        self.rename_button.setStyleSheet(get_button_style())
        self.rename_button.clicked.connect(self._on_rename_clicked)
        self._update_rename_button_state()
        button_row.addWidget(self.rename_button)

        layout.addLayout(button_row)

        close_button.setFocus()

    @staticmethod
    def _center_checkbox(checkbox: QCheckBox) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(checkbox)
        row.addStretch()
        return wrapper

    def _on_select_all_clicked(self):
        if self._blocking_select_all_sync:
            return
        all_checked = self._all_rows_checked()
        target_checked = not all_checked
        self._blocking_select_all_sync = True
        try:
            for cb in self._row_checkboxes:
                cb.setChecked(target_checked)
            self.select_all_checkbox.setChecked(target_checked)
        finally:
            self._blocking_select_all_sync = False
        self._update_rename_button_state()

    def _on_row_checkbox_changed(self, _state):
        if self._blocking_select_all_sync:
            return
        self._blocking_select_all_sync = True
        try:
            self.select_all_checkbox.setChecked(self._all_rows_checked())
        finally:
            self._blocking_select_all_sync = False
        self._update_rename_button_state()

    def _all_rows_checked(self) -> bool:
        return bool(self._row_checkboxes) and all(cb.isChecked() for cb in self._row_checkboxes)

    def _selected_entries(self) -> List[ConvertConflictRenamePlanEntry]:
        selected: List[ConvertConflictRenamePlanEntry] = []
        for row, cb in enumerate(self._row_checkboxes):
            if cb.isChecked() and row < len(self.rename_plan):
                selected.append(self.rename_plan[row])
        return selected

    def _update_rename_button_state(self):
        if not CONVERT_CONFLICT_RENAME_APPLY_ENABLED:
            self.rename_button.setEnabled(False)
            self.rename_button.setToolTip("Rename apply is not enabled yet.")
            return
        has_selection = bool(self._selected_entries())
        self.rename_button.setEnabled(has_selection)
        self.rename_button.setToolTip("" if has_selection else "Select at least one row.")

    def _on_rename_clicked(self):
        if not CONVERT_CONFLICT_RENAME_APPLY_ENABLED:
            return
        entries = self._selected_entries()
        if not entries or not self.main_window:
            return

        count, errors = apply_convert_conflict_renames(self.main_window, entries)
        if errors and count == 0:
            return
        if count:
            show_styled_information(
                self.main_window,
                "Rename Complete",
                f"Renamed {count} {file_string(count)}.",
            )
            self.accept()

    @staticmethod
    def show_confirmation(
        rename_plan: List[ConvertConflictRenamePlanEntry],
        unresolved: List[str],
        parent=None,
        main_window=None,
    ) -> bool:
        dialog = ConvertConflictRenamePlanDialog(
            rename_plan,
            unresolved,
            parent,
            main_window=main_window,
        )
        return dialog.exec() == QDialog.Accepted
