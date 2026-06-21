#!/usr/bin/env python3
"""Floating label above the generate button after a job is submitted."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
    QWidget,
)

_VISIBLE_MS = 5000
_FADE_MS = 1000
_GAP_MM = 2.0

_SUBMIT_NOTICE_BY_FUNCTION = {
    "create": "Create job submitted",
    "edit": "Edit job submitted",
    "expand": "Expand job submitted",
    "infill": "Infill job submitted",
    "infill_paint": "Infill job submitted",
}


def submit_notice_text(function: str) -> str:
    return _SUBMIT_NOTICE_BY_FUNCTION.get(function, "Job submitted")


class ImageGenSubmitNotice:
    """Themed overlay label right-aligned above the generate button."""

    def __init__(self, host: QWidget, generate_btn: QPushButton) -> None:
        self._host = host
        self._generate_btn = generate_btn
        self._label = QLabel(host)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._opacity = QGraphicsOpacityEffect(self._label)
        self._label.setGraphicsEffect(self._opacity)
        self._timer: Optional[QTimer] = None
        self._fade: Optional[QPropertyAnimation] = None
        self._style_label()
        self._label.hide()

    def _style_label(self) -> None:
        # Match NotificationBubble in status_notification.py
        self._label.setStyleSheet(
            """
            QLabel {
                font-size: 12pt;
                background-color: #cacaca;
                border: 1px solid #4a4a4a;
                color: #2a2a2a;
                padding: 7px 10px;
                border-radius: 5px;
            }
            """
        )

    def _gap_px(self) -> int:
        return max(4, int(round(_GAP_MM / 25.4 * self._host.logicalDpiY())))

    def reposition(self) -> None:
        if not self._label.isVisible():
            return
        self._position()

    def _position(self) -> None:
        self._label.adjustSize()
        notice_w = self._label.sizeHint().width()
        notice_h = self._label.sizeHint().height()
        btn_origin = self._generate_btn.mapTo(self._host, QPoint(0, 0))
        x = btn_origin.x() + self._generate_btn.width() - notice_w
        y = btn_origin.y() - self._gap_px() - notice_h
        self._label.setGeometry(x, y, notice_w, notice_h)
        self._label.raise_()

    def show(self, text: str) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade.deleteLater()
            self._fade = None
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._label.setText(text)
        self._opacity.setOpacity(1.0)
        self._position()
        self._label.show()
        self._label.raise_()
        self._timer = QTimer(self._host)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(_VISIBLE_MS)

    def _fade_out(self) -> None:
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self._host)
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.finished.connect(self._hide)
        self._fade.start()

    def _hide(self) -> None:
        self._label.hide()
        self._opacity.setOpacity(1.0)
        if self._fade is not None:
            self._fade.deleteLater()
            self._fade = None
