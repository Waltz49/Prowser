#!/usr/bin/env python3
"""Tools > Debug > See timings — saved generation timing averages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import get_config
from imagegen_plugins.generation_timing_stats import list_timing_rows
from imagegen_plugins.model_task_status_info import _format_duration
from list_models import _clear_filter_icon, _configure_filter_clear_button
from utils import (
    ensure_dialog_fits_screen,
    get_button_style,
    get_dialog_shell_stylesheet,
    restore_dialog_geometry_before_first_show,
    save_dialog_geometry_hex,
)

_GEOMETRY_KEY = "generation_timing_dialog_geometry"
_AREA_K = 1000
_COL_TOTAL_TIME = 6

_RIGHT_ALIGN = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def _format_area_k(width: int, height: int) -> tuple[str, float]:
    area = width * height
    return f"{area / _AREA_K:.1f}K", float(area)


class _NumericSortItem(QTableWidgetItem):
    """Table item that sorts by a numeric value instead of display text."""

    def __init__(self, text: str, sort_value: float | int):
        super().__init__(text)
        self._sort_value = sort_value
        self.setTextAlignment(_RIGHT_ALIGN)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _NumericSortItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


class _TextSortItem(QTableWidgetItem):
    def __init__(self, text: str, *, right_align: bool = False):
        super().__init__(text)
        if right_align:
            self.setTextAlignment(_RIGHT_ALIGN)


class GenerationTimingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = parent.config if (parent and hasattr(parent, "config")) else get_config()
        self._geometry_restore_attempted = False

        self.setWindowTitle("Generation Timings")
        self.setMinimumSize(720, 360)
        self.resize(860, 420)
        self.setModal(False)

        layout = QVBoxLayout(self)

        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        filter_layout.addWidget(QLabel("Filter:"))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter models…")
        self.filter_edit.setMinimumWidth(220)
        self.filter_edit.textChanged.connect(self._apply_model_filter)

        self.filter_clear_btn = QPushButton()
        self.filter_clear_btn.setIcon(_clear_filter_icon())
        self.filter_clear_btn.setIconSize(QSize(18, 18))
        self.filter_clear_btn.setFixedSize(24, 24)
        self.filter_clear_btn.setFlat(True)
        self.filter_clear_btn.setToolTip("Clear filter")
        self.filter_clear_btn.setEnabled(False)
        self.filter_clear_btn.clicked.connect(self.filter_edit.clear)
        self.filter_edit.textChanged.connect(
            lambda text: self.filter_clear_btn.setEnabled(bool(text))
        )

        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.filter_clear_btn)
        filter_layout.addStretch(1)
        layout.addWidget(filter_widget)

        self._table = QTableWidget(0, 8, self)
        self._table.setHorizontalHeaderLabels(
            ["Model", "Size", "Area", "Steps", "Quant", "Runs", "Total Time", "Time"]
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnHidden(_COL_TOTAL_TIME, True)
        layout.addWidget(self._table)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(get_button_style())
        refresh_btn.clicked.connect(self._reload_rows)
        button_row.addWidget(refresh_btn)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(get_button_style())
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.setStyleSheet(get_dialog_shell_stylesheet())
        _configure_filter_clear_button(self)
        self.finished.connect(self._save_geometry)
        self._reload_rows()

    def showEvent(self, event) -> None:
        if not self._geometry_restore_attempted:
            geom_hex = self._config.load_settings().get(_GEOMETRY_KEY)
            restore_dialog_geometry_before_first_show(self, geom_hex, self.parent())
        super().showEvent(event)
        ensure_dialog_fits_screen(self, self.parent())

    def _save_geometry(self, *_args) -> None:
        try:
            self._config.update_setting(_GEOMETRY_KEY, save_dialog_geometry_hex(self))
        except Exception:
            pass

    def _reload_rows(self) -> None:
        rows = list_timing_rows()
        sort_column = self._table.horizontalHeader().sortIndicatorSection()
        sort_order = self._table.horizontalHeader().sortIndicatorOrder()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            area_text, area_sort = _format_area_k(row.width, row.height)
            self._table.setItem(row_index, 0, _TextSortItem(row.model_name))
            self._table.setItem(
                row_index,
                1,
                _NumericSortItem(row.size, row.width * row.height),
            )
            self._table.setItem(
                row_index,
                2,
                _NumericSortItem(area_text, area_sort),
            )
            self._table.setItem(
                row_index,
                3,
                _NumericSortItem(str(row.steps), row.steps),
            )
            self._table.setItem(
                row_index,
                4,
                _TextSortItem(row.quant, right_align=True),
            )
            self._table.setItem(
                row_index,
                5,
                _NumericSortItem(str(row.run_count), row.run_count),
            )
            self._table.setItem(
                row_index,
                6,
                _NumericSortItem(
                    _format_duration(row.total_seconds),
                    row.total_seconds,
                ),
            )
            self._table.setItem(
                row_index,
                7,
                _NumericSortItem(
                    _format_duration(row.avg_seconds),
                    row.avg_seconds,
                ),
            )
        self._table.setSortingEnabled(True)
        if sort_column >= 0:
            self._table.sortItems(sort_column, sort_order)
        self._apply_model_filter()

    def _apply_model_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        for row in range(self._table.rowCount()):
            if not needle:
                self._table.setRowHidden(row, False)
                continue
            item = self._table.item(row, 0)
            model_name = (item.text() if item else "").lower()
            self._table.setRowHidden(row, needle not in model_name)


def show_generation_timing_dialog(parent=None) -> GenerationTimingDialog:
    dialog = GenerationTimingDialog(parent)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
