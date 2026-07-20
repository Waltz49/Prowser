#!/usr/bin/env python3
"""
Quick Person Search: for 1–4 selected images, save face samples under the known-faces
subject "Z Quick Person", then open Search by person (cmd-P). When multiple faces are in
one image, a dialog shows the image with boxes; the clicked face is used. Single-face
images use that face directly. The person dialog shows one 96px thumbnail (first sample).
"""

import os
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from theme.theme_service import get_active_theme
import thumbnails.thumbnail_constants as tc

# Reserved subject name for quick multi-sample search (max 4 samples).
QUICK_PERSON_SUBJECT_NAME = "Z Quick Person"

MAX_QUICK_PERSON_IMAGES = 4

# Match previous quick-person encoding quality (was get_largest_face_encoding_from_path).
_QUICK_PERSON_ENCODING_MODEL = "large"

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
        th = get_active_theme()
        painter.fillRect(self.rect(), QColor(th.dialog_background_hex))

        self._layout_boxes = []
        self._hit_geom_ready = False

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(th.dialog_text_color_hex))
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


def get_deduped_selected_image_paths(main_window) -> list[str]:
    """Existing file paths from current selection, display order, unique by normpath."""
    mw = main_window
    if not hasattr(mw, "selection_manager") or not mw.selection_manager:
        return []
    sel = mw.selection_manager.get_selected_files()
    out: list[str] = []
    seen: set[str] = set()
    for p in sel:
        if not p or not os.path.isfile(p):
            continue
        nk = os.path.normpath(p)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(p)
    return out


def _subject_id_for_quick_person() -> str | None:
    """Return subject id for QUICK_PERSON_SUBJECT_NAME, creating the subject if needed."""
    from faces.known_faces_manager import list_subjects, add_subject

    for s in list_subjects():
        if (s.get("name") or "").strip() == QUICK_PERSON_SUBJECT_NAME:
            return s.get("id")
    return add_subject(QUICK_PERSON_SUBJECT_NAME)


def _replace_all_samples(subject_id: str, path_embeddings: list[tuple[str, list]]) -> bool:
    """Clear subject samples, then add each (path, embedding) in order (len <= 4)."""
    from faces.known_faces_manager import get_subject, remove_sample, add_sample

    if not get_subject(subject_id):
        return False
    while True:
        sub = get_subject(subject_id)
        samples = sub.get("samples") or []
        if not samples:
            break
        if not remove_sample(subject_id, 0):
            return False
    for image_path, embedding in path_embeddings:
        if not add_sample(subject_id, image_path, embedding):
            return False
    return True


