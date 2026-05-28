#!/usr/bin/env python3
"""
Dialog for assigning names to multiple detected faces in one image.

UX:
 - Image preview with boxes around faces.
 - Click label (or box) to edit the name in an overlay QLineEdit.
 - OK returns per-face: (name, image_path, encoding).
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal, QTimer
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPixmap, QPen, QColor, QBrush
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QLineEdit,
)
import thumbnail_constants as tc

from exif_image_loader import load_image_with_exif_correction
from utils import show_styled_warning
from face_engine import (
    compare_faces,
    get_faces_with_locations_from_path,
)


TEXT_COLOR_HEX = tc.DIALOG_TEXT_COLOR_HEX
PLACEHOLDER_ADD = "Add..."
MIN_EDITOR_WIDTH_PX = 80


@dataclass
class _FaceUIState:
    face_id: str
    encoding: List[float]
    box_rect_display: QRect
    label_rect_display: QRect
    display_name: str

    # For hit testing / editor positioning
    editor: Optional[QLineEdit] = None


def _prime_face_display_name(encoding: List[float], subjects: List[Dict[str, Any]]) -> Optional[str]:
    """
    Attempt to derive an existing person's name for this face encoding.

    Uses known sample embeddings from `subjects` and `compare_faces`.
    Returns the first matching subject's name, else None.
    """
    if not encoding:
        return None

    for subject in subjects:
        name = (subject.get("name") or "").strip()
        if not name:
            continue
        samples = subject.get("samples") or []
        known_encodings: List[List[float]] = [s.get("embedding") for s in samples if s.get("embedding")]
        if not known_encodings:
            continue
        if compare_faces(known_encodings=[e for e in known_encodings if e], unknown_encoding=encoding):
            return name
    return None


class _FaceAssignCanvas(QWidget):
    """
    Paint widget that draws the scaled image, face boxes, and clickable labels.
    """

    inline_edit_started = Signal()
    inline_edit_finished = Signal()
    inline_edit_cancelled = Signal()

    def __init__(self, parent: Optional[QWidget], image_path: str, faces: List[Tuple[QRect, QRect]], labels: List[str]):
        super().__init__(parent)
        self.setMinimumSize(520, 420)
        self._image_path = image_path
        self._pixmap: Optional[QPixmap] = None
        if image_path and os.path.exists(image_path):
            self._pixmap = load_image_with_exif_correction(image_path, ignore_exif=False)

        self._face_boxes_and_labels: List[Tuple[QRect, QRect]] = faces
        self._labels: List[str] = labels

        # Map index -> rects in display coords
        self._rects: List[Tuple[QRect, QRect]] = faces

        self._editing_face_index: Optional[int] = None
        self._rename_editor: Optional[QLineEdit] = None
        self._rename_original_text: str = ""

        self._font = QFont("Arial", 13)

        # Derived values for coordinate mapping (set in paintEvent)
        self._scale: float = 1.0
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._draw_w: int = 0
        self._draw_h: int = 0

    def _ensure_label_width_for_text(self, st: _FaceUIState) -> None:
        """Expand label_rect_display to fit the full display name (font metrics)."""
        text = st.display_name if st.display_name else PLACEHOLDER_ADD
        fm = QFontMetrics(self._font)
        text_w = fm.horizontalAdvance(text) + 8  # padding
        r = st.label_rect_display
        if r.width() < text_w:
            # expand centered, keep same center
            dx = (text_w - r.width()) // 2
            st.label_rect_display = QRect(r.x() - dx, r.y(), text_w, r.height())

    def set_face_states(self, face_states: List[_FaceUIState]) -> None:
        self._face_states = face_states
        for st in face_states:
            self._ensure_label_width_for_text(st)
        self.update()

    def sizeHint(self):
        return self.minimumSize()

    def _label_at_pos(self, pos: QPoint) -> Optional[int]:
        for idx, st in enumerate(getattr(self, "_face_states", [])):
            if st.label_rect_display and st.label_rect_display.contains(pos):
                return idx
        return None

    def _box_at_pos(self, pos: QPoint) -> Optional[int]:
        for idx, st in enumerate(getattr(self, "_face_states", [])):
            if st.box_rect_display and st.box_rect_display.contains(pos):
                return idx
        return None

    def _is_in_image_area(self, pos: QPoint) -> bool:
        """True if pos is within the drawn image (pixmap) rect."""
        return (
            self._offset_x <= pos.x() < self._offset_x + self._draw_w
            and self._offset_y <= pos.y() < self._offset_y + self._draw_h
        )

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if not hasattr(self, "_face_states"):
            return
        clicked = self._label_at_pos(pos)
        if clicked is None:
            clicked = self._box_at_pos(pos)
        if self._rename_editor is not None:
            # Editing: click on image ends edit (avoids ending on OK/Cancel button clicks)
            if self._is_in_image_area(pos):
                if clicked is not None:
                    self._finish_inline_edit(emit_finished=False)
                    self._start_inline_edit(clicked)
                else:
                    self._finish_inline_edit()
            return
        if clicked is None:
            return
        self._start_inline_edit(clicked)

    def _cancel_inline_edit(self, restore: bool = True) -> None:
        if self._rename_editor is None:
            return
        try:
            self._rename_editor.hide()
            self._rename_editor.deleteLater()
        except Exception:
            pass
        self._rename_editor = None
        self._editing_face_index = None

        # restore text if needed
        if restore and hasattr(self, "_face_states"):
            for st in getattr(self, "_face_states", []):
                # nothing to do; state not modified until editing finished
                pass
        self.update()

    def _start_inline_edit(self, face_index: int) -> None:
        if face_index < 0 or face_index >= len(getattr(self, "_face_states", [])):
            return

        if self._rename_editor is not None:
            # Commit in-progress text before switching faces (don't focus OK mid-switch).
            self._finish_inline_edit(emit_finished=False)

        st = self._face_states[face_index]
        self._editing_face_index = face_index
        self._rename_original_text = st.display_name

        self._rename_editor = QLineEdit(self)
        # If placeholder "Add...", empty for typing
        initial_text = "" if (st.display_name == PLACEHOLDER_ADD or not st.display_name) else st.display_name
        self._rename_editor.setText(initial_text)
        self._rename_editor.selectAll()
        # Editor: at least 80px wide, centered on label rect
        r = st.label_rect_display
        w = max(MIN_EDITOR_WIDTH_PX, r.width())
        dx = (w - r.width()) // 2
        editor_rect = QRect(r.x() - dx, r.y(), w, r.height())
        self._rename_editor.setGeometry(editor_rect)
        self._rename_editor.setStyleSheet(
            """
            QLineEdit {
                border: 2px solid %s;
                border-radius: 0px;
                background-color: %s;
                color: %s;
                font-family: Arial;
                font-size: 13px;
                padding: 2px;
            }
            """ % (tc.CURRENT_IMAGE_BORDER_COLOR_HEX, tc.DIALOG_BACKGROUND_HEX, TEXT_COLOR_HEX)
        )
        self._rename_editor.installEventFilter(self)
        self._rename_editor.show()
        self._rename_editor.setFocus()
        self.inline_edit_started.emit()

    def eventFilter(self, watched, event: Any) -> bool:
        # Escape cancels; Enter or Return accepts (finish edit directly, no focus loss)
        if watched is self._rename_editor and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._cancel_inline_edit(restore=True)
                self.inline_edit_cancelled.emit()
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_inline_edit()
                return True
        return super().eventFilter(watched, event)

    def finish_pending_edit(self) -> None:
        """Finish any active inline edit (e.g. before OK reads results)."""
        if self._rename_editor is not None:
            self._finish_inline_edit(emit_finished=False)

    def _finish_inline_edit(self, emit_finished: bool = True) -> None:
        if self._rename_editor is None or self._editing_face_index is None:
            return
        text = (self._rename_editor.text() or "").strip()
        # Never save "Add..." as a name; treat empty as placeholder
        if not text or text == PLACEHOLDER_ADD:
            text = PLACEHOLDER_ADD
        idx = self._editing_face_index
        # Apply to model before tearing down the editor so any re-entrant OK/default-key
        # handling sees the committed name.
        if idx is not None and hasattr(self, "_face_states"):
            self._face_states[idx].display_name = text
            self._ensure_label_width_for_text(self._face_states[idx])
        self._cancel_inline_edit(restore=False)
        self.update()
        if emit_finished:
            self.inline_edit_finished.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.fillRect(self.rect(), tc.DEFAULT_BACKGROUND_COLOR)

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(tc.TEXT_COLOR)
            painter.drawText(self.rect(), Qt.AlignCenter, "Image unavailable")
            return

        # Scale the image to fit while keeping aspect ratio.
        target = self.rect().adjusted(10, 10, -10, -10)
        pm_size = self._pixmap.size()
        if pm_size.width() <= 0 or pm_size.height() <= 0:
            return

        scale = min(target.width() / pm_size.width(), target.height() / pm_size.height())
        self._scale = scale
        draw_w = int(pm_size.width() * scale)
        draw_h = int(pm_size.height() * scale)
        self._draw_w = draw_w
        self._draw_h = draw_h
        self._offset_x = target.x() + (target.width() - draw_w) // 2
        self._offset_y = target.y() + (target.height() - draw_h) // 2

        # Draw scaled image
        scaled = self._pixmap.scaled(draw_w, draw_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(self._offset_x, self._offset_y, scaled)

        # Draw face overlays (rects already in display coords)
        for st in getattr(self, "_face_states", []):
            # box
            painter.setPen(QPen(tc.CURRENT_IMAGE_BORDER_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(st.box_rect_display)

            # label bg
            painter.setPen(Qt.NoPen)
            label_bg = QColor(tc.DIALOG_BACKGROUND_HEX)
            label_bg.setAlpha(220)
            painter.setBrush(QBrush(label_bg))
            painter.drawRect(st.label_rect_display)

            # label text
            painter.setPen(tc.TEXT_COLOR)
            painter.setFont(self._font)
            painter.drawText(st.label_rect_display, Qt.AlignCenter, st.display_name if st.display_name else PLACEHOLDER_ADD)


class FaceAssignDialog(QDialog):
    def __init__(self, parent: QWidget, image_path: str, subjects: List[Dict[str, Any]]):
        super().__init__(parent)
        self.setWindowTitle("Assign faces")
        self._subjects = subjects
        self._image_path = image_path
        self._result: List[Tuple[str, str, List[float]]] = []

        self._canvas: Optional[_FaceAssignCanvas] = None

        layout = QVBoxLayout(self)

        header = QLabel("Click a face label to rename it.")
        header.setWordWrap(True)
        layout.addWidget(header)

        self._canvas = _FaceAssignCanvas(self, image_path, faces=[], labels=[])
        layout.addWidget(self._canvas, 1)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)  # Make OK the default button for Enter
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._on_ok)
        # Defer focus so the same Return/Enter that committed the line edit does not
        # immediately activate the default OK button (would re-enter _on_ok with bad timing).
        self._btn_ok = btn_ok
        self._btn_cancel = btn_cancel
        self._canvas.inline_edit_started.connect(self._on_inline_edit_started)
        self._canvas.inline_edit_finished.connect(self._schedule_focus_ok_after_inline_edit)
        self._canvas.inline_edit_cancelled.connect(self._on_inline_edit_cancelled)

        self._init_faces()

    def _on_inline_edit_started(self) -> None:
        if self._btn_ok is not None:
            self._btn_ok.setDefault(False)
            self._btn_ok.setAutoDefault(False)

    def _on_inline_edit_cancelled(self) -> None:
        if self._btn_ok is not None:
            self._btn_ok.setDefault(True)
            self._btn_ok.setAutoDefault(True)

    def _schedule_focus_ok_after_inline_edit(self) -> None:
        QTimer.singleShot(0, self._focus_ok_after_inline_edit)

    def _focus_ok_after_inline_edit(self) -> None:
        if self._btn_ok is not None:
            self._btn_ok.setDefault(True)
            self._btn_ok.setAutoDefault(True)
            self._btn_ok.setFocus(Qt.OtherFocusReason)

    def _focus_cancel_after_no_faces(self) -> None:
        if self._btn_cancel is not None:
            self._btn_cancel.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self._canvas is not None and getattr(self._canvas, "_rename_editor", None) is not None:
                self._canvas._finish_inline_edit()
                event.accept()
                return
        super().keyPressEvent(event)

    def _init_faces(self) -> None:
        detections = get_faces_with_locations_from_path(self._image_path)
        if not detections:
            show_styled_warning(self, "No face detected", "No faces were detected in the selected image.")
            if self._btn_ok is not None:
                self._btn_ok.setEnabled(False)
                self._btn_ok.setDefault(False)
                self._btn_ok.setAutoDefault(False)
            if self._btn_cancel is not None:
                self._btn_cancel.setDefault(True)
                self._btn_cancel.setAutoDefault(True)
            QTimer.singleShot(0, self._focus_cancel_after_no_faces)
            return

        # Coordinate mapping:
        # We compute display rects after the widget is sized; but we can approximate by using
        # current canvas rect (paintEvent recomputes scale; labels should still visually align).
        # For simplicity, compute based on current canvas rect size.
        canvas_rect = self._canvas.rect() if self._canvas else QRect(0, 0, 520, 420)
        target = canvas_rect.adjusted(10, 10, -10, -10)

        pix = load_image_with_exif_correction(self._image_path, ignore_exif=False) if os.path.exists(self._image_path) else None
        if not pix or pix.isNull():
            return
        pm_size = pix.size()
        scale = min(target.width() / pm_size.width(), target.height() / pm_size.height())
        draw_w = int(pm_size.width() * scale)
        draw_h = int(pm_size.height() * scale)
        offset_x = target.x() + (target.width() - draw_w) // 2
        offset_y = target.y() + (target.height() - draw_h) // 2

        # Prime labels and construct rects in display coords.
        face_states: List[_FaceUIState] = []
        for loc, enc in detections:
            top, right, bottom, left = loc
            # face_locations coords are in image pixel space
            x1 = offset_x + int(left * scale)
            y1 = offset_y + int(top * scale)
            x2 = offset_x + int(right * scale)
            y2 = offset_y + int(bottom * scale)
            box_rect_display = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))

            label_h = 24
            label_pad = 2
            # label below the face box
            lx = box_rect_display.x()
            ly = box_rect_display.bottom() + label_pad
            lw = box_rect_display.width()
            label_rect_display = QRect(lx, ly, lw, label_h)

            derived = _prime_face_display_name(enc, self._subjects) or PLACEHOLDER_ADD

            face_states.append(
                _FaceUIState(
                    face_id=str(uuid.uuid4()),
                    encoding=enc,
                    box_rect_display=box_rect_display,
                    label_rect_display=label_rect_display,
                    display_name=derived,
                )
            )

        assert self._canvas is not None
        self._canvas.set_face_states(face_states)

    def _on_ok(self) -> None:
        if not self._canvas:
            self.accept()
            return
        self._canvas.finish_pending_edit()
        faces = getattr(self._canvas, "_face_states", [])
        results: List[Tuple[str, str, List[float]]] = []
        for st in faces:
            name = (st.display_name or "").strip()
            # Allow the user to ignore some detected faces by leaving them as "Add...".
            if not name or name == PLACEHOLDER_ADD:
                continue
            results.append((name, self._image_path, st.encoding))

        # Require at least one named face.
        if not results:
            show_styled_warning(
                self,
                "Missing name",
                f"Please name at least one face (or leave the others as \"{PLACEHOLDER_ADD}\").",
            )
            if self._btn_ok is not None:
                self._btn_ok.setDefault(True)
                self._btn_ok.setAutoDefault(True)
            return

        self._result = results
        self.accept()

    def get_result(self) -> List[Tuple[str, str, List[float]]]:
        return self._result

