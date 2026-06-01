#!/usr/bin/env python3
"""Interactive paint canvas for infill mask creation."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from exif_image_loader import load_image_with_exif_correction

WORKAREA_FILL = QColor(0, 0, 0)
MASK_OVERLAY = QColor(255, 60, 60, 120)
BRUSH_MIN = 4
BRUSH_MAX = 256
BRUSH_DEFAULT = 32
BRUSH_STEP = 4
UNDO_LIMIT = 50


class InfillPaintCanvas(QWidget):
    """Letterboxed source image with a transparent mask layer the user paints on."""

    def __init__(self, source_path: str, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._source_path = source_path
        self._source_pixmap: Optional[QPixmap] = None
        self._image_w = 1
        self._image_h = 1
        self._mask = QImage(1, 1, QImage.Format.Format_ARGB32)
        self._mask.fill(Qt.GlobalColor.transparent)

        self._image_rect = QRect()
        self._scale = 1.0
        self._brush_radius = BRUSH_DEFAULT
        self._painting = False
        self._has_paint = False
        self._overlay_cache: Optional[QImage] = None
        self._undo_stack: List[QImage] = []
        self._redo_stack: List[QImage] = []
        self._cursor_pos = QPoint()
        self._cursor_visible = False

        self._load_source(source_path)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            pt = event.position()
            return pt.toPoint() if hasattr(pt, "toPoint") else QPoint(int(pt.x()), int(pt.y()))
        return event.pos()

    def _load_source(self, source_path: str) -> None:
        self._source_path = source_path
        self._source_pixmap = None
        self._image_w = 1
        self._image_h = 1
        if source_path:
            pixmap = load_image_with_exif_correction(source_path, ignore_exif=False)
            if pixmap is not None and not pixmap.isNull():
                self._source_pixmap = pixmap
                self._image_w = max(1, pixmap.width())
                self._image_h = max(1, pixmap.height())
        self._mask = QImage(self._image_w, self._image_h, QImage.Format.Format_ARGB32)
        self._mask.fill(Qt.GlobalColor.transparent)
        self._has_paint = False
        self._overlay_cache = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.update()

    def set_source_path(self, source_path: str) -> None:
        if source_path == self._source_path:
            return
        self._load_source(source_path)

    def source_size(self) -> Tuple[int, int]:
        return self._image_w, self._image_h

    def brush_radius(self) -> int:
        return self._brush_radius

    def set_brush_radius(self, radius: int) -> None:
        self._brush_radius = max(BRUSH_MIN, min(BRUSH_MAX, int(radius)))
        self.update()

    def adjust_brush_radius(self, delta: int) -> None:
        self.set_brush_radius(self._brush_radius + delta)

    def clear_mask(self) -> None:
        self._push_undo()
        self._mask.fill(Qt.GlobalColor.transparent)
        self._has_paint = False
        self._overlay_cache = None
        self._redo_stack.clear()
        self.update()

    def load_mask_from_path(self, mask_path: str) -> bool:
        """Load a saved mask PNG (same dimensions as source, or scaled to fit)."""
        mask_path = (mask_path or "").strip()
        if not mask_path or not os.path.isfile(mask_path):
            return False
        loaded = QImage(mask_path)
        if loaded.isNull():
            return False
        if loaded.size() != self._mask.size():
            loaded = loaded.scaled(
                self._mask.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._mask = loaded.convertToFormat(QImage.Format.Format_ARGB32)
        self._sync_has_paint_from_mask()
        self._overlay_cache = None
        self.update()
        return self._has_paint

    def has_paint(self) -> bool:
        return self._has_paint

    def mask_image(self) -> QImage:
        return self._mask.copy()

    def _rebuild_overlay(self) -> None:
        overlay = QImage(self._mask.size(), QImage.Format.Format_ARGB32)
        overlay.fill(MASK_OVERLAY)
        painter = QPainter(overlay)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        painter.drawImage(0, 0, self._mask)
        painter.end()
        self._overlay_cache = overlay

    def _push_undo(self) -> None:
        self._undo_stack.append(self._mask.copy())
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._mask.copy())
        self._mask = self._undo_stack.pop()
        self._sync_has_paint_from_mask()
        self._overlay_cache = None
        self.update()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._mask.copy())
        self._mask = self._redo_stack.pop()
        self._sync_has_paint_from_mask()
        self._overlay_cache = None
        self.update()
        return True

    def _sync_has_paint_from_mask(self) -> None:
        self._has_paint = False
        for y in range(self._mask.height()):
            for x in range(self._mask.width()):
                if self._mask.pixelColor(x, y).alpha() > 0:
                    self._has_paint = True
                    return

    def _update_image_geometry(self) -> None:
        margin = 12
        avail_w = max(1, self.width() - 2 * margin)
        avail_h = max(1, self.height() - 2 * margin)
        scale = min(avail_w / self._image_w, avail_h / self._image_h)
        draw_w = max(1, int(round(self._image_w * scale)))
        draw_h = max(1, int(round(self._image_h * scale)))
        off_x = (self.width() - draw_w) // 2
        off_y = (self.height() - draw_h) // 2
        self._image_rect = QRect(off_x, off_y, draw_w, draw_h)
        self._scale = draw_w / self._image_w if self._image_w > 0 else 1.0

    def _display_to_image(self, pos: QPoint) -> Optional[Tuple[float, float]]:
        if not self._image_rect.contains(pos):
            return None
        rel_x = pos.x() - self._image_rect.x()
        rel_y = pos.y() - self._image_rect.y()
        ix = rel_x / self._scale
        iy = rel_y / self._scale
        if ix < 0 or iy < 0 or ix >= self._image_w or iy >= self._image_h:
            return None
        return ix, iy

    def _option_erase_active(self, event=None) -> bool:
        """Option (macOS) / Alt — erase mask instead of painting."""
        if event is not None:
            mods = event.modifiers()
        else:
            mods = QApplication.keyboardModifiers()
        return bool(mods & Qt.KeyboardModifier.AltModifier)

    def _stamp_brush(self, ix: float, iy: float, *, erase: bool = False) -> None:
        painter = QPainter(self._mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self._brush_radius
        if erase:
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            painter.setBrush(Qt.GlobalColor.transparent)
        else:
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.drawEllipse(
            QPointF(ix, iy),
            float(radius),
            float(radius),
        )
        painter.end()
        if erase:
            self._sync_has_paint_from_mask()
        else:
            self._has_paint = True
        self._overlay_cache = None

    def _paint_brush_cursor(self, painter: QPainter) -> None:
        if not self._cursor_visible:
            return
        img_pt = self._display_to_image(self._cursor_pos)
        if img_pt is None:
            return
        display_r = max(2.0, float(self._brush_radius) * self._scale)
        cx = float(self._cursor_pos.x())
        cy = float(self._cursor_pos.y())
        erase = self._option_erase_active()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if erase:
            painter.setPen(QPen(QColor(255, 140, 40), 2))
            painter.drawEllipse(QPointF(cx, cy), display_r, display_r)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawEllipse(
                QPointF(cx, cy), max(0.0, display_r - 1.0), max(0.0, display_r - 1.0)
            )
        else:
            painter.setPen(QPen(QColor(0, 0, 0), 2))
            painter.drawEllipse(QPointF(cx, cy), display_r, display_r)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawEllipse(
                QPointF(cx, cy), max(0.0, display_r - 1.0), max(0.0, display_r - 1.0)
            )

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
            self.update()
        if key == Qt.Key.Key_BracketLeft:
            self.adjust_brush_radius(-BRUSH_STEP)
            event.accept()
            return
        if key == Qt.Key.Key_BracketRight:
            self.adjust_brush_radius(BRUSH_STEP)
            event.accept()
            return
        if (
            key == Qt.Key.Key_Z
            and mods & Qt.KeyboardModifier.ControlModifier
            and mods & Qt.KeyboardModifier.ShiftModifier
        ):
            if self.redo():
                event.accept()
                return
        elif key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            if self.undo():
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
            self.update()
        super().keyReleaseEvent(event)

    def enterEvent(self, event):
        self._cursor_visible = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._cursor_visible = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._update_image_geometry()
        pos = self._event_pos(event)
        img_pt = self._display_to_image(pos)
        if img_pt is None:
            super().mousePressEvent(event)
            return
        self._push_undo()
        self._painting = True
        self._stamp_brush(
            img_pt[0], img_pt[1], erase=self._option_erase_active(event)
        )
        self.grabMouse()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        pos = self._event_pos(event)
        moved = pos != self._cursor_pos
        self._cursor_pos = pos
        self._update_image_geometry()
        if not self._painting:
            if moved:
                self.update()
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._end_paint()
            event.accept()
            return
        img_pt = self._display_to_image(pos)
        if img_pt is not None:
            self._stamp_brush(
                img_pt[0], img_pt[1], erase=self._option_erase_active(event)
            )
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._painting:
            self._end_paint()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _end_paint(self) -> None:
        if self._painting:
            self.releaseMouse()
        self._painting = False

    def showEvent(self, event):
        super().showEvent(event)
        self._update_image_geometry()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_image_geometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 480)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), WORKAREA_FILL)
        self._update_image_geometry()
        r = self._image_rect

        if self._source_pixmap is None or self._source_pixmap.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "Image unavailable")
            return

        scaled = self._source_pixmap.scaled(
            r.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(r.topLeft(), scaled)

        if self._has_paint:
            if self._overlay_cache is None:
                self._rebuild_overlay()
            if self._overlay_cache is not None:
                overlay_scaled = self._overlay_cache.scaled(
                    r.size(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawImage(r.topLeft(), overlay_scaled)

        self._paint_brush_cursor(painter)
