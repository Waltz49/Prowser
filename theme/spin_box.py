#!/usr/bin/env python3
"""Custom integer step spin control — avoids macOS QSpinBox subcontrol bugs."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

_STEP_SPIN_OBJECT_NAME = "StepSpinBox"
_BTN_UP_OBJECT_NAME = "StepSpinUpButton"
_BTN_DOWN_OBJECT_NAME = "StepSpinDownButton"
_BTN_COL_OBJECT_NAME = "StepSpinButtons"
_EDIT_OBJECT_NAME = "StepSpinEdit"

# Each step button gets a dedicated, non-overlapping vertical hit area.
_BTN_HEIGHT = 15
_CONTROL_HEIGHT = _BTN_HEIGHT * 2
_BTN_STRIP_WIDTH = 12
_DEFAULT_CHAR_COUNT = 6


class StepSpinBox(QWidget):
    """QSpinBox-compatible integer control with explicit step buttons."""

    valueChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(_STEP_SPIN_OBJECT_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._minimum = 0
        self._maximum = 99
        self._single_step = 1
        self._value = self._minimum
        self._suffix = ""

        self._edit = QLineEdit(self)
        self._edit.setObjectName(_EDIT_OBJECT_NAME)
        self._edit.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._edit.editingFinished.connect(self._commit_edit_text)
        self._edit.installEventFilter(self)

        self._up_btn = QToolButton(self)
        self._up_btn.setObjectName(_BTN_UP_OBJECT_NAME)
        self._up_btn.setFixedHeight(_BTN_HEIGHT)
        self._up_btn.setAutoRepeat(True)
        self._up_btn.setAutoRepeatDelay(400)
        self._up_btn.setAutoRepeatInterval(60)
        self._up_btn.clicked.connect(self._step_up)

        self._down_btn = QToolButton(self)
        self._down_btn.setObjectName(_BTN_DOWN_OBJECT_NAME)
        self._down_btn.setFixedHeight(_BTN_HEIGHT)
        self._down_btn.setAutoRepeat(True)
        self._down_btn.setAutoRepeatDelay(400)
        self._down_btn.setAutoRepeatInterval(60)
        self._down_btn.clicked.connect(self._step_down)

        btn_col = QWidget(self)
        btn_col.setObjectName(_BTN_COL_OBJECT_NAME)
        btn_col.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        btn_layout = QVBoxLayout(btn_col)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(0)
        btn_layout.addWidget(self._up_btn, 0)
        btn_layout.addWidget(self._down_btn, 0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._edit, 1)
        layout.addWidget(btn_col, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setMinimumHeight(_CONTROL_HEIGHT)
        self.setMinimumWidth(self.char_width())

        self._apply_button_icons()
        self._sync_edit_from_value()
        self._update_button_states()

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def singleStep(self) -> int:
        return self._single_step

    def value(self) -> int:
        return self._value

    def setMinimum(self, n: int) -> None:
        self._minimum = int(n)
        if self._value < self._minimum:
            self.setValue(self._minimum)
        else:
            self._update_button_states()

    def setMaximum(self, n: int) -> None:
        self._maximum = int(n)
        if self._value > self._maximum:
            self.setValue(self._maximum)
        else:
            self._update_button_states()

    def setRange(self, lo: int, hi: int) -> None:
        self._minimum = int(lo)
        self._maximum = int(hi)
        self.setValue(self._value)

    def setSingleStep(self, step: int) -> None:
        self._single_step = max(1, int(step))

    def suffix(self) -> str:
        return self._suffix

    def setSuffix(self, suffix: str) -> None:
        self._suffix = suffix or ""
        self._sync_edit_from_value()

    def char_width_for_text(self, sample_text: str, *, extra_chars: int = 1) -> int:
        """Widget width that fits ``sample_text`` plus step buttons and padding."""
        fm = self._edit.fontMetrics()
        text_w = fm.horizontalAdvance(sample_text)
        if extra_chars > 0:
            text_w += fm.horizontalAdvance("0" * extra_chars)
        return text_w + _BTN_STRIP_WIDTH + 16

    def setValue(self, value: int) -> None:
        clamped = max(self._minimum, min(self._maximum, int(value)))
        if clamped == self._value:
            self._sync_edit_from_value()
            self._update_button_states()
            return
        self._value = clamped
        self._sync_edit_from_value()
        self._update_button_states()
        if not self.signalsBlocked():
            self.valueChanged.emit(self._value)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._edit.setEnabled(enabled)
        self._up_btn.setEnabled(enabled)
        self._down_btn.setEnabled(enabled)
        self._update_button_states()

    def char_width(self, chars: int = _DEFAULT_CHAR_COUNT) -> int:
        """Widget width that fits ``chars`` digits plus suffix, step buttons, and padding."""
        count = max(1, int(chars))
        fm = self._edit.fontMetrics()
        text_w = fm.horizontalAdvance("8" * count + self._suffix)
        # Edit padding + outer border slack so five-digit values do not clip.
        chrome_w = _BTN_STRIP_WIDTH + 16
        return text_w + chrome_w

    def sizeHint(self) -> QSize:
        width = self.char_width()
        height = max(self._edit.sizeHint().height(), _CONTROL_HEIGHT)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Up:
                    self._step_up()
                    return True
                if key == Qt.Key.Key_Down:
                    self._step_down()
                    return True
            if event.type() in (
                QEvent.Type.FocusIn,
                QEvent.Type.FocusOut,
            ):
                focused = event.type() == QEvent.Type.FocusIn
                self.setProperty("hasFocus", focused)
                self.style().unpolish(self)
                self.style().polish(self)
                self.update()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._step_up()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._step_down()
            event.accept()
            return
        super().keyPressEvent(event)

    def _step_up(self) -> None:
        self.setValue(self._value + self._single_step)

    def _step_down(self) -> None:
        self.setValue(self._value - self._single_step)

    def _commit_edit_text(self) -> None:
        text = self._edit.text().strip()
        if self._suffix and text.endswith(self._suffix):
            text = text[: -len(self._suffix)].strip()
        try:
            self.setValue(int(text))
        except ValueError:
            self._sync_edit_from_value()

    def _sync_edit_from_value(self) -> None:
        blocked = self._edit.blockSignals(True)
        self._edit.setText(f"{self._value}{self._suffix}")
        self._edit.blockSignals(blocked)

    def _update_button_states(self) -> None:
        enabled = self.isEnabled()
        self._up_btn.setEnabled(enabled and self._value < self._maximum)
        self._down_btn.setEnabled(enabled and self._value > self._minimum)

    def _apply_button_icons(self) -> None:
        t = get_active_theme()
        if t.theme_id == "light":
            up_path = asset_path("spinbox_down_light.svg")
            down_path = asset_path("spinbox_up_light.svg")
        else:
            up_path = asset_path("spinbox_down_dark.svg")
            down_path = asset_path("spinbox_up_dark.svg")
        icon_size = QSize(7, 4)
        self._up_btn.setIcon(QIcon(up_path))
        self._down_btn.setIcon(QIcon(down_path))
        self._up_btn.setIconSize(icon_size)
        self._down_btn.setIconSize(icon_size)
