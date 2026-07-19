#!/usr/bin/env python3
"""Tools > Debug > See timings — saved generation timing averages."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from PySide6.QtCore import Qt, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPaintEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import get_config
from imagegen_plugins.generation_timing_stats import GenerationTimingRow, list_timing_rows
from imagegen_plugins.model_task_status_info import _format_duration
from list_models import _clear_filter_icon, _configure_filter_clear_button
from theme.theme_service import get_active_theme
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
_CHART_MIN_HEIGHT = 120
_POINT_SIZE = 5

_RIGHT_ALIGN = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

_SERIES_COLORS = (
    QColor("#4e79a7"),
    QColor("#f28e2b"),
    QColor("#e15759"),
    QColor("#76b7b2"),
    QColor("#59a14f"),
    QColor("#edc948"),
    QColor("#b07aa1"),
    QColor("#ff9da7"),
    QColor("#9c755f"),
    QColor("#bab0ac"),
)


def _format_area_k(width: int, height: int) -> tuple[str, float]:
    area = width * height
    return f"{area / _AREA_K:.1f}K", float(area)


def _combo_label(steps: int, quant: str, lora_stack: tuple[str, ...]) -> str:
    lora_label = ",".join(lora_stack) if lora_stack else "(none)"
    quant_label = quant or "(none)"
    return f"{steps}:{quant_label}:{lora_label}"


def _padded_range(vmin: float, vmax: float, *, padding: float = 0.08) -> tuple[float, float]:
    if vmax <= vmin:
        mid = vmax if vmax > 0 else 1.0
        return 0.0, mid * 1.1
    span = vmax - vmin
    pad = span * padding
    return vmin - pad, vmax + pad


def _tick_values(vmin: float, vmax: float, count: int = 5) -> list[float]:
    if count < 2 or vmax <= vmin:
        return [vmin] if vmax <= vmin else [vmin, vmax]
    step = (vmax - vmin) / (count - 1)
    return [vmin + step * i for i in range(count)]


def _format_area_tick(area: float) -> str:
    return f"{area / _AREA_K:.1f}K"


def _format_time_tick(seconds: float) -> str:
    return _format_duration(max(0.0, seconds))


@dataclass
class _ChartSeries:
    label: str
    color: QColor
    points: list[tuple[float, float]]


class _AreaTimeChart(QWidget):
    """Manually drawn area (x) vs time (y) chart with legend."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series: list[_ChartSeries] = []
        self.setMinimumHeight(_CHART_MIN_HEIGHT)

    def set_series(self, series: list[_ChartSeries]) -> None:
        self._series = list(series)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme = get_active_theme()
        bg = QColor(theme.dialog_background_hex)
        text = QColor(theme.dialog_text_color_hex)
        grid = QColor(text)
        grid.setAlpha(40)

        painter.fillRect(self.rect(), bg)

        margin_left = 48
        margin_bottom = 36
        margin_top = 8
        margin_right = 120

        plot = QRect(
            margin_left,
            margin_top,
            max(1, self.width() - margin_left - margin_right),
            max(1, self.height() - margin_top - margin_bottom),
        )
        legend_left = plot.right() + 8

        if not self._series or plot.width() < 20 or plot.height() < 20:
            painter.setPen(text)
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No chart data")
            return

        all_areas = [area for series in self._series for area, _ in series.points]
        all_times = [time for series in self._series for _, time in series.points]
        area_min, area_max = _padded_range(min(all_areas), max(all_areas))
        time_min, time_max = _padded_range(min(all_times), max(all_times))

        def map_x(area: float) -> float:
            if area_max <= area_min:
                return plot.left() + plot.width() / 2.0
            return plot.left() + (area - area_min) / (area_max - area_min) * plot.width()

        def map_y(seconds: float) -> float:
            if time_max <= time_min:
                return plot.top() + plot.height() / 2.0
            return plot.bottom() - (seconds - time_min) / (time_max - time_min) * plot.height()

        axis_pen = QPen(text, 1)
        painter.setPen(axis_pen)
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())
        painter.drawLine(plot.bottomLeft(), plot.topLeft())

        tick_font = QFont(painter.font())
        tick_font.setPointSize(max(8, tick_font.pointSize() - 1))
        painter.setFont(tick_font)
        metrics = painter.fontMetrics()

        for tick in _tick_values(area_min, area_max):
            x = int(map_x(tick))
            painter.setPen(axis_pen)
            painter.drawLine(x, plot.bottom(), x, plot.bottom() + 4)
            painter.setPen(grid)
            painter.drawLine(x, plot.top(), x, plot.bottom())
            label = _format_area_tick(tick)
            label_w = metrics.horizontalAdvance(label)
            painter.setPen(text)
            painter.drawText(x - label_w // 2, plot.bottom() + 16, label)

        for tick in _tick_values(time_min, time_max):
            y = int(map_y(tick))
            painter.setPen(axis_pen)
            painter.drawLine(plot.left() - 4, y, plot.left(), y)
            painter.setPen(grid)
            painter.drawLine(plot.left(), y, plot.right(), y)
            label = _format_time_tick(tick)
            label_w = metrics.horizontalAdvance(label)
            painter.setPen(text)
            painter.drawText(plot.left() - 8 - label_w, y + metrics.ascent() // 2, label)

        title_font = QFont(painter.font())
        title_font.setBold(True)
        painter.setFont(title_font)

        x_title = "Area (K px)"
        x_title_w = metrics.horizontalAdvance(x_title)
        painter.setPen(text)
        painter.drawText(
            plot.left() + (plot.width() - x_title_w) // 2,
            self.height() - 4,
            x_title,
        )

        painter.save()
        painter.translate(14, plot.top() + plot.height() // 2)
        painter.rotate(-90)
        y_title = "Time (mm:ss)"
        y_title_w = metrics.horizontalAdvance(y_title)
        painter.drawText(-y_title_w // 2, 0, y_title)
        painter.restore()

        half_point = _POINT_SIZE / 2.0
        for series in self._series:
            mapped = [(map_x(area), map_y(seconds)) for area, seconds in series.points]
            line_pen = QPen(series.color, 2)
            painter.setPen(line_pen)
            if len(mapped) >= 2:
                for index in range(len(mapped) - 1):
                    x1, y1 = mapped[index]
                    x2, y2 = mapped[index + 1]
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))

            painter.setBrush(series.color)
            painter.setPen(QPen(series.color.darker(120), 1))
            for x, y in mapped:
                painter.drawRect(
                    QRectF(x - half_point, y - half_point, _POINT_SIZE, _POINT_SIZE)
                )

        legend_font = QFont(painter.font())
        legend_font.setBold(False)
        legend_font.setPointSize(max(8, legend_font.pointSize() - 1))
        painter.setFont(legend_font)
        legend_metrics = painter.fontMetrics()
        legend_y = plot.top()
        legend_row_h = max(14, legend_metrics.height() + 2)
        legend_square = 8
        legend_text_w = max(1, self.width() - legend_left - 4)

        for series in self._series:
            if legend_y + legend_row_h > plot.bottom() + 1:
                break
            painter.setBrush(series.color)
            painter.setPen(QPen(series.color.darker(120), 1))
            painter.drawRect(legend_left, legend_y + 2, legend_square, legend_square)
            painter.setPen(text)
            elided = legend_metrics.elidedText(
                series.label,
                Qt.TextElideMode.ElideRight,
                legend_text_w - legend_square - 6,
            )
            painter.drawText(
                legend_left + legend_square + 4,
                legend_y + legend_metrics.ascent() + 1,
                elided,
            )
            legend_y += legend_row_h


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

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._apply_splitter_theme()

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
        self._table.cellDoubleClicked.connect(self._filter_to_model_row)

        self._area_chart = _AreaTimeChart(self)
        self._area_chart.hide()

        self._splitter.addWidget(self._table)
        self._splitter.addWidget(self._area_chart)
        self._splitter.setSizes([1, 0])
        layout.addWidget(self._splitter, 1)

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

    def _apply_splitter_theme(self) -> None:
        theme = get_active_theme()
        handle_w = theme.view_border_width_px
        self._splitter.setHandleWidth(handle_w)
        self._splitter.setStyleSheet(
            f"""
            QSplitter::handle {{
                background-color: {theme.splitter_handle_hex};
                border: none;
            }}
            QSplitter::handle:vertical {{
                height: {handle_w}px;
            }}
            """
        )

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
            model_item = self._table.item(row_index, 0)
            if model_item is not None:
                model_item.setData(Qt.ItemDataRole.UserRole, row)
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

    def _visible_row_indices(self) -> list[int]:
        return [
            row_index
            for row_index in range(self._table.rowCount())
            if not self._table.isRowHidden(row_index)
        ]

    def _hide_area_chart(self) -> None:
        self._area_chart.set_series([])
        self._area_chart.hide()
        self._splitter.setSizes([1, 0])

    def _update_area_time_chart(self) -> None:
        visible = self._visible_row_indices()
        if not visible:
            self._hide_area_chart()
            return

        model_names: set[str] = set()
        groups: dict[tuple[int, str, tuple[str, ...]], list[tuple[float, float]]] = (
            defaultdict(list)
        )
        for row_index in visible:
            item = self._table.item(row_index, 0)
            row = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if not isinstance(row, GenerationTimingRow):
                continue
            model_names.add(row.model_name)
            key = (row.steps, row.quant, row.lora_stack)
            area = float(row.width * row.height)
            groups[key].append((area, row.avg_seconds))

        if not model_names:
            self._hide_area_chart()
            return

        if len(model_names) != 1:
            self._hide_area_chart()
            return

        series_list: list[_ChartSeries] = []
        for series_index, (key, points) in enumerate(sorted(groups.items())):
            steps, quant, lora_stack = key
            label = _combo_label(steps, quant, lora_stack)
            color = _SERIES_COLORS[series_index % len(_SERIES_COLORS)]
            sorted_points = sorted(points, key=lambda point: point[0])
            series_list.append(_ChartSeries(label, color, sorted_points))

        self._area_chart.set_series(series_list)
        self._area_chart.show()
        self._area_chart.setMinimumHeight(_CHART_MIN_HEIGHT)
        total = self._splitter.height()
        if total <= 0:
            total = max(self.height() - 80, 320)
        self._splitter.setSizes([int(total * 0.65), int(total * 0.35)])

    def _filter_to_model_row(self, row: int, _column: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        model_name = item.text().strip()
        if not model_name:
            return
        self.filter_edit.setText(model_name)

    def _apply_model_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        for row in range(self._table.rowCount()):
            if not needle:
                self._table.setRowHidden(row, False)
                continue
            item = self._table.item(row, 0)
            model_name = (item.text() if item else "").lower()
            self._table.setRowHidden(row, needle not in model_name)
        self._update_area_time_chart()


def show_generation_timing_dialog(parent=None) -> GenerationTimingDialog:
    dialog = GenerationTimingDialog(parent)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
