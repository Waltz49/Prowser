#!/usr/bin/env python3
"""
Modal dialog: image preview with face boxes; user clicks one face to select its encoding.
Used by Quick Person Search when an image contains multiple faces.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
import thumbnail_constants as tc

# (top, right, bottom, left), encoding
FaceDetection = Tuple[Tuple[int, int, int, int], List[float]]


class _FacePickCanvas(QWidget):
    """Draws scaled image and face boxes; emits index when a box is clicked."""

    face_selected = Signal(int)

    def __init__(self, parent: Optional[QWidget], preview_pixmap: QPixmap, detections: List[FaceDetection]):
        super().__init__(parent)
        self.setMinimumSize(520, 420)
        self._detections = detections
        self._pixmap: Optional[QPixmap] = preview_pixmap if not preview_pixmap.isNull() else None

        self._scale: float = 1.0
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._draw_w: int = 0
        self._draw_h: int = 0
        self._layout_boxes: List[QRect] = []
        self._hit_geom_ready: bool = False
        self._hit_cx: float = 0.0
        self._hit_cy: float = 0.0
        self._hit_sx: float = 1.0
        self._hit_sy: float = 1.0

    def sizeHint(self):
        return self.minimumSize()

    def mousePressEvent(self, event):
        pf = event.position()
        pos = pf.toPoint()
        chosen: Optional[int] = None

        if (
            self._hit_geom_ready
            and self._hit_sx > 0
            and self._hit_sy > 0
            and self._layout_boxes
        ):
            ix = (pf.x() - self._hit_cx) / self._hit_sx
            iy = (pf.y() - self._hit_cy) / self._hit_sy
            for i in range(len(self._detections) - 1, -1, -1):
                top, right, bottom, left = self._detections[i][0]
                if left <= ix <= right and top <= iy <= bottom:
                    chosen = i
                    break

        if chosen is None:
            for i in range(len(self._layout_boxes) - 1, -1, -1):
                if self._layout_boxes[i].contains(pos):
                    chosen = i
                    break

        if chosen is not None:
            self.face_selected.emit(chosen)
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), tc.DEFAULT_BACKGROUND_COLOR)

        self._layout_boxes = []
        self._hit_geom_ready = False

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(tc.TEXT_COLOR)
            painter.drawText(self.rect(), Qt.AlignCenter, "Image unavailable")
            return

        target = self.rect().adjusted(10, 10, -10, -10)
        pm_size = self._pixmap.size()
        if pm_size.width() <= 0 or pm_size.height() <= 0:
            return

        pm_w = float(pm_size.width())
        pm_h = float(pm_size.height())
        scale_fit = min(target.width() / pm_w, target.height() / pm_h)
        self._scale = scale_fit
        draw_w = int(pm_w * scale_fit)
        draw_h = int(pm_h * scale_fit)
        self._draw_w = draw_w
        self._draw_h = draw_h
        self._offset_x = target.x() + (target.width() - draw_w) // 2
        self._offset_y = target.y() + (target.height() - draw_h) // 2

        scaled = self._pixmap.scaled(draw_w, draw_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        sw = scaled.width()
        sh = scaled.height()
        cx = self._offset_x + (draw_w - sw) // 2
        cy = self._offset_y + (draw_h - sh) // 2
        painter.drawPixmap(cx, cy, scaled)

        sx = sw / pm_w
        sy = sh / pm_h
        self._hit_cx = float(cx)
        self._hit_cy = float(cy)
        self._hit_sx = sx
        self._hit_sy = sy
        self._hit_geom_ready = True

        painter.setPen(QPen(tc.CURRENT_IMAGE_BORDER_COLOR, 2))
        painter.setBrush(Qt.NoBrush)
        for loc, _enc in self._detections:
            top, right, bottom, left = loc
            x1 = cx + int(round(left * sx))
            y1 = cy + int(round(top * sy))
            x2 = cx + int(round(right * sx))
            y2 = cy + int(round(bottom * sy))
            rect = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
            self._layout_boxes.append(rect)
            painter.drawRect(rect)


class QuickPersonFacePickDialog(QDialog):
    """User picks one face; result via get_result() after exec() returns Accepted."""

    def __init__(
        self,
        parent: QWidget,
        detections: List[FaceDetection],
        preview_pixmap: QPixmap,
    ):
        super().__init__(parent)
        self.setWindowTitle("Choose face — Quick Person Search")
        self._detections = detections
        self._selected_index: Optional[int] = None

        layout = QVBoxLayout(self)
        hint = QLabel("Click the face to use for this image in Quick Person Search.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._canvas = _FacePickCanvas(self, preview_pixmap, detections)
        self._canvas.face_selected.connect(self._on_face_selected)
        layout.addWidget(self._canvas, 1)

        row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        row.addWidget(btn_cancel)
        row.addStretch()
        layout.addLayout(row)
        btn_cancel.clicked.connect(self.reject)

    def _on_face_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._detections):
            return
        self._selected_index = index
        self.accept()

    def get_result(self) -> Optional[Tuple[int, List[float]]]:
        """After Accepted: (face_index, encoding). After reject: None."""
        if self._selected_index is None:
            return None
        i = self._selected_index
        return (i, list(self._detections[i][1]))