def run_quick_person_search(main_window) -> None:
    """Entry point from Search > Quick Person Search."""
    try:
        from bundle_capabilities import faces_ui_enabled

        if not faces_ui_enabled():
            return
    except ImportError:
        pass
    from utils import show_styled_warning
    from faces.face_engine import is_available, get_faces_with_locations_and_rgb_from_path

    mw = main_window
    if getattr(mw, "current_view_mode", None) not in ("thumbnail", "browse"):
        return

    if not is_available():
        show_styled_warning(mw, "Quick Person Search", "Face recognition is not available.")
        return

    paths = get_deduped_selected_image_paths(mw)
    if len(paths) > MAX_QUICK_PERSON_IMAGES:
        show_styled_warning(
            mw,
            "Quick Person Search",
            f"Too many images selected ({len(paths)}).\nSelect at most {MAX_QUICK_PERSON_IMAGES} images.",
        )
        return
    if not paths:
        show_styled_warning(
            mw,
            "Quick Person Search",
            "No images selected.\nSelect 1 to 4 images with at least one face each.",
        )
        return

    path_rows: list[tuple[str, list, Any, tuple[int, int, int, int]]] = []
    errors: list[str] = []
    for path in paths:
        preview_pm = None
        detections, rgb = get_faces_with_locations_and_rgb_from_path(
            path, encoding_model=_QUICK_PERSON_ENCODING_MODEL
        )
        if not detections:
            errors.append(f"{path}\n  No faces found or could not encode.")
            continue

        if len(detections) > 1:
            # Left-to-right, then top-to-bottom (face_recognition order is not spatial).
            detections = sorted(list(detections), key=lambda d: (d[0][3], d[0][0]))

        emb: list | None = None
        chosen_index: int = 0
        if len(detections) == 1:
            emb = list(detections[0][1])
            chosen_index = 0
        else:
            if rgb is None:
                errors.append(f"{path}\n  No faces found or could not encode.")
                continue
            from PIL import Image
            from exif.exif_image_loader import pil_to_qpixmap

            preview = pil_to_qpixmap(Image.fromarray(rgb), preserve_alpha=False)
            if preview is None or preview.isNull():
                errors.append(f"{path}\n  Could not build preview for face picker.")
                continue
            preview_pm = preview
            dlg = QuickPersonFacePickDialog(mw, detections, preview)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            res = dlg.get_result()
            if not res:
                return
            chosen_index, emb = res

        if not emb or len(emb) != 128:
            errors.append(f"{path}\n  No faces found or could not encode.")
            continue

        if getattr(mw, "debug_mode", False):
            import numpy as np

            ref = np.array(detections[chosen_index][1], dtype=np.float64)
            got = np.array(emb, dtype=np.float64)
            if ref.shape != got.shape or not np.allclose(ref, got):
                print(
                    f"[Quick Person] debug: embedding mismatch for face index {chosen_index} path={path!r}"
                )
            else:
                print(
                    f"[Quick Person] debug: face index {chosen_index} embedding matches detection path={path!r}"
                )
            if preview_pm is not None and rgb is not None:
                if preview_pm.width() != rgb.shape[1] or preview_pm.height() != rgb.shape[0]:
                    print(
                        f"[Quick Person] debug: preview size {preview_pm.width()}x{preview_pm.height()} "
                        f"!= rgb {rgb.shape[1]}x{rgb.shape[0]} path={path!r}"
                    )

        trbl = detections[chosen_index][0]
        picked_trbl = (int(trbl[0]), int(trbl[1]), int(trbl[2]), int(trbl[3]))
        path_rows.append((path, emb, rgb, picked_trbl))

    if errors:
        warning_title = "Quick Person Search"
        error_sep = "\n\n"
        if len(paths) == 1:
            warning_body = f"No faces were found.\n\n{error_sep.join(errors)}"
        else:
            warning_body = f"Some images could not be used.\n\n{error_sep.join(errors)}"
        show_styled_warning(mw, warning_title, warning_body)
        return


    if not path_rows:
        show_styled_warning(mw, "Quick Person Search", "No valid face samples to save.")
        return

    sid = _subject_id_for_quick_person()
    if not sid:
        show_styled_warning(
            mw,
            "Quick Person Search",
            f'Could not create or find the "{QUICK_PERSON_SUBJECT_NAME}" person.',
        )
        return

    path_embeddings = [(p, e) for p, e, _rgb, _tr in path_rows]
    if not _replace_all_samples(sid, path_embeddings):
        show_styled_warning(mw, "Quick Person Search", "Could not save the face samples.")
        return

    try:
        from faces.face_sample_thumbnail import ensure_face_sample_thumbnail
        for path, emb, rgb, picked_trbl in path_rows:
            try:
                ensure_face_sample_thumbnail(
                    path, emb, alignment_rgb=rgb, picked_face_trbl=picked_trbl
                )
            except Exception:
                pass
    except Exception:
        pass
    try:
        mw.on_known_faces_external_update()
    except Exception:
        pass

    try:
        mw.config.update_setting("find_person_subject_id", sid)
    except Exception:
        pass

    tree_had_focus = mw._tree_has_focus() if hasattr(mw, "_tree_has_focus") else False
    mw._tree_had_focus_when_invoked = tree_had_focus
    try:
        mw.show_filter_by_person_dialog()
    finally:
        mw._tree_had_focus_when_invoked = False
