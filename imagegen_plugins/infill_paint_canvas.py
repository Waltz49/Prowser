#!/usr/bin/env python3
"""Interactive paint canvas for infill mask creation."""

from __future__ import annotations

import os
from typing import List, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QGestureEvent, QSizePolicy, QWidget

from exif.exif_image_loader import load_image_with_exif_correction, pil_to_qpixmap
from imagegen_plugins.image_gen_dim_limits import (
    APP_MAX_GENERATION_DIMENSION_DEFAULT,
    align_generation_dimension,
)
from imagegen_plugins.image_gen_dialog import image_gen_preview_workarea_fill
from imagegen_plugins.image_gen_form_layout import create_image_gen_dim_helper_icon_button
from imagegen_plugins.outpaint_mask import fit_infill_paint_dims

MASK_OVERLAY = QColor(255, 60, 60, 120)
BRUSH_MIN = 4
BRUSH_MAX = 256
BRUSH_DEFAULT = 32
BRUSH_STEP = 4
UNDO_LIMIT = 50
VIEW_MARGIN = 12
VIEW_SCALE_MAX = 8.0
ZOOM_WHEEL_FACTOR = 1.15
TRACK_EDGE_CM = 1.0


def _qobject_alive(obj) -> bool:
    if obj is None:
        return False
    try:
        from shiboken6 import isValid

        return isValid(obj)
    except ImportError:
        return True


