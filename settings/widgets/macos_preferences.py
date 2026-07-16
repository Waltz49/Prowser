#!/usr/bin/env python3
"""macOS System Settings–style preference rows and toggle switches for PySide6."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from settings.widgets.settings_dialog_theme import (
    SettingsDialogChrome,
    SettingsGearButton,
    resolve_settings_chrome_from_widget,
)


class MacToggleSwitch(QCheckBox):
    """macOS-style on/off switch (no text; pair with a separate label)."""

    TRACK_WIDTH = 36
    TRACK_HEIGHT = 20
    THUMB_MARGIN = 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.StyleChange:
            self.update()
        super().changeEvent(event)

    def _chrome(self) -> SettingsDialogChrome:
        return resolve_settings_chrome_from_widget(self)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        chrome = self._chrome()
        is_dark = chrome.bg_hex.lower() in ("#000000", "#0d0d0d", "#1c1c1e")
        checked = self.isChecked()
        enabled = self.isEnabled()

        # Track color constants for macOS-style toggle
        TRACK_COLOR_ON = "#29b94d"     # Green: enabled/on state

        TRACK_COLOR_OFF_DARK = "#636366"  # Gray: off state in dark mode
        TRACK_COLOR_OFF_LIGHT = "#E9E9EA"  # Light gray: off state in light mode

        if checked:
            track = QColor(TRACK_COLOR_ON)
        elif is_dark:
            track = QColor(TRACK_COLOR_OFF_DARK)
        else:
            track = QColor(TRACK_COLOR_OFF_LIGHT)

        if not enabled:
 
            track.setAlpha(120)

        thumb = QColor("#FFFFFF")
        if not enabled:
            thumb.setAlpha(180)

        w = self.TRACK_WIDTH
        h = self.TRACK_HEIGHT
        radius = h / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        thumb_d = h - 2 * self.THUMB_MARGIN
        thumb_y = self.THUMB_MARGIN
        thumb_x_off = w - self.THUMB_MARGIN - thumb_d
        thumb_x = thumb_x_off if checked else self.THUMB_MARGIN

        painter.setPen(QPen(QColor(0, 0, 0, 25 if enabled else 10), 0.5))
        painter.setBrush(thumb)
        painter.drawEllipse(int(thumb_x), int(thumb_y), int(thumb_d), int(thumb_d))


class MacPreferenceToggleRow(QWidget):
    """Single preference row: title (+ optional subtitle) left, toggle right."""

    def __init__(
        self,
        title: str,
        *,
        tooltip: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.toggle = MacToggleSwitch(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("macPreferenceRowTitle")
        title_label.setWordWrap(True)
        if tooltip:
            title_label.setToolTip(tooltip)
            self.toggle.setToolTip(tooltip)
        text_col.addWidget(title_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("macPreferenceRowSubtitle")
            sub.setWordWrap(True)
            text_col.addWidget(sub)

        layout.addLayout(text_col, 1)
        layout.addWidget(self.toggle, 0, Qt.AlignRight | Qt.AlignVCenter)


class MacPreferenceGearToggleRow(QWidget):
    """Preference row: title + gear on the left, toggle on the right."""

    def __init__(
        self,
        title: str,
        *,
        on_gear_clicked: Callable[[], None],
        tooltip: str = "",
        subtitle: str = "",
        gear_tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.toggle = MacToggleSwitch(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("macPreferenceRowTitle")
        title_label.setWordWrap(True)
        title_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        if tooltip:
            title_label.setToolTip(tooltip)
            self.toggle.setToolTip(tooltip)
        title_row.addWidget(title_label, 0, Qt.AlignVCenter)

        gear_button = SettingsGearButton(self, tooltip=gear_tooltip or tooltip)
        gear_button.clicked.connect(on_gear_clicked)
        title_row.addWidget(gear_button, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("macPreferenceRowSubtitle")
            sub.setWordWrap(True)
            text_col.addWidget(sub)

        layout.addLayout(text_col, 1)
        layout.addWidget(self.toggle, 0, Qt.AlignRight | Qt.AlignVCenter)


class MacPreferenceSubordinateToggleRow(MacPreferenceToggleRow):
    """Indented preference row; grey out label and toggle when disabled."""

    def __init__(
        self,
        title: str,
        *,
        tooltip: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(title, tooltip=tooltip, subtitle=subtitle, parent=parent)
        self.layout().setContentsMargins(36, 8, 20, 8)


class MacPreferenceCompactToggleRow(QWidget):
    """Compact label + toggle for multi-column preference grids."""

    def __init__(
        self,
        title: str,
        *,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.toggle = MacToggleSwitch(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("macPreferenceRowTitle")
        if tooltip:
            title_label.setToolTip(tooltip)
            self.toggle.setToolTip(tooltip)
        layout.addWidget(title_label, 1, Qt.AlignVCenter)
        layout.addWidget(self.toggle, 0, Qt.AlignRight | Qt.AlignVCenter)


def build_column_major_toggle_grid(
    items: list[tuple[str, str, str]],
    *,
    num_cols: int = 3,
    parent: Optional[QWidget] = None,
) -> tuple[QWidget, dict[str, MacToggleSwitch]]:
    """Lay out (key, title, tooltip) items in column-major order across columns.

    Returns the grid container and a mapping of key -> toggle switch.
    """
    num_items = len(items)
    num_rows = (num_items + num_cols - 1) // num_cols if num_items else 0

    grid_widget = QWidget(parent)
    grid_layout = QHBoxLayout(grid_widget)
    grid_layout.setContentsMargins(8, 6, 8, 6)
    grid_layout.setSpacing(12)

    toggles: dict[str, MacToggleSwitch] = {}
    for col in range(num_cols):
        col_widget = QWidget(grid_widget)
        col_layout = QVBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)

        for row in range(num_rows):
            idx = col * num_rows + row
            if idx >= num_items:
                spacer = QWidget()
                spacer.setFixedHeight(30)
                col_layout.addWidget(spacer)
                continue
            key, title, tooltip = items[idx]
            row_widget = MacPreferenceCompactToggleRow(title, tooltip=tooltip, parent=col_widget)
            toggles[key] = row_widget.toggle
            col_layout.addWidget(row_widget)

        col_layout.addStretch()
        grid_layout.addWidget(col_widget, 1)

    return grid_widget, toggles


class MacPreferenceFormRow(QWidget):
    """Label (+ optional subtitle) on the left, arbitrary control on the right."""

    def __init__(
        self,
        label_text: str,
        control: QWidget,
        *,
        tooltip: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        label = QLabel(label_text)
        label.setObjectName("macPreferenceRowTitle")
        label.setWordWrap(True)
        if tooltip:
            label.setToolTip(tooltip)
            control.setToolTip(tooltip)
        text_col.addWidget(label, 0, Qt.AlignVCenter)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("macPreferenceRowSubtitle")
            sub.setWordWrap(True)
            text_col.addWidget(sub)

        layout.addLayout(text_col, 1)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)


class MacPreferencePanel(QFrame):
    """Rounded inset panel grouping multiple preference rows."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("macPreferencePanel")
        self._rows_layout = QVBoxLayout(self)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.setSpacing(0)
        self._row_count = 0

    def _add_divider(self) -> None:
        div = QFrame(self)
        div.setObjectName("macPreferenceDivider")
        div.setFixedHeight(1)
        div.setFrameShape(QFrame.NoFrame)
        self._rows_layout.addWidget(div)

    def add_toggle(
        self,
        title: str,
        *,
        tooltip: str = "",
        subtitle: str = "",
    ) -> MacToggleSwitch:
        if self._row_count:
            self._add_divider()
        row = MacPreferenceToggleRow(title, tooltip=tooltip, subtitle=subtitle, parent=self)
        self._rows_layout.addWidget(row)
        self._row_count += 1
        return row.toggle

    def add_gear_toggle(
        self,
        title: str,
        *,
        on_gear_clicked: Callable[[], None],
        tooltip: str = "",
        subtitle: str = "",
        gear_tooltip: str = "",
    ) -> MacToggleSwitch:
        if self._row_count:
            self._add_divider()
        row = MacPreferenceGearToggleRow(
            title,
            on_gear_clicked=on_gear_clicked,
            tooltip=tooltip,
            subtitle=subtitle,
            gear_tooltip=gear_tooltip,
            parent=self,
        )
        self._rows_layout.addWidget(row)
        self._row_count += 1
        return row.toggle

    def add_subordinate_toggle(
        self,
        title: str,
        *,
        tooltip: str = "",
        subtitle: str = "",
    ) -> MacPreferenceSubordinateToggleRow:
        if self._row_count:
            self._add_divider()
        row = MacPreferenceSubordinateToggleRow(
            title,
            tooltip=tooltip,
            subtitle=subtitle,
            parent=self,
        )
        self._rows_layout.addWidget(row)
        self._row_count += 1
        return row

    def add_form_row(
        self,
        label_text: str,
        control: QWidget,
        *,
        tooltip: str = "",
        subtitle: str = "",
    ) -> None:
        if self._row_count:
            self._add_divider()
        row = MacPreferenceFormRow(
            label_text,
            control,
            tooltip=tooltip,
            subtitle=subtitle,
            parent=self,
        )
        self._rows_layout.addWidget(row)
        self._row_count += 1

    def add_custom_row(self, widget: QWidget) -> None:
        if self._row_count:
            self._add_divider()
        self._rows_layout.addWidget(widget)
        self._row_count += 1


def mac_preference_section_title(text: str, parent: Optional[QWidget] = None) -> QLabel:
    """Small caps-style section header above a preference panel."""
    label = QLabel(text.upper(), parent)
    label.setObjectName("macPreferenceSectionTitle")
    return label


def mac_preference_section(
    title: str,
    parent: Optional[QWidget] = None,
) -> tuple[QLabel, MacPreferencePanel]:
    """Return (section header label, panel) for a preference group."""
    return mac_preference_section_title(title, parent), MacPreferencePanel(parent)
