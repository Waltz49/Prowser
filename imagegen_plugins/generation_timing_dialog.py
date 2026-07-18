#!/usr/bin/env python3
"""Tools > Debug > See timings — saved generation timing averages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from imagegen_plugins.generation_timing_stats import list_timing_rows
from imagegen_plugins.model_task_status_info import _format_duration
from utils import (
    ensure_dialog_fits_screen,
    get_button_style,
    get_dialog_shell_stylesheet,
)

_RIGHT_ALIGN = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


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
        self.setWindowTitle("Generation Timings")
        self.setMinimumSize(720, 360)
        self.resize(860, 420)
        self.setModal(False)

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 7, self)
        self._table.setHorizontalHeaderLabels(
            ["Model", "Size", "Steps", "Quant", "Runs", "Total Time", "Time"]
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
        for column in range(1, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
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
        self._reload_rows()

    def _reload_rows(self) -> None:
        rows = list_timing_rows()
        sort_column = self._table.horizontalHeader().sortIndicatorSection()
        sort_order = self._table.horizontalHeader().sortIndicatorOrder()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self._table.setItem(row_index, 0, _TextSortItem(row.model_name))
            self._table.setItem(
                row_index,
                1,
                _NumericSortItem(row.size, row.width * row.height),
            )
            self._table.setItem(
                row_index,
                2,
                _NumericSortItem(str(row.steps), row.steps),
            )
            self._table.setItem(
                row_index,
                3,
                _TextSortItem(row.quant, right_align=True),
            )
            self._table.setItem(
                row_index,
                4,
                _NumericSortItem(str(row.run_count), row.run_count),
            )
            self._table.setItem(
                row_index,
                5,
                _NumericSortItem(
                    _format_duration(row.total_seconds),
                    row.total_seconds,
                ),
            )
            self._table.setItem(
                row_index,
                6,
                _NumericSortItem(
                    _format_duration(row.avg_seconds),
                    row.avg_seconds,
                ),
            )
        self._table.setSortingEnabled(True)
        if sort_column >= 0:
            self._table.sortItems(sort_column, sort_order)


def show_generation_timing_dialog(parent=None) -> GenerationTimingDialog:
    dialog = GenerationTimingDialog(parent)
    ensure_dialog_fits_screen(dialog)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