class InfillPaintCanvas(QWidget):
    """Letterboxed source image with a transparent mask layer the user paints on."""

    maskChanged = Signal()

    def __init__(self, source_path: str, parent=None, *, max_side: int = APP_MAX_GENERATION_DIMENSION_DEFAULT):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.grabGesture(Qt.GestureType.PinchGesture)

        self._max_generation_dimension = align_generation_dimension(max_side)

        self._source_path = source_path
        self._source_pixmap: Optional[QPixmap] = None
        self._image_w = 1
        self._image_h = 1
        self._mask = QImage(1, 1, QImage.Format.Format_ARGB32)
        self._mask.fill(Qt.GlobalColor.transparent)

        self._image_rect = QRect()
        self._fit_scale = 1.0
        self._view_scale = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._scale = 1.0
        self._zoom_center_point = QPointF()
        self._brush_radius = BRUSH_DEFAULT
        self._painting = False
        self._has_paint = False
        self._overlay_cache: Optional[QImage] = None
        self._undo_stack: List[QImage] = []
        self._redo_stack: List[QImage] = []
        self._cursor_pos = QPoint()
        self._cursor_visible = False

        self._clear_btn = create_image_gen_dim_helper_icon_button(
            "dim_reverse_icon.png",
            hover_icon_name="dim_reverse_icon_hover.png",
            tooltip="Clear painted mask",
            parent=self,
        )
        self._clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self.clear_mask)
        self._clear_btn.hide()

        self._load_source(source_path)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def set_max_generation_dimension(self, max_side: int) -> None:
        self._max_generation_dimension = align_generation_dimension(max_side)
        if self._source_path:
            self._load_source(self._source_path)

    def _event_pos(self, event) -> QPoint:
        if hasattr(event, "position"):
            pt = event.position()
            return pt.toPoint() if hasattr(pt, "toPoint") else QPoint(int(pt.x()), int(pt.y()))
        return event.pos()

    def _reset_view(self) -> None:
        self._fit_scale = 1.0
        self._view_scale = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0

    def _load_source(self, source_path: str) -> None:
        self._source_path = source_path
        self._source_pixmap = None
        self._image_w = 1
        self._image_h = 1
        self._reset_view()
        if source_path:
            pixmap = self._load_working_pixmap(source_path)
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
        self._sync_clear_button_state()
        self.update()

    def _load_working_pixmap(self, source_path: str) -> Optional[QPixmap]:
        """Load source with EXIF correction, scaled to infill working dimensions."""
        try:
            from PIL import Image
            from pil_image_io import open_pil_with_exif_correction

            pil_img = open_pil_with_exif_correction(
                source_path, ignore_exif=False, cr2_half_size=False
            )
            if pil_img is not None:
                work_w, work_h = fit_infill_paint_dims(
                    pil_img.width,
                    pil_img.height,
                    max_side=self._max_generation_dimension,
                )
                if (work_w, work_h) != (pil_img.width, pil_img.height):
                    pil_img = pil_img.resize((work_w, work_h), Image.Resampling.LANCZOS)
                pixmap = pil_to_qpixmap(pil_img, preserve_alpha=True)
                if pixmap is not None and not pixmap.isNull():
                    return pixmap
        except (ImportError, OSError, ValueError):
            pass
        pixmap = load_image_with_exif_correction(source_path, ignore_exif=False)
        if pixmap is None or pixmap.isNull():
            return None
        work_w, work_h = fit_infill_paint_dims(
            pixmap.width(),
            pixmap.height(),
            max_side=self._max_generation_dimension,
        )
        if (work_w, work_h) == (pixmap.width(), pixmap.height()):
            return pixmap
        scaled = pixmap.scaled(
            work_w,
            work_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return scaled if not scaled.isNull() else pixmap

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

    def _image_brush_radius(self) -> float:
        """Mask-space brush radius; shrinks when zoomed in so the on-screen ring stays fixed."""
        vs = max(1.0, self._view_scale)
        return max(1.0, float(self._brush_radius) / vs)

    def _display_brush_radius(self) -> float:
        """On-screen brush ring radius (constant across view zoom)."""
        return max(2.0, float(self._brush_radius) * self._fit_scale)

    def clear_mask(self) -> None:
        if not self._has_paint:
            return
        self._push_undo()
        self._mask.fill(Qt.GlobalColor.transparent)
        self._has_paint = False
        self._overlay_cache = None
        self._redo_stack.clear()
        self._sync_clear_button_state()
        self.update()
        self.maskChanged.emit()

    def load_mask_image(self, loaded: QImage) -> bool:
        """Load mask pixels (same dimensions as source, or scaled to fit)."""
        if loaded is None or loaded.isNull():
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
        self._sync_clear_button_state()
        self.update()
        self.maskChanged.emit()
        return self._has_paint

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
        self._sync_clear_button_state()
        self.update()
        self.maskChanged.emit()
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
        self._sync_clear_button_state()
        self.update()
        self.maskChanged.emit()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._mask.copy())
        self._mask = self._redo_stack.pop()
        self._sync_has_paint_from_mask()
        self._overlay_cache = None
        self._sync_clear_button_state()
        self.update()
        self.maskChanged.emit()
        return True

    def _sync_has_paint_from_mask(self) -> None:
        self._has_paint = False
        for y in range(self._mask.height()):
            for x in range(self._mask.width()):
                if self._mask.pixelColor(x, y).alpha() > 0:
                    self._has_paint = True
                    return

    def _sync_clear_button_state(self) -> None:
        if not _qobject_alive(self._clear_btn):
            return
        btn = self._clear_btn
        if self._has_paint:
            btn.show()
            btn.setEnabled(True)
            self._position_clear_button()
        else:
            btn.hide()

    def _clear_button_contains(self, pos: QPoint) -> bool:
        if not self._has_paint or not _qobject_alive(self._clear_btn):
            return False
        btn = self._clear_btn
        if not btn.isVisible():
            return False
        return btn.geometry().contains(pos)

    def _update_clear_button_cursor(self, pos: QPoint) -> None:
        if self._clear_button_contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)

    def _display_scale(self) -> float:
        return self._fit_scale * self._view_scale

    def _avail_viewport_size(self) -> Tuple[int, int]:
        avail_w = max(1, self.width() - 2 * VIEW_MARGIN)
        avail_h = max(1, self.height() - 2 * VIEW_MARGIN)
        return avail_w, avail_h

    def _clamp_pan(self, draw_w: int, draw_h: int, base_x: int, base_y: int) -> None:
        avail_w, avail_h = self._avail_viewport_size()
        if draw_w <= avail_w:
            self._pan_x = 0.0
        else:
            min_off_x = VIEW_MARGIN + avail_w - draw_w
            max_off_x = VIEW_MARGIN
            self._pan_x = max(
                float(min_off_x - base_x),
                min(float(max_off_x - base_x), self._pan_x),
            )
        if draw_h <= avail_h:
            self._pan_y = 0.0
        else:
            min_off_y = VIEW_MARGIN + avail_h - draw_h
            max_off_y = VIEW_MARGIN
            self._pan_y = max(
                float(min_off_y - base_y),
                min(float(max_off_y - base_y), self._pan_y),
            )

    def _update_image_geometry(self) -> None:
        avail_w, avail_h = self._avail_viewport_size()
        fit_scale = min(avail_w / self._image_w, avail_h / self._image_h)
        self._fit_scale = fit_scale

        self._view_scale = max(1.0, min(VIEW_SCALE_MAX, self._view_scale))
        display_scale = self._display_scale()

        draw_w = max(1, int(round(self._image_w * display_scale)))
        draw_h = max(1, int(round(self._image_h * display_scale)))
        base_x = (self.width() - draw_w) // 2
        base_y = (self.height() - draw_h) // 2

        self._clamp_pan(draw_w, draw_h, base_x, base_y)
        off_x = base_x + int(round(self._pan_x))
        off_y = base_y + int(round(self._pan_y))

        self._image_rect = QRect(off_x, off_y, draw_w, draw_h)
        self._scale = draw_w / self._image_w if self._image_w > 0 else 1.0
        self._position_clear_button()

    def _position_clear_button(self) -> None:
        if not _qobject_alive(self._clear_btn):
            return
        btn = self._clear_btn
        btn_sz = btn.size()
        if btn_sz.width() < 1:
            btn.adjustSize()
            btn_sz = btn.size()
        inset = 6
        r = self._image_rect
        if r.isEmpty():
            btn.hide()
            return
        x = r.left() + inset
        y = r.bottom() - btn_sz.height() - inset
        btn.move(x, y)
        if self._has_paint:
            btn.show()
            QTimer.singleShot(0, btn.raise_)
        else:
            btn.hide()

    def _can_pan_image(self) -> bool:
        avail_w, avail_h = self._avail_viewport_size()
        draw_w = max(1, int(round(self._image_w * self._display_scale())))
        draw_h = max(1, int(round(self._image_h * self._display_scale())))
        return draw_w > avail_w or draw_h > avail_h

    def _zoom_at_point(self, new_display_scale: float, zoom_point: QPointF) -> None:
        min_scale = self._fit_scale
        max_scale = self._fit_scale * VIEW_SCALE_MAX
        new_display_scale = max(min_scale, min(max_scale, new_display_scale))
        old_scale = self._display_scale()
        if abs(new_display_scale - old_scale) < 0.001:
            return

        img_pt = self._display_to_image(
            QPoint(int(zoom_point.x()), int(zoom_point.y()))
        )
        self._view_scale = max(1.0, min(VIEW_SCALE_MAX, new_display_scale / self._fit_scale))

        if img_pt is None:
            self._update_image_geometry()
            self.update()
            return

        ix, iy = img_pt
        draw_w = max(1, int(round(self._image_w * new_display_scale)))
        draw_h = max(1, int(round(self._image_h * new_display_scale)))
        base_x = (self.width() - draw_w) // 2
        base_y = (self.height() - draw_h) // 2

        self._pan_x = float(zoom_point.x()) - ix * new_display_scale - base_x
        self._pan_y = float(zoom_point.y()) - iy * new_display_scale - base_y
        self._update_image_geometry()
        self.update()

    def _track_margin_px(self) -> int:
        """~1 cm logical pixels for brush tracking outside the image edge."""
        screen = self.screen()
        dpi = float(screen.logicalDotsPerInchX()) if screen is not None else 96.0
        return max(8, int(round(dpi * TRACK_EDGE_CM / 2.54)))

    def _cursor_track_rect(self) -> QRect:
        """Image rect expanded so the brush ring stays visible near edges."""
        pad = self._track_margin_px()
        display_r = int(self._display_brush_radius() + 0.999) + 2
        pad = max(pad, display_r)
        return self._image_rect.adjusted(-pad, -pad, pad, pad)

    def _display_to_image_coords(self, pos: QPoint) -> Tuple[float, float]:
        rel_x = pos.x() - self._image_rect.x()
        rel_y = pos.y() - self._image_rect.y()
        scale = self._scale if self._scale > 0 else 1.0
        return rel_x / scale, rel_y / scale

    def _brush_overlaps_image(self, ix: float, iy: float) -> bool:
        radius = self._image_brush_radius()
        return not (
            ix + radius < 0.0
            or iy + radius < 0.0
            or ix - radius >= float(self._image_w)
            or iy - radius >= float(self._image_h)
        )

    def _display_to_image(self, pos: QPoint) -> Optional[Tuple[float, float]]:
        if not self._image_rect.contains(pos):
            return None
        ix, iy = self._display_to_image_coords(pos)
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
        if not self._brush_overlaps_image(ix, iy):
            return
        painter = QPainter(self._mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(QRect(0, 0, self._image_w, self._image_h))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self._image_brush_radius()
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
        self._sync_clear_button_state()

    def _paint_brush_cursor(self, painter: QPainter) -> None:
        if not self._cursor_visible:
            return
        if not self._cursor_track_rect().contains(self._cursor_pos):
            return
        display_r = self._display_brush_radius()
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

    def event(self, event):
        if event.type() == QEvent.Type.Gesture:
            return self.gestureEvent(event)
        return super().event(event)

    def gestureEvent(self, event: QGestureEvent) -> bool:
        if self._painting:
            return False
        pinch = event.gesture(Qt.GestureType.PinchGesture)
        if pinch is None:
            return False
        if pinch.state() == Qt.GestureState.GestureStarted:
            self._zoom_center_point = pinch.centerPoint()
        elif pinch.state() == Qt.GestureState.GestureUpdated:
            scale_change = pinch.scaleFactor()
            new_scale = self._display_scale() * scale_change
            if abs(new_scale - self._display_scale()) > 0.01:
                self._zoom_at_point(new_scale, self._zoom_center_point)
        event.accept()
        return True

    def wheelEvent(self, event):
        if self._painting:
            super().wheelEvent(event)
            return
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                zoom_factor = ZOOM_WHEEL_FACTOR if delta > 0 else (1.0 / ZOOM_WHEEL_FACTOR)
                new_scale = self._display_scale() * zoom_factor
                self._zoom_at_point(new_scale, event.position())
                event.accept()
                return
        elif self._can_pan_image():
            pixel_delta = event.pixelDelta()
            if not pixel_delta.isNull():
                delta_x = pixel_delta.x()
                delta_y = pixel_delta.y()
            else:
                delta_x = event.angleDelta().x()
                delta_y = event.angleDelta().y()
            if delta_x != 0 or delta_y != 0:
                self._pan_x -= float(delta_x)
                self._pan_y -= float(delta_y)
                self._update_image_geometry()
                self.update()
                event.accept()
                return
        super().wheelEvent(event)

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
        if _mask_redo_key_event(event):
            if self.redo():
                event.accept()
                return
        elif _mask_undo_key_event(event):
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
        self._update_clear_button_cursor(self._event_pos(event))
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
        if self._clear_button_contains(pos):
            self.clear_mask()
            event.accept()
            return
        ix, iy = self._display_to_image_coords(pos)
        if not self._brush_overlaps_image(ix, iy):
            super().mousePressEvent(event)
            return
        self._push_undo()
        self._painting = True
        self._stamp_brush(
            ix, iy, erase=self._option_erase_active(event)
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
            self._update_clear_button_cursor(pos)
            if moved:
                self.update()
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._end_paint()
            event.accept()
            return
        ix, iy = self._display_to_image_coords(pos)
        self._stamp_brush(
            ix, iy, erase=self._option_erase_active(event)
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
        was_painting = self._painting
        if self._painting:
            self.releaseMouse()
        self._painting = False
        if was_painting:
            self.maskChanged.emit()

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
        painter.fillRect(self.rect(), image_gen_preview_workarea_fill())
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


def _mask_undo_key_event(event: QKeyEvent) -> bool:
    return event.matches(QKeySequence.StandardKey.Undo)


def _mask_redo_key_event(event: QKeyEvent) -> bool:
    return event.matches(QKeySequence.StandardKey.Redo)


class _InfillPaintMaskUndoKeyFilter(QObject):
    """Mask undo/redo; blocks main-window file Undo while the mask stack has entries."""

    def __init__(
        self, canvas: InfillPaintCanvas, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas

    def _try_mask_redo(self, event: QKeyEvent) -> bool:
        if not _mask_redo_key_event(event) or not self._canvas._redo_stack:
            return False
        self._canvas.redo()
        event.accept()
        return True

    def _try_mask_undo(self, event: QKeyEvent) -> bool:
        if not _mask_undo_key_event(event) or not self._canvas._undo_stack:
            return False
        self._canvas.undo()
        event.accept()
        return True

    def _block_file_undo_shortcut(self, event: QKeyEvent) -> bool:
        """Accept ShortcutOverride so main-window file Undo does not run."""
        if _mask_redo_key_event(event) and self._canvas._redo_stack:
            event.accept()
            return True
        if _mask_undo_key_event(event) and self._canvas._undo_stack:
            event.accept()
            return True
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not _qobject_alive(self._canvas):
            return False
        if event.type() == QEvent.Type.ShortcutOverride:
            if not isinstance(event, QKeyEvent):
                return False
            self._block_file_undo_shortcut(event)
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isinstance(event, QKeyEvent):
            return False
        if self._try_mask_redo(event) or self._try_mask_undo(event):
            return True
        return False


def _attach_infill_paint_mask_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_infill_paint_mask_key_filter", None)
    if filt is None:
        return
    tracked: Set[int] = (
        getattr(host, "_infill_paint_mask_key_filter_widgets", None) or set()
    )
    for widget in (host, *host.findChildren(QWidget)):
        wid = id(widget)
        if wid in tracked:
            continue
        widget.installEventFilter(filt)
        tracked.add(wid)
    setattr(host, "_infill_paint_mask_key_filter_widgets", tracked)


def install_infill_paint_mask_keyboard_shortcuts(
    host: QWidget, canvas: InfillPaintCanvas | None
) -> None:
    """Cmd+Z / Cmd+Shift+Z — undo/redo mask strokes from prompt fields and canvas."""
    filt = getattr(host, "_infill_paint_mask_key_filter", None)
    if filt is None:
        filt = _InfillPaintMaskUndoKeyFilter(canvas, parent=host)
        setattr(host, "_infill_paint_mask_key_filter", filt)
    else:
        filt._canvas = canvas
    _attach_infill_paint_mask_key_filter(host)


def refresh_infill_paint_mask_keyboard_shortcuts(host: QWidget) -> None:
    """Attach mask undo key filter to widgets added after install."""
    _attach_infill_paint_mask_key_filter(host)
