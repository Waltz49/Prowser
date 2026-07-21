#!/usr/bin/env python3
"""Interactive canvas for placing and resizing source image on expand target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from exif.exif_image_loader import load_image_with_exif_correction

from imagegen_plugins.image_gen_dialog import image_gen_preview_workarea_fill

MIN_PLACEMENT_EDGE = 128
HANDLE_SIZE = 14
HANDLE_HIT_PAD = 8
TARGET_BORDER_WIDTH = 4  # drawn outside target interior (display pixels)
# Target canvas (letterboxed inside black work area)
CANVAS_FILL = QColor(72, 72, 72)
CANVAS_BORDER_OUTER = QColor(255, 255, 255)
CANVAS_BORDER_INNER = QColor(30, 30, 30)
PLACEMENT_OUTLINE = QColor(100, 180, 255)
HANDLE_FILL = QColor(80, 160, 255)


@dataclass
class _RelativePlacement:
    cx: float
    cy: float
    w_frac: float
    placement_aspect: float  # placement_w / placement_h when stored


class ExpandPlacementCanvas(QWidget):
    """Black work area with bordered target canvas; draggable/resizable source overlay."""

    placementChanged = Signal()

    def __init__(self, source_path: str, canvas_w: int, canvas_h: int, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._source_path = source_path
        self._source_pixmap: Optional[QPixmap] = None
        if source_path:
            self._source_pixmap = load_image_with_exif_correction(
                source_path, ignore_exif=False
            )

        self._canvas_w = max(MIN_PLACEMENT_EDGE, int(canvas_w))
        self._canvas_h = max(MIN_PLACEMENT_EDGE, int(canvas_h))
        self._placement_x = 0
        self._placement_y = 0
        self._placement_w = MIN_PLACEMENT_EDGE
        self._placement_h = MIN_PLACEMENT_EDGE
        self._rel: Optional[_RelativePlacement] = None

        self._canvas_rect = QRect()
        self._scale = 1.0

        self._drag_mode: Optional[str] = None  # "move" | "resize"
        self._press_pos = QPoint()
        self._press_placement = (0, 0, 0, 0)

        self._reset_initial_placement()

    def _event_pos(self, event) -> QPoint:
        """Widget-local pixel coordinates (do not mapFromGlobal — breaks on dialogs/Retina)."""
        if hasattr(event, "position"):
            pt = event.position()
            return pt.toPoint() if hasattr(pt, "toPoint") else QPoint(int(pt.x()), int(pt.y()))
        return event.pos()

    def source_size(self) -> Tuple[int, int]:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return (MIN_PLACEMENT_EDGE, MIN_PLACEMENT_EDGE)
        return self._source_pixmap.width(), self._source_pixmap.height()

    def _source_aspect_ratio(self) -> float:
        sw, sh = self.source_size()
        return sw / sh if sh > 0 else 1.0

    def _clamp_size_in_canvas(
        self, w: int, h: int, max_w: int, max_h: int
    ) -> Tuple[int, int]:
        w = max(MIN_PLACEMENT_EDGE, min(int(w), max_w))
        h = max(MIN_PLACEMENT_EDGE, min(int(h), max_h))
        return w, h

    def _clamp_aspect_size(
        self, w: int, h: int, aspect: float, max_w: int, max_h: int
    ) -> Tuple[int, int]:
        """Fit (w,h) to aspect; min/max on one axis pins the other (uniform scale)."""
        aspect = max(0.01, float(aspect))
        max_w = max(MIN_PLACEMENT_EDGE, int(max_w))
        max_h = max(MIN_PLACEMENT_EDGE, int(max_h))

        w = float(max(1, int(w)))
        h = w / aspect

        def _fit_max() -> None:
            nonlocal w, h
            scale = min(1.0, max_w / w, max_h / h)
            w *= scale
            h = w / aspect

        def _fit_min() -> None:
            nonlocal w, h
            scale = max(1.0, MIN_PLACEMENT_EDGE / w, MIN_PLACEMENT_EDGE / h)
            w *= scale
            h = w / aspect

        _fit_max()
        _fit_min()
        _fit_max()

        wi = int(round(w))
        hi = int(round(wi / aspect))
        if hi > max_h:
            hi = max_h
            wi = int(round(hi * aspect))
        if wi > max_w:
            wi = max_w
            hi = int(round(wi / aspect))
        if wi < MIN_PLACEMENT_EDGE:
            wi = MIN_PLACEMENT_EDGE
            hi = int(round(wi / aspect))
        if hi < MIN_PLACEMENT_EDGE:
            hi = MIN_PLACEMENT_EDGE
            wi = int(round(hi * aspect))
            wi = min(wi, max_w)
            hi = int(round(wi / aspect))

        wi = max(MIN_PLACEMENT_EDGE, min(wi, max_w))
        hi = max(MIN_PLACEMENT_EDGE, min(int(round(wi / aspect)), max_h))
        if int(round(wi / aspect)) != hi and hi == max_h:
            wi = max(MIN_PLACEMENT_EDGE, min(int(round(hi * aspect)), max_w))
            hi = int(round(wi / aspect))
        return wi, hi

    def _apply_resize_drag(
        self,
        px: int,
        py: int,
        pw: int,
        ph: int,
        cdx: int,
        cdy: int,
        *,
        free_aspect: bool,
    ) -> None:
        self._placement_x = px
        self._placement_y = py
        max_w = self._canvas_w - px
        max_h = self._canvas_h - py

        if free_aspect:
            self._placement_w, self._placement_h = self._clamp_size_in_canvas(
                pw + cdx, ph + cdy, max_w, max_h
            )
            return

        aspect = self._source_aspect_ratio()
        w_from_width = pw + cdx
        h_from_width = w_from_width / aspect
        w_from_height = (ph + cdy) * aspect
        h_from_height = ph + cdy

        if abs(cdx) >= abs(cdy) * aspect:
            new_w, new_h = w_from_width, h_from_width
        else:
            new_w, new_h = w_from_height, h_from_height

        self._placement_w, self._placement_h = self._clamp_aspect_size(
            new_w, new_h, aspect, max_w, max_h
        )

    def set_source_path(self, source_path: str) -> None:
        """Load a new source image and reset placement to the default fit."""
        self._source_path = source_path
        self._source_pixmap = None
        if source_path:
            self._source_pixmap = load_image_with_exif_correction(
                source_path, ignore_exif=False
            )
        self._reset_initial_placement()
        self.update()

    def set_canvas_size(self, width: int, height: int) -> None:
        width = max(MIN_PLACEMENT_EDGE, int(width))
        height = max(MIN_PLACEMENT_EDGE, int(height))
        if width == self._canvas_w and height == self._canvas_h:
            return
        self._store_relative()
        self._canvas_w = width
        self._canvas_h = height
        self._apply_relative()
        self.update()
        self.placementChanged.emit()

    def canvas_placement(self) -> Tuple[int, int, int, int]:
        return (
            self._placement_x,
            self._placement_y,
            self._placement_w,
            self._placement_h,
        )

    def set_canvas_placement(
        self, px: int, py: int, pw: int, ph: int, *, emit_changed: bool = False
    ) -> None:
        """Restore absolute placement on the current canvas size."""
        cw, ch = self._canvas_w, self._canvas_h
        max_w = max(MIN_PLACEMENT_EDGE, cw)
        max_h = max(MIN_PLACEMENT_EDGE, ch)
        pw_i = max(MIN_PLACEMENT_EDGE, min(int(pw), max_w))
        ph_i = max(MIN_PLACEMENT_EDGE, min(int(ph), max_h))
        px_i = max(0, min(int(px), cw - pw_i))
        py_i = max(0, min(int(py), ch - ph_i))
        self._placement_x = px_i
        self._placement_y = py_i
        self._placement_w = pw_i
        self._placement_h = ph_i
        self._clamp_placement_position()
        self._store_relative()
        self.update()
        if emit_changed:
            self.placementChanged.emit()

    def _reset_initial_placement(self) -> None:
        self._apply_top_centered_fit(emit_changed=False)

    def _apply_top_centered_fit(self, *, emit_changed: bool = True) -> None:
        """Fit source at top, horizontally centered; max size that fits canvas."""
        aspect = self._source_aspect_ratio()
        cw, ch = self._canvas_w, self._canvas_h
        pw = cw
        ph = int(round(pw / aspect))
        if ph > ch:
            ph = ch
            pw = int(round(ph * aspect))
        pw, ph = self._clamp_aspect_size(pw, ph, aspect, cw, ch)
        self._placement_w = pw
        self._placement_h = ph
        self._placement_x = (cw - pw) // 2
        self._placement_y = 0
        self._clamp_placement_position()
        self._store_relative()
        self.update()
        if emit_changed:
            self.placementChanged.emit()

    def _store_relative(self) -> None:
        cx = self._placement_x + self._placement_w / 2
        cy = self._placement_y + self._placement_h / 2
        aspect = self._placement_w / max(1, self._placement_h)
        self._rel = _RelativePlacement(
            cx=cx / max(1, self._canvas_w),
            cy=cy / max(1, self._canvas_h),
            w_frac=self._placement_w / max(1, self._canvas_w),
            placement_aspect=aspect,
        )

    def _apply_relative(self) -> None:
        if self._rel is None:
            self._reset_initial_placement()
            return
        aspect = max(0.01, self._rel.placement_aspect)
        max_w = self._canvas_w
        max_h = self._canvas_h
        pw = max(MIN_PLACEMENT_EDGE, int(self._rel.w_frac * self._canvas_w))
        ph = max(MIN_PLACEMENT_EDGE, int(round(pw / aspect)))
        pw, ph = self._clamp_aspect_size(pw, ph, aspect, max_w, max_h)
        cx = self._rel.cx * self._canvas_w
        cy = self._rel.cy * self._canvas_h
        self._placement_w = pw
        self._placement_h = ph
        self._placement_x = int(cx - pw / 2)
        self._placement_y = int(cy - ph / 2)
        self._clamp_placement_position()

    def _clamp_placement_position(self) -> None:
        """Keep placement size; only clamp position inside the target canvas."""
        self._placement_x = max(
            0, min(self._placement_x, self._canvas_w - self._placement_w)
        )
        self._placement_y = max(
            0, min(self._placement_y, self._canvas_h - self._placement_h)
        )

    def _update_canvas_geometry(self) -> None:
        margin = 20
        border = TARGET_BORDER_WIDTH
        avail_w = max(1, self.width() - 2 * margin - 2 * border)
        avail_h = max(1, self.height() - 2 * margin - 2 * border)
        scale = min(avail_w / self._canvas_w, avail_h / self._canvas_h)
        draw_w = max(1, int(self._canvas_w * scale))
        draw_h = max(1, int(self._canvas_h * scale))
        frame_w = draw_w + 2 * border
        frame_h = draw_h + 2 * border
        off_x = (self.width() - frame_w) // 2 + border
        off_y = (self.height() - frame_h) // 2 + border
        self._canvas_rect = QRect(off_x, off_y, draw_w, draw_h)
        self._scale = scale

    def _target_border_display_rect(self) -> QRect:
        """Border frame surrounding the target interior (outside image area)."""
        r = self._canvas_rect
        bw = TARGET_BORDER_WIDTH
        return QRect(r.x() - bw, r.y() - bw, r.width() + 2 * bw, r.height() + 2 * bw)

    def _canvas_to_display(self, cx: int, cy: int, cw: int, ch: int) -> QRect:
        r = self._canvas_rect
        return QRect(
            r.x() + int(round(cx * self._scale)),
            r.y() + int(round(cy * self._scale)),
            max(1, int(round(cw * self._scale))),
            max(1, int(round(ch * self._scale))),
        )

    def _display_to_canvas_delta(self, dx: int, dy: int) -> Tuple[int, int]:
        if self._scale <= 0:
            return 0, 0
        return int(round(dx / self._scale)), int(round(dy / self._scale))

    def _placement_display_rect(self) -> QRect:
        pr = self._canvas_to_display(
            self._placement_x,
            self._placement_y,
            self._placement_w,
            self._placement_h,
        )
        return pr.intersected(self._canvas_rect)

    def _handle_display_rect(self) -> QRect:
        pr = self._placement_display_rect()
        hs = HANDLE_SIZE
        return QRect(pr.right() - hs + 1, pr.bottom() - hs + 1, hs, hs)

    def _handle_hit_rect(self) -> QRect:
        return self._handle_display_rect().adjusted(
            -HANDLE_HIT_PAD, -HANDLE_HIT_PAD, HANDLE_HIT_PAD, HANDLE_HIT_PAD
        )

    def _hit_test(self, pos: QPoint) -> Optional[str]:
        if not self._canvas_rect.contains(pos):
            return None
        if self._handle_hit_rect().contains(pos):
            return "resize"
        if self._placement_display_rect().contains(pos):
            return "move"
        return None

    def _end_drag(self) -> None:
        if self._drag_mode is not None:
            self.releaseMouse()
        self._drag_mode = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._update_canvas_geometry()
        pos = self._event_pos(event)
        mode = self._hit_test(pos)
        if mode is None:
            super().mousePressEvent(event)
            return
        self._drag_mode = mode
        self._press_pos = pos
        self._press_placement = self.canvas_placement()
        self.grabMouse()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setCursor(
            Qt.CursorShape.SizeFDiagCursor
            if mode == "resize"
            else Qt.CursorShape.ClosedHandCursor
        )
        event.accept()

    def mouseMoveEvent(self, event):
        pos = self._event_pos(event)
        self._update_canvas_geometry()
        if self._drag_mode is None:
            hit = self._hit_test(pos)
            if hit == "resize":
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif hit == "move":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)
            return

        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._end_drag()
            event.accept()
            return

        dx = pos.x() - self._press_pos.x()
        dy = pos.y() - self._press_pos.y()
        cdx, cdy = self._display_to_canvas_delta(dx, dy)
        px, py, pw, ph = self._press_placement

        if self._drag_mode == "move":
            self._placement_x = px + cdx
            self._placement_y = py + cdy
            self._clamp_placement_position()
        else:
            free_aspect = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._apply_resize_drag(
                px, py, pw, ph, cdx, cdy, free_aspect=free_aspect
            )
            self._clamp_placement_position()
        self._store_relative()
        self.update()
        self.placementChanged.emit()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self._update_canvas_geometry()
        pos = self._event_pos(event)
        if self._placement_display_rect().contains(pos):
            self._apply_top_centered_fit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_canvas_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_canvas_geometry()

    def sizeHint(self) -> QSize:
        return QSize(520, 360)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), image_gen_preview_workarea_fill())
        self._update_canvas_geometry()
        r = self._canvas_rect

        # Target canvas interior (image area only; border drawn outside)
        painter.fillRect(r, CANVAS_FILL)

        if self._source_pixmap is None or self._source_pixmap.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "Image unavailable")
            self._paint_target_border(painter)
            return

        pr = self._placement_display_rect()
        if pr.isEmpty():
            self._paint_target_border(painter)
            return

        # Clip image to target interior only
        painter.save()
        painter.setClipRect(r)
        scaled = self._source_pixmap.scaled(
            pr.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(pr.topLeft(), scaled)
        painter.restore()

        # Outline around placed image (within target)
        painter.setPen(
            QPen(
                PLACEMENT_OUTLINE,
                1,
                Qt.PenStyle.DashLine,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(pr.adjusted(0, 0, -1, -1))

        # Resize handle (lower-right of placement)
        hr = self._handle_display_rect()
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QBrush(HANDLE_FILL))
        painter.drawRect(hr)

        self._paint_target_border(painter)

    def _paint_target_border(self, painter: QPainter) -> None:
        """Draw target frame outside the interior so it does not overlap the image."""
        outer = self._target_border_display_rect()
        painter.setPen(QPen(CANVAS_BORDER_OUTER, TARGET_BORDER_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(outer)
        inner = self._canvas_rect.adjusted(-1, -1, 0, 0)
        painter.setPen(QPen(CANVAS_BORDER_INNER, 1))
        painter.drawRect(inner)
