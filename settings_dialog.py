#!/usr/bin/env python3
"""
Settings Dialog for Image Browser
Allows users to configure debug mode and confirm delete settings
"""

# Standard library imports
import copy
import fnmatch
import json
import os
import uuid
import logging
from pathlib import Path
from exif.exif_image_loader import load_image_with_exif_correction
from faces.face_engine import compare_faces, get_faces_with_locations_from_path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from PySide6.QtCore import Qt, Signal, QTimer, QObject, QEvent, QMutexLocker, QPoint, QRect
from PySide6.QtGui import QFont, QColor, QPixmap, QIcon, QFontMetrics, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton, 
    QGroupBox, QFormLayout, QDialogButtonBox, QFrame, QSpinBox, QDoubleSpinBox,
    QComboBox, QGridLayout, QMessageBox, QSizePolicy, QWidget, QTabWidget,
    QLineEdit, QTextEdit, QFileDialog, QSlider, QRadioButton, QButtonGroup,
    QColorDialog, QApplication, QScrollArea, QProgressDialog
)
import thumbnails.thumbnail_constants as tc
from thumbnails.thumbnail_constants import (
    TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX, TAB_BUTTON_FOCUS_BORDER_COLOR_HEX,
    DIALOG_BACKGROUND_HEX, BORDER_DEFAULT_HEX, BORDER_HOVER_HEX, WIDGET_BG_HOVER_HEX,
    TAB_BUTTON_HOVER_BG_HEX, BUTTON_BG_DEFAULT_HEX,
    BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX, BUTTON_BG_HOVER_HEX,
    BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX, BUTTON_BG_PRESSED_HEX,
    BUTTON_FOCUS_TEXT_HEX, BUTTON_DEFAULT_BG_HEX, BUTTON_DEFAULT_BORDER_HEX,
    TEXT_DISABLED_HEX, ERROR_COLOR_HEX, VALIDATION_SUCCESS_COLOR_HEX,
    CURRENT_IMAGE_BACKGROUND_COLOR, CURRENT_IMAGE_BORDER_COLOR,
    CURRENT_IMAGE_BORDER_COLOR_HEX, SIDEBAR_SPLITTER_HANDLE_HEX,
    DEFAULT_BORDER_COLOR_HEX,
    MAX_THEME_BORDER_WIDTH_PX,
    MIN_VIEW_CHROME_BORDER_WIDTH_PX,
    MAX_VIEW_CHROME_BORDER_WIDTH_PX,
    CMD_SYMBOL, OPTION_SYMBOL, SHIFT_SYMBOL, ENTER_SYMBOL, CTRL_SYMBOL,
)

# macOS-specific imports for application selection
MACOS_APP_SELECTION_AVAILABLE = False
NSOpenPanel = None
NSModalResponseOK = None
NSWorkspace = None
LSCopyAllRoleHandlersForContentType = None
kLSRolesAll = None
kUTTypeImage = None
NSURL = None

try:
    from AppKit import NSOpenPanel, NSModalResponseOK, NSWorkspace
    from LaunchServices import (
        LSCopyAllRoleHandlersForContentType,
        kLSRolesAll
    )
    from CoreServices import kUTTypeImage
    from Foundation import NSURL
    MACOS_APP_SELECTION_AVAILABLE = True
except ImportError:
    MACOS_APP_SELECTION_AVAILABLE = False

# Local imports
from config import (
    get_config,
    ImageBrowserConfig,
    default_browse_transparency_entry,
    default_browse_transparency_settings,
    merge_browse_transparency_settings,
)
from thumbnails.thumbnail_constants import get_image_extensions, clear_image_extensions_cache, DIALOG_TEXT_COLOR_HEX, asset_path
from utils import format_file_size, styled_message_box, show_styled_warning, show_styled_information, show_styled_critical, show_styled_question
from theme.theme_service import (
    apply_theme,
    default_dark_theme_colors,
    default_light_theme_colors,
    default_user_theme_colors,
    get_active_theme,
    merge_dark_theme_colors,
    merge_light_theme_colors,
    merge_user_theme_colors,
    normalize_theme_id,
    resolve_theme_id_for_apply,
    USER_THEME_COLOR_KEYS,
    THEME_BORDER_WIDTH_KEYS,
    VIEW_CHROME_THEME_KEYS,
    theme_apply_scope_for_keys,
)
from theme.spin_box import StepSpinBox


_THEME_SYNC_CONSTANTS = (
    "TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX",
    "TAB_BUTTON_FOCUS_BORDER_COLOR_HEX",
    "DIALOG_BACKGROUND_HEX",
    "DIALOG_INPUT_BACKGROUND_HEX",
    "BORDER_DEFAULT_HEX",
    "BORDER_HOVER_HEX",
    "WIDGET_BG_HOVER_HEX",
    "TAB_BUTTON_HOVER_BG_HEX",
    "BUTTON_BG_DEFAULT_HEX",
    "BUTTON_TEXT_DEFAULT_HEX",
    "BUTTON_BORDER_DEFAULT_HEX",
    "BUTTON_BG_HOVER_HEX",
    "BUTTON_TEXT_HOVER_HEX",
    "BUTTON_BORDER_HOVER_HEX",
    "BUTTON_BG_PRESSED_HEX",
    "BUTTON_FOCUS_TEXT_HEX",
    "BUTTON_DEFAULT_BG_HEX",
    "BUTTON_DEFAULT_BORDER_HEX",
    "TEXT_DISABLED_HEX",
    "ERROR_COLOR_HEX",
    "VALIDATION_SUCCESS_COLOR_HEX",
    "CURRENT_IMAGE_BACKGROUND_COLOR",
    "CURRENT_IMAGE_BORDER_COLOR",
    "CURRENT_IMAGE_BORDER_COLOR_HEX",
    "SIDEBAR_SPLITTER_HANDLE_HEX",
    "DEFAULT_BORDER_COLOR_HEX",
    "DIALOG_TEXT_COLOR_HEX",
)


def _refresh_theme_constants_from_thumbnail_constants():
    """Refresh module-level theme constants from the active palette."""
    g = globals()
    for name in _THEME_SYNC_CONSTANTS:
        if hasattr(tc, name):
            g[name] = getattr(tc, name)


from settings.widgets.settings_dialog_theme import (
    resolve_settings_chrome_from_widget,
    settings_chrome_for_preset,
    settings_dialog_stylesheet,
    settings_dialog_tooltip_label_stylesheet,
)
from settings.widgets.collapsible_theme_group import (
    CollapsibleThemeGroup,
    THEME_COLLAPSE_GROUP_KEYS,
    merge_theme_settings_groups_expanded,
)
from settings.widgets.macos_preferences import (
    MacPreferencePanel,
    MacToggleSwitch,
    build_column_major_toggle_grid,
    mac_preference_section,
)
from settings.widgets.multi_row_tab_widget import (
    FlowLayout,
    MultiRowTabWidget,
    TabButtonContainer,
)
from tooltip_popup_utils import install_settings_dialog_tooltip_filter

THEME_COLOR_SWATCH_TOOLTIPS = {
    "default_background_color_hex": (
        "Background for the main application window chrome (not\n"
        "thumbnails or dialogs)."
    ),
    "text_color_hex": (
        "Browse view and other main-window information (not\n"
        "dialogs or menus)."
    ),
    "dialog_background_hex": "Background for modal and modeless dialog windows.",
    "dialog_text_color_hex": (
        "Text color for dialog labels and general dialog\n"
        "content."
    ),
    "dialog_input_background_hex": (
        "Background for text fields, combo boxes, and other\n"
        "typed-in controls inside dialogs."
    ),
    "thumbnail_grid_background_color_hex": (
        "Background behind the thumbnail and list grids (margins\n"
        "and empty areas)."
    ),
    "thumbnail_text_color_hex": (
        "Text on thumbnail overlays, list rows, and in-grid\n"
        "labels."
    ),
    "status_bar_background_color_hex": (
        "Background fill for the main status bar, context menus,\n"
        "and menu-bar dropdowns."
    ),
    "status_bar_text_color_hex": (
        "Text color for status bar labels, context menus, and\n"
        "menu-bar dropdown items."
    ),
    "sidebar_header_bg_hex": (
        "Background of view title bars (e.g. Favorites, folder\n"
        "name headers)."
    ),
    "sidebar_background_color_hex": (
        "Background for left and right sidebar panes (file tree,\n"
        "preview, organize, information, jobs)."
    ),
    "sidebar_text_color_hex": (
        "Text color for sidebar content, titlebar labels, and\n"
        "tables; section headings are derived automatically."
    ),
    "default_border_color_hex": "Border color around sidebar sections and other chrome dividers.",
    "default_image_color_hex": "Border color around non-selected thumbnails.",
    "default_image_background_color_hex": "Background fill behind non-selected thumbnail images.",
    "current_image_border_color_hex": "Border color for the active image thumbnail.",
    "current_image_background_color_hex": "Background fill behind the active image thumbnail.",
    "multiselect_border_color_hex": "Border color when multiple thumbnails are selected.",
    "multiselect_background_color_hex": "Background fill behind thumbnails in a multi-selection.",
    "button_bg_default_hex": "Background color for standard buttons.",
    "button_border_default_hex": "Border color for standard buttons.",
    "button_bg_hover_hex": "Button background when hovered or keyboard-focused.",
    "button_border_hover_hex": "Button border when hovered or keyboard-focused.",
    "button_text_default_hex": "Text color for standard buttons.",
    "button_text_hover_hex": "Button text when hovered or keyboard-focused.",
}


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
            """ % (
                tc.CURRENT_IMAGE_BORDER_COLOR_HEX,
                resolve_settings_chrome_from_widget(self).control_bg_hex,
                resolve_settings_chrome_from_widget(self).text_hex,
            )
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

        chrome = resolve_settings_chrome_from_widget(self)
        painter.fillRect(self.rect(), QColor(chrome.bg_hex))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor(chrome.text_hex))
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
            label_bg = QColor(resolve_settings_chrome_from_widget(self).control_bg_hex)
            label_bg.setAlpha(220)
            painter.setBrush(QBrush(label_bg))
            painter.drawRect(st.label_rect_display)

            # label text
            painter.setPen(QColor(chrome.text_hex))
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




class SettingsDialog(QDialog):
    """Settings dialog for Image Browser configuration"""
    
    settings_changed = Signal(dict)  # Signal emitted when settings are changed
    cache_cleared = Signal()  # Signal emitted when cache is cleared
    
    # Constants
    DEFAULT_ROOT_DIRECTORIES = ['Users', 'Volumes', 'tmp']
    DEFAULT_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']
    DEFAULT_SLIDESHOW_RATE = 5000
    DEFAULT_TRANSITION_SPEED = 1300
    DEFAULT_OVERLAP_DELAY = -200
    DEFAULT_OVERLAP_PERCENT = 115
    DEFAULT_SLIDESHOW_DIRECTION = 'right'
    DEFAULT_SLIDESHOW_BACK_AND_FORTH = False
    DEFAULT_SIMILARITY_THRESHOLD = 45
    DEFAULT_HASH_SIZE = 16
    DEFAULT_SHIFT_CMD_DEPTH = 4
    DEFAULT_SEARCH_DEPTH = 4
    SMALL_CHECKBOX_STYLE = """
            QCheckBox::indicator {
                width: 11px;
                height: 11px;
            }
        """
    NOTE_TEXT_STYLE = f"color: {DIALOG_TEXT_COLOR_HEX}; font-size: 12pt; font-style: italic; margin-top: 10px;"
    
    # Theme tab: column widths so labels, swatches, and sliders align (sliders share one column).
    # Keep row total below scroll viewport width when a vertical scrollbar is present (gutter in inner min width).
    THEME_LABEL_COL_WIDTH = 185
    THEME_SWATCH_COL_WIDTH = 32
    THEME_SLIDER_COL_MIN_WIDTH = 155
    THEME_INNER_WIDTH_EXTRA = 48  # HBox spacing + vertical scrollbar / frame margin
    THEME_LIVE_PREVIEW_DEBOUNCE_MS = 120
    
    # Session-only: remember last tab id (not persisted across sessions)
    _last_tab_id = None
    # Session-only: remember LoRA tab model dropdown (not persisted across sessions)
    _last_lora_model_key = None
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Prowser Preferences")
        self.setModal(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(400, 300)
        self._sync_theme_context()
        
        # macOS key names
        self.is_mac = True
        
        # Store original settings for comparison
        self.original_settings = {}
        self.current_settings = {}
        # Thumbnail overlay settings (no UI; Cmd+I toggles in main window)
        self._overlay_filename_visible = False
        self._show_image_size = False
        self._overlay_settings_dialog_edited = False
        
        # Track Option key state for reset button behavior
        self.option_key_pressed = False
        self.shift_key_pressed = False
        
        # Timer to periodically check Option key state
        self.modifier_check_timer = QTimer()
        self.modifier_check_timer.timeout.connect(self._check_modifier_state)
        self.modifier_check_timer.setInterval(50)  # Check every 50ms

        self._user_theme_color_live_timer = QTimer(self)
        self._user_theme_color_live_timer.setSingleShot(True)
        self._user_theme_color_live_timer.setInterval(self.THEME_LIVE_PREVIEW_DEBOUNCE_MS)
        self._user_theme_color_live_timer.timeout.connect(self._debounced_apply_user_theme_preview_live)
        self._user_theme_color_picker_active_key = None
        self._theme_live_preview_changed_keys: set[str] = set()
        self._main_window_theme_touched = False

        self._browse_transparency_live_timer = QTimer(self)
        self._browse_transparency_live_timer.setSingleShot(True)
        self._browse_transparency_live_timer.setInterval(8)
        self._browse_transparency_live_timer.timeout.connect(self._debounced_browse_color_live_refresh)
        self._browse_color_picker_active = None
        self._browse_color_picker_tid = None

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(300)
        self._geometry_save_timer.timeout.connect(self._persist_settings_dialog_geometry)
        
        # Install event filter to catch modifier key changes
        self.installEventFilter(self)
        
        self.setup_ui()
        self.load_current_settings()
        # Ensure transparency color button is updated after settings are loaded
        if hasattr(self, 'transparency_color_button'):
            self._update_transparency_color_button()
        if hasattr(self, 'browse_border_color_button'):
            self._update_browse_border_color_button()
        self.apply_theme()
        install_settings_dialog_tooltip_filter(
            self,
            lambda: settings_dialog_tooltip_label_stylesheet(self._settings_chrome()),
        )

    def _settings_chrome_preset_id(self) -> str:
        """Theme preset driving settings-dialog chrome (not generic app dialog colors)."""
        if hasattr(self, "theme_preset_combo"):
            tid = self.theme_preset_combo.currentData()
            if tid in ("dark", "light", "user"):
                return tid
        tid = getattr(get_active_theme(), "theme_id", "dark")
        return tid if tid in ("dark", "light", "user") else "dark"

    def _settings_chrome(self):
        return settings_chrome_for_preset(self._settings_chrome_preset_id())

    def _combo_theme_preset_id(self) -> str:
        if not hasattr(self, "theme_preset_combo"):
            return "dark"
        tid = self.theme_preset_combo.currentData()
        return tid if tid in ("dark", "light", "user") else "dark"

    def _ui_theme_user_explicitly_changed(self, combo_tid: Optional[str] = None) -> bool:
        """True when the theme combo no longer matches the stored system appearance."""
        combo_tid = normalize_theme_id(combo_tid or self._combo_theme_preset_id())
        stored = normalize_theme_id(self.original_settings.get("ui_theme") or "dark")
        if stored != "system":
            return stored != combo_tid
        return resolve_theme_id_for_apply("system") != combo_tid

    def _get_ui_theme_for_save(self) -> str:
        """Persisted ui_theme: keep 'system' when the combo still reflects OS appearance."""
        combo_tid = self._combo_theme_preset_id()
        stored = normalize_theme_id(self.original_settings.get("ui_theme") or "dark")
        if stored == "system" and not self._ui_theme_user_explicitly_changed(combo_tid):
            return "system"
        return combo_tid

    def _ui_theme_values_equal(self, stored_ui_theme, combo_tid: str) -> bool:
        stored = normalize_theme_id(stored_ui_theme or "dark")
        combo = normalize_theme_id(combo_tid if combo_tid in ("dark", "light", "user") else "dark")
        if stored == combo:
            return True
        if stored == "system" and combo == resolve_theme_id_for_apply("system"):
            return True
        return False

    def _mark_main_window_theme_touched(self) -> None:
        self._main_window_theme_touched = True

    def _sync_theme_context(self):
        """Sync local theme constants and instance styles from active theme."""
        _refresh_theme_constants_from_thumbnail_constants()
        chrome = self._settings_chrome()
        self.NOTE_TEXT_STYLE = (
            f"color: {chrome.text_hex}; font-size: 12pt; "
            f"font-style: italic; margin-top: 10px;"
        )
        self._applied_theme_id = getattr(get_active_theme(), "theme_id", "dark")

    def _small_ellipsis_button_style(self) -> str:
        """Themed compact button style for path browse buttons."""
        return f"""
            QPushButton {{
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                color: {BUTTON_TEXT_DEFAULT_HEX};
                background: {BUTTON_BG_DEFAULT_HEX};
                border-radius: 4px;
                font-size: 12pt;
                padding: 0px 8px;
                min-width: 0px;
            }}
            QPushButton:hover {{
                background-color: {BUTTON_BG_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton:focus {{
                background-color: {BUTTON_BG_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
                outline: none;
            }}
            QPushButton:disabled {{
                color: {TEXT_DISABLED_HEX};
                border-color: {BORDER_DEFAULT_HEX};
                background: {TAB_BUTTON_HOVER_BG_HEX};
            }}
        """

    def _picker_list_button_style(self) -> str:
        """Themed row style for app picker buttons."""
        return f"""
            QPushButton {{
                text-align: left;
                padding: 8px;
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {BUTTON_TEXT_DEFAULT_HEX};
            }}
            QPushButton:hover {{
                background-color: {BUTTON_BG_HOVER_HEX};
                border-color: {BUTTON_BORDER_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
            }}
        """

    def _path_to_display(self, path: str) -> str:
        """Convert a full path to display format, replacing home directory with ~
        
        Args:
            path: Full path string (e.g., '/Users/bubba/foo')
            
        Returns:
            Display format path (e.g., '~/foo') or original path if not under home
        """
        from utils import normalize_path_for_display
        return normalize_path_for_display(path)

    def _display_to_path(self, display_path: str) -> str:
        """Convert display format path (with ~) to full path
        
        Args:
            display_path: Display format path (e.g., '~/foo' or '/Users/bubba/foo')
            
        Returns:
            Full path string (e.g., '/Users/bubba/foo')
        """
        from utils import display_to_path
        return display_to_path(display_path)

    def setup_ui(self):
        """Setup the settings dialog UI"""
        self._settings_dialog_initializing = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(0)
        
        # Create multi-row tab widget
        self.tab_widget = MultiRowTabWidget()
        self.tab_widget.setFocusPolicy(Qt.StrongFocus)

        layout.addWidget(self.tab_widget, 1)
        
        # Tab pages: no fixed min-height (content + scroll areas define size)
        self.app_settings_tab = QWidget()
        self.theme_settings_tab = QWidget()
        self.slideshow_settings_tab = QWidget()
        self.cache_management_tab = QWidget()
        self.directories_tab = QWidget()
        self.extensions_tab = QWidget()
        self.favorites_tab = QWidget()
        self.move_destinations_tab = QWidget()
        self.exclude_destinations_tab = QWidget()
        self.map_settings_tab = QWidget()
        self.similarity_settings_tab = QWidget()
        self.captioning_settings_tab = QWidget()
        self.lora_settings_tab = QWidget()
        self.faces_tab = QWidget()
        try:
            from bundle_capabilities import imagegen_ui_enabled, lmstudio_ui_enabled, faces_ui_enabled
        except ImportError:
            imagegen_ui_enabled = lambda: True  # type: ignore[misc, assignment]
            lmstudio_ui_enabled = lambda: True  # type: ignore[misc, assignment]
            faces_ui_enabled = lambda: True  # type: ignore[misc, assignment]
        self._show_faces_settings_tab = faces_ui_enabled()
        self._show_captioning_settings_tab = lmstudio_ui_enabled()
        self._show_lora_settings_tab = imagegen_ui_enabled()
        # Add tabs to widget in alphabetical order (column first)
        self.tab_widget.addTab(self.app_settings_tab, "General", "⚙️")
        self.tab_widget.addTab(self.favorites_tab, "Favorites", "❤️")
        self.tab_widget.addTab(self.directories_tab, "Directories", "📂")
        self.tab_widget.addTab(self.extensions_tab, "File Types", "🏞️")
        self.tab_widget.addTab(self.move_destinations_tab, "Destinations", "⤵️")
        self.tab_widget.addTab(self.exclude_destinations_tab, "Excludes", "🚫")
        if self._show_faces_settings_tab:
            self.tab_widget.addTab(self.faces_tab, "Face Recognition", "🧑🏼‍🦱")
        if self._show_captioning_settings_tab:
            self.tab_widget.addTab(self.captioning_settings_tab, "Captioning", "📝")
        if self._show_lora_settings_tab:
            self.tab_widget.addTab(self.lora_settings_tab, "LoRA", "🎭")
        self.tab_widget.addTab(self.map_settings_tab, "Maps and Editor", "📱")
        self.tab_widget.addTab(self.slideshow_settings_tab, "Slideshow", "💥")
        self.tab_widget.addTab(self.similarity_settings_tab, "Search Models", "🔍")
        self.tab_widget.addTab(self.theme_settings_tab, "Theme", "🎨")
        self.tab_widget.addTab(self.cache_management_tab, "Caches", "💾")
        
        # Connect tab change signal to resize dialog
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # Restore last tab if available (session-only)
        if SettingsDialog._last_tab_id is not None:
            self.show_tab_by_id(SettingsDialog._last_tab_id)
        
        # Setup each tab's content
        self.setup_app_settings_tab()
        self.setup_theme_settings_tab()
        self.setup_slideshow_settings_tab()
        self.setup_move_destinations_tab()
        self.setup_favorites_tab()
        self.setup_exclude_destinations_tab()
        # Faces tab: lazy-load on first visit (avoids slow face_recognition import at dialog open)
        self._faces_tab_setup_done = False
        self._auto_extract_faces = False
        self.setup_cache_management_tab()
        self.setup_root_directories_tab()
        self.setup_extensions_tab()
        self.setup_map_settings_tab()
        self.setup_similarity_settings_tab()
        if getattr(self, "_show_captioning_settings_tab", True):
            self.setup_captioning_settings_tab()
        if getattr(self, "_show_lora_settings_tab", True):
            self.setup_lora_settings_tab()
        self._apply_min_bundle_settings_visibility()
        
        self.setMinimumSize(720, 520)
        self._apply_saved_settings_dialog_geometry()
        
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet(f"color: {BORDER_DEFAULT_HEX}; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(8)
        
        # Buttons
        button_layout = QHBoxLayout()

        self._lora_add_button = QPushButton()
        self._lora_add_button.setObjectName("loraAddDownloadedButton")
        self._lora_add_button.setToolTip("Add downloaded LoRA (.safetensors)…")
        self._lora_add_button.setFixedSize(34, 34)
        self._lora_add_button.setStyleSheet(self._lora_add_button_style())
        self._lora_add_button.clicked.connect(self._open_add_downloaded_lora_dialog)
        self._lora_add_button.setVisible(False)
        button_layout.addWidget(self._lora_add_button)
        
        # Reset to defaults button (now resets only the current tab)
        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.setToolTip(
            "Reset settings on the current tab to your saved\n"
            "defaults.\n"
            f"Hold Option ({OPTION_SYMBOL}) for Save as Defaults;\n"
            f"Option+Shift ({SHIFT_SYMBOL}{OPTION_SYMBOL}) for System\n"
            "Defaults."
        )
        self.reset_button.clicked.connect(self.reset_tab_to_defaults)
        self.reset_button.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {BORDER_DEFAULT_HEX};
            }}
            QPushButton:focus {{
                border: 2px solid {BORDER_HOVER_HEX};
                outline: none;
            }}
            QPushButton:disabled {{
                color: {TEXT_DISABLED_HEX};
                border-color: {TAB_BUTTON_HOVER_BG_HEX};
            }}
        """)
        button_layout.addWidget(self.reset_button)
        
        # Small note about Option key
        self.option_note = QLabel(
            f"<b>{OPTION_SYMBOL}</b> Save defaults<br><b>{SHIFT_SYMBOL}{OPTION_SYMBOL}</b> System defaults"
        )
        option_note_font = QFont()
        option_note_font.setPointSize(10)
        self.option_note.setFont(option_note_font)
        self.option_note.setStyleSheet(f"color: {TEXT_DISABLED_HEX};")
        self.option_note.setToolTip(
            "Modifier keys for the reset button:\n"
            f"{OPTION_SYMBOL} — Save current tab as your defaults\n"
            f"{SHIFT_SYMBOL}{OPTION_SYMBOL} — Reset current tab to\n"
            "system defaults"
        )
        button_layout.addWidget(self.option_note)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Discard changes and close Settings")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        # Add spacing between buttons to prevent overlap
        button_layout.addSpacing(10)
        
        self.ok_button = QPushButton("OK")
        self.ok_button.setToolTip("Save changes and close Settings")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        
        # Set initial button visibility based on current tab
        initial_index = self.tab_widget.currentIndex()
        if initial_index >= 0:
            self.on_tab_changed(initial_index)
        if getattr(self, "_lora_add_button", None):
            lora_idx = self.tab_widget.indexOf(self.lora_settings_tab)
            self._lora_add_button.setVisible(
                getattr(self, "_show_lora_settings_tab", False)
                and initial_index == lora_idx
            )
        self._settings_tab_prev_index = self.tab_widget.currentIndex()
        self._settings_dialog_initializing = False

    def _apply_saved_settings_dialog_geometry(self):
        """Restore last saved dialog size from config (defaults merged in load_settings)."""
        w, h = 920, 680
        try:
            sz = get_config().load_settings().get("settings_dialog_size")
            if isinstance(sz, (list, tuple)) and len(sz) >= 2:
                w = max(400, min(3000, int(sz[0])))
                h = max(300, min(2000, int(sz[1])))
        except (TypeError, ValueError):
            pass
        self.resize(w, h)
        self._settings_dialog_geometry_at_load = [w, h]

    def _persist_settings_dialog_geometry(self):
        """Save current dialog size to config only when it changed."""
        try:
            size = [self.width(), self.height()]
            if getattr(self, "_settings_dialog_geometry_at_load", None) == size:
                return
            get_config().update_setting("settings_dialog_size", size)
            self._settings_dialog_geometry_at_load = list(size)
        except Exception:
            pass

    def _adjust_size_and_persist_geometry(self):
        """Fit dialog to current tab content, then save size (used after tab change / Faces lazy load)."""
        self.adjustSize()
        self._persist_settings_dialog_geometry()

    def _get_tab_name(self, tab_widget):
        """Get the name/key for a tab widget"""
        if tab_widget == self.theme_settings_tab:
            return 'theme_settings'
        elif tab_widget == self.app_settings_tab:
            return 'app_settings'
        elif tab_widget == self.slideshow_settings_tab:
            return 'slideshow_settings'
        elif tab_widget == self.move_destinations_tab:
            return 'move_destinations'
        elif tab_widget == self.exclude_destinations_tab:
            return 'exclude_destinations'
        elif tab_widget == self.favorites_tab:
            return 'favorites'
        elif tab_widget == self.directories_tab:
            return 'directories'
        elif tab_widget == self.extensions_tab:
            return 'extensions'
        elif tab_widget == self.map_settings_tab:
            return 'map_settings'
        elif tab_widget == self.similarity_settings_tab:
            return 'similarity_settings'
        elif tab_widget == self.captioning_settings_tab:
            return 'captioning_settings'
        elif tab_widget == self.lora_settings_tab:
            return 'lora_settings'
        elif tab_widget == self.cache_management_tab:
            return 'cache_management'
        elif tab_widget == self.faces_tab:
            return 'faces_tab'
        return None
    
    def _get_tab_display_name(self, tab_widget):
        """Get the display name for a tab widget"""
        # Find the tab in the tabs list
        for widget, label in self.tab_widget.tabs:
            if widget == tab_widget:
                return label
        return "this"

    def _tab_widgets_by_id(self) -> dict[str, QWidget]:
        """Map stable tab ids to tab page widgets (includes optional tabs)."""
        return {
            "app_settings": self.app_settings_tab,
            "favorites": self.favorites_tab,
            "directories": self.directories_tab,
            "extensions": self.extensions_tab,
            "move_destinations": self.move_destinations_tab,
            "exclude_destinations": self.exclude_destinations_tab,
            "faces_tab": self.faces_tab,
            "captioning_settings": self.captioning_settings_tab,
            "lora_settings": self.lora_settings_tab,
            "map_settings": self.map_settings_tab,
            "slideshow_settings": self.slideshow_settings_tab,
            "similarity_settings": self.similarity_settings_tab,
            "theme_settings": self.theme_settings_tab,
            "cache_management": self.cache_management_tab,
        }

    def tab_widget_for_id(self, tab_id: str):
        """Return the tab page widget for a stable tab id, or None if absent/hidden."""
        widget = self._tab_widgets_by_id().get(tab_id)
        if widget is None:
            return None
        if self.tab_widget.indexOf(widget) < 0:
            return None
        return widget

    def show_tab_by_id(self, tab_id: str) -> bool:
        """Select a settings tab by stable id; returns False if the tab is unavailable."""
        widget = self.tab_widget_for_id(tab_id)
        if widget is None:
            return False
        idx = self.tab_widget.indexOf(widget)
        if idx < 0:
            return False
        self.tab_widget.setCurrentIndex(idx)
        return True

    def select_lora_model_key(self, model_key: str) -> bool:
        """Select a base model on the LoRA settings tab (call after show_tab_by_id)."""
        mk = (model_key or "").strip()
        if not mk:
            return False
        self._ensure_lora_tab_ready()
        if not hasattr(self, "_lora_model_combo"):
            return False
        idx = self._lora_model_combo.findData(mk)
        if idx < 0:
            return False
        previous_model_key = getattr(self, "_lora_model_key", None)
        if previous_model_key and previous_model_key != mk:
            self._save_lora_widgets_to_draft(previous_model_key)
        self._lora_model_combo.blockSignals(True)
        self._lora_model_combo.setCurrentIndex(idx)
        self._lora_model_combo.blockSignals(False)
        self._show_lora_draft_for_model(mk)
        self._persist_session_lora_model_key()
        return True

    def _persist_session_lora_model_key(self) -> None:
        """Remember LoRA model dropdown for this app session (not saved to disk)."""
        if hasattr(self, "_lora_model_combo"):
            mk = self._current_lora_model_key()
            if mk:
                SettingsDialog._last_lora_model_key = mk

    def _resolve_lora_model_key(self, settings: dict) -> str:
        """Config model key, unless the user already picked one this session."""
        from imagegen_plugins.hf_model_ids import FLUX1_DEV
        from imagegen_plugins.lora_model_registry import legacy_host_id_to_model_key

        session_key = SettingsDialog._last_lora_model_key
        if session_key:
            if hasattr(self, "_lora_model_combo"):
                if self._lora_model_combo.findData(session_key) >= 0:
                    return str(session_key)
            else:
                return str(session_key)

        model_key = settings.get("imagegen_lora_model_key")
        if not model_key and settings.get("imagegen_lora_host_id"):
            model_key = legacy_host_id_to_model_key(
                str(settings.get("imagegen_lora_host_id"))
            )
        if model_key:
            return str(model_key)
        return str(getattr(self, "_lora_model_key", None) or FLUX1_DEV)
    
    def _get_tab_settings(self, tab_widget):
        """Get current settings for a specific tab"""
        if tab_widget == self.theme_settings_tab:
            tid = self.theme_preset_combo.currentData()
            if tid in ("dark", "light", "user") and hasattr(self, "use_diamonds_checkbox"):
                self._flush_browse_transparency_entry(tid)
            if tid == "user":
                utc = self._get_user_theme_colors_from_widgets()
            else:
                utc = merge_user_theme_colors(self.current_settings.get("user_theme_colors"))
            if tid == "dark":
                dtc = self._get_user_theme_colors_from_widgets()
            else:
                dtc = merge_dark_theme_colors(self.current_settings.get("dark_theme_colors"))
            if tid == "light":
                ltc = self._get_user_theme_colors_from_widgets()
            else:
                ltc = merge_light_theme_colors(self.current_settings.get("light_theme_colors"))
            bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
            return {
                'ui_theme': self._get_ui_theme_for_save(),
                'user_theme_colors': utc,
                'dark_theme_colors': dtc,
                'light_theme_colors': ltc,
                'browse_transparency_settings': copy.deepcopy(bts),
            }
        elif tab_widget == self.app_settings_tab:
            return {
                'filter_pattern': ImageBrowserConfig.normalize_filter_pattern(self.filter_pattern_input.text().strip()),
                'drag_drop_auto_date_change': self.drag_drop_auto_date_change_checkbox.isChecked(),
                'allow_thumbnail_locking': self.allow_thumbnail_locking_checkbox.isChecked(),
                'space_key_mode': self.space_mode_combo.currentData(),
                'browse_image_history_save_after_ms': (
                    self.browse_image_history_save_after_slider.value() * 500
                    if hasattr(self, 'browse_image_history_save_after_slider') else 3000
                ),
                'show_extensions': self.show_extensions_checkbox.isChecked(),
                'thumbnail_filename_visible': self._get_overlay_settings_for_save()[0],
                'show_image_size': self._get_overlay_settings_for_save()[1],
                'debug_mode': self.debug_checkbox.isChecked(),
                'confirm_delete': self.confirm_delete_checkbox.isChecked(),
                'wrap_around': self.wrap_around_checkbox.isChecked(),
                'raise_status_bar_on_cursor_near_bottom': (
                    self.raise_status_bar_on_cursor_near_bottom_checkbox.isChecked()
                ),
                'use_prompt_filter_exits': self.use_prompt_filter_exits_checkbox.isChecked(),
                'ignore_exif_rotation': not self.ignore_exif_rotation_checkbox.isChecked(),
                'imagegen_max_generation_dimension': (
                    self._imagegen_max_generation_dimension_px()
                    if hasattr(self, 'imagegen_max_generation_dimension_slider')
                    else 1024
                ),
                'imagegen_series_cooldown_seconds': (
                    int(self.imagegen_series_cooldown_slider.value())
                    if hasattr(self, 'imagegen_series_cooldown_slider')
                    else 60
                ),
                'imagegen_add_chat_prefix_postfix': (
                    self.imagegen_add_chat_prefix_postfix_checkbox.isChecked()
                    if hasattr(self, 'imagegen_add_chat_prefix_postfix_checkbox')
                    else True
                ),
            }
        elif tab_widget == self.slideshow_settings_tab:
            return {
                'slideshow_rate': self.slideshow_rate_spinbox.value(),
                'slideshow_transition_speed': self.transition_speed_spinbox.value(),
                'slideshow_max_rotation': self.rotation_angle_spinbox.value(),
                'slideshow_overlap_percent': self.overlap_percent_spinbox.value(),
                'slideshow_direction': self.direction_combo.currentText(),
                'slideshow_overlap_delay': self._calculate_overlap_delay(),
                'slideshow_back_and_forth': self.slideshow_back_and_forth_checkbox.isChecked(),
            }
        elif tab_widget == self.move_destinations_tab:
            return {
                'move_destinations': self.get_move_destinations(),
                'destination_menu_action': self._get_destination_menu_action(),
            }
        elif tab_widget == self.exclude_destinations_tab:
            return {
                'exclude_directories': self.get_exclude_destinations(),
            }
        elif tab_widget == self.favorites_tab:
            return {
                'favorite_directories': self.get_favorite_directories(),
            }
        elif tab_widget == self.directories_tab:
            return {
                'root_directories': self.get_root_directories(),
                'show_hidden_directories': self.show_hidden_directories_checkbox.isChecked() if hasattr(self, 'show_hidden_directories_checkbox') else False,
                'always_show_work': self.always_show_work_checkbox.isChecked() if hasattr(self, 'always_show_work_checkbox') else False,
                'follow_symlinks': self.follow_symlinks_checkbox.isChecked() if hasattr(self, 'follow_symlinks_checkbox') else False,
                'shift_cmd_depth': self.shift_cmd_depth_spinbox.value() if hasattr(self, 'shift_cmd_depth_spinbox') else self.DEFAULT_SHIFT_CMD_DEPTH,
                'search_depth': self.search_depth_spinbox.value() if hasattr(self, 'search_depth_spinbox') else self.DEFAULT_SEARCH_DEPTH,
                'ignore_directories': self.get_ignore_directories(),
                'image_creation_directory': self.get_image_creation_directory(),
                'temporary_files_directory': self.get_temporary_files_directory(),
            }
        elif tab_widget == self.extensions_tab:
            return {
                'image_extensions': self.get_image_extensions(),
            }
        elif tab_widget == self.map_settings_tab:
            return {
                'map_application': self._get_map_application(),
            }
        elif tab_widget == self.similarity_settings_tab:
            return {
                'similarity_metric': self._get_similarity_metric(),
            }
        elif tab_widget == self.captioning_settings_tab:
            return {
                'caption_lms_host': self.caption_lms_host_edit.text().strip(),
                'caption_system_prompt': self.caption_system_prompt_edit.toPlainText().strip(),
                'caption_user_prompt': self.caption_user_prompt_edit.toPlainText().strip(),
                'caption_max_words': self.caption_max_words_spinbox.value(),
                'caption_temperature': self.caption_temperature_spinbox.value(),
            }
        elif tab_widget == self.lora_settings_tab:
            self._ensure_lora_tab_ready()
            model_key = self._current_lora_model_key()
            self._save_lora_widgets_to_draft(model_key)
            slice_ = self._lora_draft_slice(model_key)
            return {
                'imagegen_lora_model_key': model_key,
                'imagegen_lora_enabled_ids': list(slice_["enabled_ids"]),
            }
        elif tab_widget == self.cache_management_tab:
            return {}  # No editable settings on cache tab
        elif tab_widget == self.faces_tab:
            return {}  # Faces persisted via known_faces.json
        return {}

    def _setting_values_equal(self, key: str, original_value, new_value) -> bool:
        """True when two setting values compare equal (same rules as accept())."""
        if key == 'filter_pattern':
            return (original_value or "") == (new_value or "")
        if key in (
            'imagegen_lora_enabled_ids',
            'imagegen_lora_model_key',
            'imagegen_lora_deleted_ids',
        ):
            return sorted(original_value or []) == sorted(new_value or [])
        if key == 'browse_transparency_settings':
            o = merge_browse_transparency_settings(
                original_value if isinstance(original_value, dict) else None
            )
            n = merge_browse_transparency_settings(new_value if isinstance(new_value, dict) else None)
            o_t = tuple(
                sorted(
                    (
                        t,
                        tuple(o[t]["transparency_color"]),
                        o[t]["use_diamonds"],
                        tuple(o[t]["browse_border_color"]),
                    )
                    for t in ("dark", "light", "user")
                )
            )
            n_t = tuple(
                sorted(
                    (
                        t,
                        tuple(n[t]["transparency_color"]),
                        n[t]["use_diamonds"],
                        tuple(n[t]["browse_border_color"]),
                    )
                    for t in ("dark", "light", "user")
                )
            )
            return o_t == n_t
        if key == 'favorite_directories':
            orig_favs = ((original_value or [])[:9] + [None] * 9)[:9]
            new_favs = ((new_value or [])[:9] + [None] * 9)[:9]
            return tuple(str(v) if v else '' for v in orig_favs) == tuple(
                str(v) if v else '' for v in new_favs
            )
        if key == 'user_theme_colors':
            o = merge_user_theme_colors(original_value if isinstance(original_value, dict) else None)
            n = merge_user_theme_colors(new_value if isinstance(new_value, dict) else None)
            return tuple(sorted(o.items())) == tuple(sorted(n.items()))
        if key == 'dark_theme_colors':
            o = merge_dark_theme_colors(original_value if isinstance(original_value, dict) else None)
            n = merge_dark_theme_colors(new_value if isinstance(new_value, dict) else None)
            return tuple(sorted(o.items())) == tuple(sorted(n.items()))
        if key == 'light_theme_colors':
            o = merge_light_theme_colors(original_value if isinstance(original_value, dict) else None)
            n = merge_light_theme_colors(new_value if isinstance(new_value, dict) else None)
            return tuple(sorted(o.items())) == tuple(sorted(n.items()))
        if key == 'ui_theme':
            return self._ui_theme_values_equal(original_value, new_value)
        return original_value == new_value

    def _tab_has_unsaved_changes(self, tab_widget) -> bool:
        """True when the current tab differs from values loaded at dialog open."""
        if tab_widget == self.faces_tab:
            return self._faces_subjects_changed()
        if tab_widget == self.cache_management_tab:
            return False
        current = self._get_tab_settings(tab_widget)
        for key, new_value in current.items():
            if not self._setting_values_equal(key, self.original_settings.get(key), new_value):
                return True
        return False
    
    def _apply_tab_settings(self, tab_widget, settings):
        """Apply settings to a specific tab"""
        if tab_widget == self.theme_settings_tab:
            # Restore only the palette currently selected in the combo (dark / light / user).
            # Do not apply saved ui_theme — that would switch the combo and confuse app vs editor state.
            tid_now = self.theme_preset_combo.currentData()
            if tid_now not in ("dark", "light", "user"):
                tid_now = "dark"
            if not hasattr(self, "current_settings"):
                return
            if tid_now == "user":
                if "user_theme_colors" in settings:
                    merged_u = merge_user_theme_colors(settings["user_theme_colors"])
                else:
                    merged_u = merge_user_theme_colors(None)
                self.current_settings["user_theme_colors"] = copy.deepcopy(merged_u)
            elif tid_now == "dark":
                if "dark_theme_colors" in settings:
                    merged_d = merge_dark_theme_colors(settings["dark_theme_colors"])
                else:
                    merged_d = merge_dark_theme_colors(None)
                self.current_settings["dark_theme_colors"] = copy.deepcopy(merged_d)
            else:
                if "light_theme_colors" in settings:
                    merged_l = merge_light_theme_colors(settings["light_theme_colors"])
                else:
                    merged_l = merge_light_theme_colors(None)
                self.current_settings["light_theme_colors"] = copy.deepcopy(merged_l)
            bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
            raw_saved_bts = settings.get("browse_transparency_settings")
            if isinstance(raw_saved_bts, dict) and raw_saved_bts:
                merged_saved = merge_browse_transparency_settings(raw_saved_bts)
                if tid_now in merged_saved:
                    bts[tid_now] = copy.deepcopy(merged_saved[tid_now])
                else:
                    bts[tid_now] = default_browse_transparency_entry()
            else:
                bts[tid_now] = default_browse_transparency_entry()
            self.current_settings["browse_transparency_settings"] = bts
            self._populate_theme_tab_swatches()
            self._load_browse_transparency_entry(tid_now)
            self._last_theme_preset_id = tid_now
            self._apply_theme_tab_from_dialog()
        elif tab_widget == self.app_settings_tab:
            if 'filter_pattern' in settings:
                self.filter_pattern_input.setText(settings['filter_pattern'] or "")
                self.update_match_count(settings['filter_pattern'] or "")
            if 'drag_drop_auto_date_change' in settings:
                self.drag_drop_auto_date_change_checkbox.setChecked(settings['drag_drop_auto_date_change'])
            if 'allow_thumbnail_locking' in settings:
                self.allow_thumbnail_locking_checkbox.setChecked(settings['allow_thumbnail_locking'])
            if 'allow_quick_mass_rename' in settings:
                self.allow_quick_mass_rename_checkbox.setChecked(settings['allow_quick_mass_rename'])
            if 'space_key_mode' in settings:
                for i in range(self.space_mode_combo.count()):
                    if self.space_mode_combo.itemData(i) == settings['space_key_mode']:
                        self.space_mode_combo.setCurrentIndex(i)
                        break
            if 'browse_image_history_save_after_ms' in settings and hasattr(self, 'browse_image_history_save_after_slider'):
                try:
                    _bh = max(0, min(5000, int(settings['browse_image_history_save_after_ms'])))
                except (TypeError, ValueError):
                    _bh = 3000
                self.browse_image_history_save_after_slider.blockSignals(True)
                self.browse_image_history_save_after_slider.setValue(max(0, min(10, round(_bh / 500))))
                self.browse_image_history_save_after_slider.blockSignals(False)
                self._update_browse_image_history_save_after_label()
            if 'show_extensions' in settings:
                self.show_extensions_checkbox.setChecked(settings['show_extensions'])
            if 'thumbnail_filename_visible' in settings or 'show_image_size' in settings:
                self._set_dialog_overlay_settings(
                    settings.get('thumbnail_filename_visible', self._overlay_filename_visible),
                    settings.get('show_image_size', self._show_image_size),
                    dialog_edited=True,
                )
            if 'debug_mode' in settings:
                self.debug_checkbox.setChecked(settings['debug_mode'])
            if 'confirm_delete' in settings:
                self.confirm_delete_checkbox.setChecked(settings['confirm_delete'])
            if 'wrap_around' in settings:
                self.wrap_around_checkbox.setChecked(settings['wrap_around'])
            if 'raise_status_bar_on_cursor_near_bottom' in settings:
                self.raise_status_bar_on_cursor_near_bottom_checkbox.setChecked(
                    settings['raise_status_bar_on_cursor_near_bottom']
                )
            if 'use_prompt_filter_exits' in settings:
                self.use_prompt_filter_exits_checkbox.setChecked(settings['use_prompt_filter_exits'])
            if 'ignore_exif_rotation' in settings:
                self.ignore_exif_rotation_checkbox.setChecked(not settings['ignore_exif_rotation'])
            self._load_imagegen_general_settings(settings)
        elif tab_widget == self.slideshow_settings_tab:
            if 'slideshow_rate' in settings:
                self.slideshow_rate_spinbox.setValue(settings['slideshow_rate'])
            if 'slideshow_transition_speed' in settings:
                self.transition_speed_spinbox.setValue(settings['slideshow_transition_speed'])
            if 'slideshow_max_rotation' in settings:
                self.rotation_angle_spinbox.setValue(settings['slideshow_max_rotation'])
            if 'slideshow_overlap_percent' in settings:
                self.overlap_percent_spinbox.setValue(settings['slideshow_overlap_percent'])
            if 'slideshow_direction' in settings:
                self.direction_combo.setCurrentText(settings['slideshow_direction'])
            if 'slideshow_back_and_forth' in settings:
                self.slideshow_back_and_forth_checkbox.setChecked(settings['slideshow_back_and_forth'])
        elif tab_widget == self.move_destinations_tab:
            if 'move_destinations' in settings and hasattr(self, 'move_destination_input_fields'):
                destinations = settings['move_destinations']
                for i, field in enumerate(self.move_destination_input_fields):
                    if i < len(destinations) and destinations[i]:
                        # Convert to display format
                        display_path = self._path_to_display(destinations[i])
                        field.setText(display_path)
                    else:
                        field.setText("")
            if 'destination_menu_action' in settings and hasattr(self, 'destination_menu_action_combo'):
                action = settings['destination_menu_action']
                if action not in ('none', 'copy', 'move'):
                    action = 'move'
                self.destination_menu_action_combo.setCurrentIndex({'none': 0, 'copy': 1, 'move': 2}[action])
        elif tab_widget == self.exclude_destinations_tab:
            if 'exclude_directories' in settings:
                exclude_dirs = settings['exclude_directories']
                if hasattr(self, 'exclude_destination_input_fields') and hasattr(self, 'exclude_destination_checkboxes'):
                    for i, field in enumerate(self.exclude_destination_input_fields):
                        if i < len(exclude_dirs):
                            if exclude_dirs[i].get('path'):
                                # Convert to display format
                                display_path = self._path_to_display(exclude_dirs[i]['path'])
                                field.setText(display_path)
                            else:
                                field.setText("")
                            if i < len(self.exclude_destination_checkboxes):
                                self.exclude_destination_checkboxes[i].setChecked(exclude_dirs[i].get('enabled', False))
        elif tab_widget == self.directories_tab:
            if 'root_directories' in settings and hasattr(self, 'directory_checkboxes'):
                root_dirs = settings['root_directories']
                # Convert from /Users format to Users format for checkboxes
                root_dirs_set = {d.lstrip('/') for d in root_dirs}
                for directory, checkbox in self.directory_checkboxes.items():
                    checkbox.setChecked(directory in root_dirs_set)
            if 'show_hidden_directories' in settings and hasattr(self, 'show_hidden_directories_checkbox'):
                self.show_hidden_directories_checkbox.setChecked(settings['show_hidden_directories'])
            if 'always_show_work' in settings and hasattr(self, 'always_show_work_checkbox'):
                self.always_show_work_checkbox.setChecked(settings['always_show_work'])
            if 'follow_symlinks' in settings and hasattr(self, 'follow_symlinks_checkbox'):
                self.follow_symlinks_checkbox.setChecked(settings['follow_symlinks'])
            if 'shift_cmd_depth' in settings and hasattr(self, 'shift_cmd_depth_spinbox'):
                self.shift_cmd_depth_spinbox.setValue(settings['shift_cmd_depth'])
            if 'search_depth' in settings and hasattr(self, 'search_depth_spinbox'):
                self.search_depth_spinbox.setValue(settings['search_depth'])
            if 'image_creation_directory' in settings:
                self._load_image_creation_directory(settings)
            if 'temporary_files_directory' in settings:
                self._load_temporary_files_directory(settings)
            if 'ignore_directories' in settings and hasattr(self, 'ignore_directory_input_fields'):
                ignore_dirs = settings['ignore_directories']
                if not isinstance(ignore_dirs, list):
                    ignore_dirs = []
                # Ensure we have at least 3 items (pad with empty dicts)
                while len(ignore_dirs) < 3:
                    ignore_dirs.append({'path': None, 'enabled': False})
                ignore_dirs = ignore_dirs[:3]
                for i, field in enumerate(self.ignore_directory_input_fields):
                    if i < len(ignore_dirs):
                        ignore_dir = ignore_dirs[i]
                        if isinstance(ignore_dir, dict):
                            path = ignore_dir.get('path')
                            enabled = ignore_dir.get('enabled', False)
                        else:
                            # Backward compatibility: if it's just a string, treat as path with enabled=True
                            path = ignore_dir if ignore_dir else None
                            enabled = True if path else False
                        
                        if path:
                            # Convert to display format
                            display_path = self._path_to_display(path)
                            field.setText(display_path)
                        else:
                            field.setText("")
                        
                        if hasattr(self, 'ignore_directory_checkboxes'):
                            self.ignore_directory_checkboxes[i].setChecked(enabled)
                    else:
                        field.setText("")
                        if hasattr(self, 'ignore_directory_checkboxes'):
                            self.ignore_directory_checkboxes[i].setChecked(False)
        elif tab_widget == self.extensions_tab:
            if 'image_extensions' in settings and hasattr(self, 'extension_checkboxes'):
                extensions_set = set(settings['image_extensions'])
                for extension, checkbox in self.extension_checkboxes.items():
                    checkbox.setChecked(extension in extensions_set)
        elif tab_widget == self.map_settings_tab:
            if 'map_application' in settings:
                map_app = settings['map_application']
                if map_app == 'apple_maps':
                    self.apple_maps_radio.setChecked(True)
                elif map_app == 'google_maps':
                    self.google_maps_radio.setChecked(True)
        elif tab_widget == self.similarity_settings_tab:
            if 'similarity_metric' in settings:
                metric = settings['similarity_metric']
                metric_map = {
                    'cosine': 'Cosine',
                    'euclidean': 'Euclidean',
                    'manhattan': 'Manhattan'
                }
                metric_display = metric_map.get(metric, 'Cosine')
                index = self.similarity_metric_combo.findText(metric_display)
                if index >= 0:
                    self.similarity_metric_combo.setCurrentIndex(index)
        elif tab_widget == self.captioning_settings_tab:
            if 'caption_lms_host' in settings:
                self.caption_lms_host_edit.setText(settings['caption_lms_host'])
            if 'caption_system_prompt' in settings:
                self.caption_system_prompt_edit.setPlainText(settings['caption_system_prompt'])
            if 'caption_user_prompt' in settings:
                self.caption_user_prompt_edit.setPlainText(settings['caption_user_prompt'])
            if 'caption_max_words' in settings:
                self.caption_max_words_spinbox.setValue(settings['caption_max_words'])
            if 'caption_temperature' in settings:
                self.caption_temperature_spinbox.setValue(settings['caption_temperature'])
        elif tab_widget == self.lora_settings_tab:
            self._load_lora_drafts_from_settings(settings)
            model_key = self._resolve_lora_model_key(settings)
            if hasattr(self, "_lora_model_combo"):
                idx = self._lora_model_combo.findData(model_key)
                if idx >= 0:
                    self._lora_model_combo.blockSignals(True)
                    self._lora_model_combo.setCurrentIndex(idx)
                    self._lora_model_combo.blockSignals(False)
            self._show_lora_draft_for_model(model_key)
        elif tab_widget == self.faces_tab:
            pass  # Faces persisted via known_faces.json; nothing to apply from settings dict
        elif tab_widget == self.favorites_tab:
            if 'favorite_directories' in settings and hasattr(self, 'favorite_destination_input_fields'):
                favorites = settings['favorite_directories']
                # Ensure we have exactly 9 items
                favorites = (favorites + [None] * 9)[:9]
                for i, field in enumerate(self.favorite_destination_input_fields):
                    if i < len(favorites) and favorites[i]:
                        # Convert to display format
                        display_path = self._path_to_display(favorites[i])
                        field.setText(display_path)
                        self.validate_favorite_destination_path(i, display_path)
                    else:
                        field.setText("")
                        if i < len(self.favorite_destination_validation_labels):
                            self.favorite_destination_validation_labels[i].setText("")
                            self.favorite_destination_validation_labels[i].setToolTip("")
    
    def save_as_defaults(self):
        """Save current tab settings as user defaults"""
        idx = self.tab_widget.currentIndex()
        tab_widget = self.tab_widget.widget(idx)
        tab_name = self._get_tab_name(tab_widget)
        
        if not tab_name:
            return
        
        # Get display name for confirmation dialog
        display_name = self._get_tab_display_name(tab_widget)
        
        # Show confirmation dialog
        reply = show_styled_question(
            self,
            "Save as Defaults",
            f"Do you want to save the current settings of the {display_name} tab to be your defaults?",
            default_no=False
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Get current settings for this tab
        tab_settings = self._get_tab_settings(tab_widget)
        
        # Save to config with a special key prefix
        config = get_config()
        settings = config.load_settings()
        defaults_key = f'_tab_defaults_{tab_name}'
        settings[defaults_key] = tab_settings
        config.save_settings(settings)
        
        # Show confirmation
        show_styled_information(
            self,
            "Defaults Saved",
            f"Current settings for this tab have been saved as defaults.\n"
            f"Clicking 'Reset to Defaults' will now use these saved values."
        )
    
    def reset_tab_to_defaults(self):
        """Reset only the settings/fields on the current tab to their default values."""
        idx = self.tab_widget.currentIndex()
        tab_widget = self.tab_widget.widget(idx)
        tab_name = self._get_tab_name(tab_widget)

        if self._tab_has_unsaved_changes(tab_widget):
            display_name = self._get_tab_display_name(tab_widget)
            reply = show_styled_question(
                self,
                "Reset to Defaults",
                f"Do you want to reset the {display_name} tab to defaults?\n\n"
                f"This will discard your unsaved changes on this tab.",
                default_no=True,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Check for saved defaults first
        config = get_config()
        settings = config.load_settings()
        defaults_key = f'_tab_defaults_{tab_name}'
        saved_defaults = settings.get(defaults_key)
        
        if saved_defaults:
            # Use saved defaults
            self._apply_tab_settings(tab_widget, saved_defaults)
            return

        if tab_widget == self.app_settings_tab:
            # Application tab: All checkboxes/selectors/spinboxes shown on this tab
            # Thumbnail Settings
            self.filter_pattern_input.setText("")
            self.update_match_count("")
            self.drag_drop_auto_date_change_checkbox.setChecked(False)
            self.allow_thumbnail_locking_checkbox.setChecked(False)
            self.allow_quick_mass_rename_checkbox.setChecked(False)
            # Browse Settings
            for i in range(self.space_mode_combo.count()):
                if self.space_mode_combo.itemData(i) == 'exit':
                    self.space_mode_combo.setCurrentIndex(i)
            if hasattr(self, 'browse_image_history_save_after_slider'):
                self.browse_image_history_save_after_slider.blockSignals(True)
                self.browse_image_history_save_after_slider.setValue(6)
                self.browse_image_history_save_after_slider.blockSignals(False)
                self._update_browse_image_history_save_after_label()
            self.show_extensions_checkbox.setChecked(False)
            self._set_dialog_overlay_settings(False, False, dialog_edited=True)
            # General Settings
            self.debug_checkbox.setChecked(False)
            self.confirm_delete_checkbox.setChecked(True)
            self.wrap_around_checkbox.setChecked(True)
            self.raise_status_bar_on_cursor_near_bottom_checkbox.setChecked(True)
            self.use_prompt_filter_exits_checkbox.setChecked(False)
            self.ignore_exif_rotation_checkbox.setChecked(True)
            if hasattr(self, 'imagegen_max_generation_dimension_slider'):
                from imagegen_plugins.image_gen_dim_limits import (
                    APP_MAX_GENERATION_DIMENSION_DEFAULT,
                    APP_MAX_GENERATION_DIMENSION_MIN,
                    APP_MAX_GENERATION_DIMENSION_STEP,
                    align_generation_dimension,
                )

                px = align_generation_dimension(APP_MAX_GENERATION_DIMENSION_DEFAULT)
                index = (px - APP_MAX_GENERATION_DIMENSION_MIN) // APP_MAX_GENERATION_DIMENSION_STEP
                self.imagegen_max_generation_dimension_slider.blockSignals(True)
                self.imagegen_max_generation_dimension_slider.setValue(index)
                self.imagegen_max_generation_dimension_slider.blockSignals(False)
                self._update_imagegen_max_generation_dimension_label()
            if hasattr(self, 'imagegen_series_cooldown_slider'):
                from imagegen_plugins.image_gen_dim_limits import (
                    APP_SERIES_COOLDOWN_SECONDS_DEFAULT,
                    app_series_cooldown_seconds,
                )

                sec = app_series_cooldown_seconds(
                    {"imagegen_series_cooldown_seconds": APP_SERIES_COOLDOWN_SECONDS_DEFAULT}
                )
                self.imagegen_series_cooldown_slider.blockSignals(True)
                self.imagegen_series_cooldown_slider.setValue(sec)
                self.imagegen_series_cooldown_slider.blockSignals(False)
                self._update_imagegen_series_cooldown_label()
            if hasattr(self, 'imagegen_add_chat_prefix_postfix_checkbox'):
                self.imagegen_add_chat_prefix_postfix_checkbox.setChecked(True)
        elif tab_widget == self.slideshow_settings_tab:
            self.slideshow_rate_spinbox.setValue(self.DEFAULT_SLIDESHOW_RATE)
            self.transition_speed_spinbox.setValue(self.DEFAULT_TRANSITION_SPEED)
            self.rotation_angle_spinbox.setValue(0)
            self.overlap_percent_spinbox.setValue(self.DEFAULT_OVERLAP_PERCENT)
            self.direction_combo.setCurrentText(self.DEFAULT_SLIDESHOW_DIRECTION)
        elif tab_widget == self.move_destinations_tab:
            if hasattr(self, 'move_destination_input_fields'):
                for field in self.move_destination_input_fields:
                    field.setText("")
                for label in self.move_destination_validation_labels:
                    label.setText("")
                    label.setToolTip("")
            if hasattr(self, 'destination_menu_action_combo'):
                self.destination_menu_action_combo.setCurrentIndex(2)  # Move
        elif tab_widget == self.exclude_destinations_tab:
            if hasattr(self, 'exclude_destination_input_fields'):
                for field in self.exclude_destination_input_fields:
                    field.setText("")
                for checkbox in self.exclude_destination_checkboxes:
                    checkbox.setChecked(False)
        elif tab_widget == self.directories_tab:
            if hasattr(self, 'directory_checkboxes'):
                for directory, checkbox in self.directory_checkboxes.items():
                    checkbox.setChecked(directory in self.DEFAULT_ROOT_DIRECTORIES)
            if hasattr(self, 'show_hidden_directories_checkbox'):
                self.show_hidden_directories_checkbox.setChecked(False)
            if hasattr(self, 'always_show_work_checkbox'):
                self.always_show_work_checkbox.setChecked(False)
            if hasattr(self, 'follow_symlinks_checkbox'):
                self.follow_symlinks_checkbox.setChecked(False)
            if hasattr(self, 'shift_cmd_depth_spinbox'):
                self.shift_cmd_depth_spinbox.setValue(self.DEFAULT_SHIFT_CMD_DEPTH)
            if hasattr(self, 'search_depth_spinbox'):
                self.search_depth_spinbox.setValue(self.DEFAULT_SEARCH_DEPTH)
            if hasattr(self, 'image_creation_directory_input_field'):
                self.image_creation_directory_input_field.setText("")
            if hasattr(self, 'image_creation_directory_checkbox'):
                self.image_creation_directory_checkbox.setChecked(False)
            if hasattr(self, 'temporary_files_directory_input_field'):
                self.temporary_files_directory_input_field.setText("")
            if hasattr(self, 'ignore_directory_input_fields'):
                for field in self.ignore_directory_input_fields:
                    field.setText("")
            if hasattr(self, 'ignore_directory_checkboxes'):
                for checkbox in self.ignore_directory_checkboxes:
                    checkbox.setChecked(False)
        elif tab_widget == self.extensions_tab:
            if hasattr(self, 'extension_checkboxes'):
                for extension, checkbox in self.extension_checkboxes.items():
                    checkbox.setChecked(extension in self.DEFAULT_IMAGE_EXTENSIONS)
        elif tab_widget == self.map_settings_tab:
            self.apple_maps_radio.setChecked(True)  # Default to Apple Maps
        elif tab_widget == self.similarity_settings_tab:
            # Reset similarity settings to defaults
            self.similarity_metric_combo.setCurrentIndex(0)  # Cosine
        elif tab_widget == self.captioning_settings_tab:
            from config import CAPTION_DEFAULTS
            self.caption_lms_host_edit.setText(CAPTION_DEFAULTS['caption_lms_host'])
            self.caption_system_prompt_edit.setPlainText(CAPTION_DEFAULTS['caption_system_prompt'])
            self.caption_user_prompt_edit.setPlainText(CAPTION_DEFAULTS['caption_user_prompt'])
            self.caption_max_words_spinbox.setValue(CAPTION_DEFAULTS['caption_max_words'])
            self.caption_temperature_spinbox.setValue(CAPTION_DEFAULTS['caption_temperature'])
        elif tab_widget == self.lora_settings_tab:
            from imagegen_plugins.lora_catalog_settings import (
                DEFAULT_ENABLED_LORA_IDS_BY_MODEL,
            )

            model_key = self._current_lora_model_key()
            if not hasattr(self, "_lora_draft_by_model"):
                self._lora_draft_by_model = {}
            self._lora_draft_by_model[model_key] = {
                "enabled_ids": list(
                    DEFAULT_ENABLED_LORA_IDS_BY_MODEL.get(model_key, ())
                ),
                "hidden_ids": [],
            }
            self._show_lora_draft_for_model(model_key)
        elif tab_widget == self.favorites_tab:
            if hasattr(self, 'favorite_destination_input_fields'):
                for field in self.favorite_destination_input_fields:
                    field.setText("")
                for label in self.favorite_destination_validation_labels:
                    label.setText("")
                    label.setToolTip("")
        elif tab_widget == self.cache_management_tab:
            # There are no editable fields on cache tab (just action buttons), so do nothing.
            pass
        elif tab_widget == self.theme_settings_tab:
            tid = self.theme_preset_combo.currentData()
            if tid in ("dark", "light", "user"):
                theme_updates: dict = {}
                if tid == "user":
                    defaults = merge_user_theme_colors(None)
                    self.current_settings["user_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["user_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["user_theme_colors"] = copy.deepcopy(defaults)
                elif tid == "dark":
                    defaults = merge_dark_theme_colors(None)
                    self.current_settings["dark_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["dark_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["dark_theme_colors"] = copy.deepcopy(defaults)
                elif tid == "light":
                    defaults = merge_light_theme_colors(None)
                    self.current_settings["light_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["light_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["light_theme_colors"] = copy.deepcopy(defaults)
                bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
                bts[tid] = default_browse_transparency_entry()
                bts_copy = copy.deepcopy(bts)
                self.current_settings["browse_transparency_settings"] = bts_copy
                self.original_settings["browse_transparency_settings"] = copy.deepcopy(bts_copy)
                theme_updates["browse_transparency_settings"] = bts_copy
                if theme_updates:
                    get_config().update_settings(theme_updates)
                self._populate_theme_tab_swatches()
                self._load_browse_transparency_entry(tid)
                self._last_theme_preset_id = tid
                self._apply_theme_tab_from_dialog()

    def load_system_defaults(self):
        """Load system defaults (hardcoded) for the current tab, ignoring saved defaults"""
        idx = self.tab_widget.currentIndex()
        tab_widget = self.tab_widget.widget(idx)
        tab_name = self._get_tab_name(tab_widget)
        
        if not tab_name:
            return
        
        # Get display name for confirmation dialog
        display_name = self._get_tab_display_name(tab_widget)
        
        # Show confirmation dialog
        reply = show_styled_question(
            self,
            "Load System Defaults",
            f"Do you want to load system defaults for the {display_name} tab?\n\n"
            f"This will reset all settings on this tab to their original system defaults, "
            f"ignoring any saved defaults.",
            default_no=False
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        if tab_widget == self.app_settings_tab:
            # Application tab: All checkboxes/selectors/spinboxes shown on this tab
            # Thumbnail Settings
            self.filter_pattern_input.setText("")
            self.update_match_count("")
            self.drag_drop_auto_date_change_checkbox.setChecked(False)
            self.allow_thumbnail_locking_checkbox.setChecked(False)
            self.allow_quick_mass_rename_checkbox.setChecked(False)
            # Browse Settings
            for i in range(self.space_mode_combo.count()):
                if self.space_mode_combo.itemData(i) == 'exit':
                    self.space_mode_combo.setCurrentIndex(i)
            if hasattr(self, 'browse_image_history_save_after_slider'):
                self.browse_image_history_save_after_slider.blockSignals(True)
                self.browse_image_history_save_after_slider.setValue(6)
                self.browse_image_history_save_after_slider.blockSignals(False)
                self._update_browse_image_history_save_after_label()
            self.show_extensions_checkbox.setChecked(False)
            self._set_dialog_overlay_settings(False, False, dialog_edited=True)
            # General Settings
            self.debug_checkbox.setChecked(False)
            self.confirm_delete_checkbox.setChecked(True)
            self.wrap_around_checkbox.setChecked(True)
            self.raise_status_bar_on_cursor_near_bottom_checkbox.setChecked(True)
            self.use_prompt_filter_exits_checkbox.setChecked(False)
            self.ignore_exif_rotation_checkbox.setChecked(True)
            if hasattr(self, 'imagegen_max_generation_dimension_slider'):
                from imagegen_plugins.image_gen_dim_limits import (
                    APP_MAX_GENERATION_DIMENSION_DEFAULT,
                    APP_MAX_GENERATION_DIMENSION_MIN,
                    APP_MAX_GENERATION_DIMENSION_STEP,
                    align_generation_dimension,
                )

                px = align_generation_dimension(APP_MAX_GENERATION_DIMENSION_DEFAULT)
                index = (px - APP_MAX_GENERATION_DIMENSION_MIN) // APP_MAX_GENERATION_DIMENSION_STEP
                self.imagegen_max_generation_dimension_slider.blockSignals(True)
                self.imagegen_max_generation_dimension_slider.setValue(index)
                self.imagegen_max_generation_dimension_slider.blockSignals(False)
                self._update_imagegen_max_generation_dimension_label()
            if hasattr(self, 'imagegen_series_cooldown_slider'):
                from imagegen_plugins.image_gen_dim_limits import (
                    APP_SERIES_COOLDOWN_SECONDS_DEFAULT,
                    app_series_cooldown_seconds,
                )

                sec = app_series_cooldown_seconds(
                    {"imagegen_series_cooldown_seconds": APP_SERIES_COOLDOWN_SECONDS_DEFAULT}
                )
                self.imagegen_series_cooldown_slider.blockSignals(True)
                self.imagegen_series_cooldown_slider.setValue(sec)
                self.imagegen_series_cooldown_slider.blockSignals(False)
                self._update_imagegen_series_cooldown_label()
            if hasattr(self, 'imagegen_add_chat_prefix_postfix_checkbox'):
                self.imagegen_add_chat_prefix_postfix_checkbox.setChecked(True)
        elif tab_widget == self.slideshow_settings_tab:
            self.slideshow_rate_spinbox.setValue(self.DEFAULT_SLIDESHOW_RATE)
            self.transition_speed_spinbox.setValue(self.DEFAULT_TRANSITION_SPEED)
            self.rotation_angle_spinbox.setValue(0)
            self.overlap_percent_spinbox.setValue(self.DEFAULT_OVERLAP_PERCENT)
            self.direction_combo.setCurrentText(self.DEFAULT_SLIDESHOW_DIRECTION)
        elif tab_widget == self.move_destinations_tab:
            if hasattr(self, 'move_destination_input_fields'):
                for field in self.move_destination_input_fields:
                    field.setText("")
                for label in self.move_destination_validation_labels:
                    label.setText("")
                    label.setToolTip("")
            if hasattr(self, 'destination_menu_action_combo'):
                self.destination_menu_action_combo.setCurrentIndex(2)  # Move
        elif tab_widget == self.exclude_destinations_tab:
            if hasattr(self, 'exclude_destination_input_fields'):
                for field in self.exclude_destination_input_fields:
                    field.setText("")
                for checkbox in self.exclude_destination_checkboxes:
                    checkbox.setChecked(False)
        elif tab_widget == self.directories_tab:
            if hasattr(self, 'directory_checkboxes'):
                for directory, checkbox in self.directory_checkboxes.items():
                    checkbox.setChecked(directory in self.DEFAULT_ROOT_DIRECTORIES)
            if hasattr(self, 'show_hidden_directories_checkbox'):
                self.show_hidden_directories_checkbox.setChecked(False)
            if hasattr(self, 'always_show_work_checkbox'):
                self.always_show_work_checkbox.setChecked(False)
            if hasattr(self, 'follow_symlinks_checkbox'):
                self.follow_symlinks_checkbox.setChecked(False)
            if hasattr(self, 'shift_cmd_depth_spinbox'):
                self.shift_cmd_depth_spinbox.setValue(self.DEFAULT_SHIFT_CMD_DEPTH)
            if hasattr(self, 'search_depth_spinbox'):
                self.search_depth_spinbox.setValue(self.DEFAULT_SEARCH_DEPTH)
            if hasattr(self, 'image_creation_directory_input_field'):
                self.image_creation_directory_input_field.setText("")
            if hasattr(self, 'image_creation_directory_checkbox'):
                self.image_creation_directory_checkbox.setChecked(False)
            if hasattr(self, 'temporary_files_directory_input_field'):
                self.temporary_files_directory_input_field.setText("")
            if hasattr(self, 'ignore_directory_input_fields'):
                for field in self.ignore_directory_input_fields:
                    field.setText("")
            if hasattr(self, 'ignore_directory_checkboxes'):
                for checkbox in self.ignore_directory_checkboxes:
                    checkbox.setChecked(False)
        elif tab_widget == self.extensions_tab:
            if hasattr(self, 'extension_checkboxes'):
                for extension, checkbox in self.extension_checkboxes.items():
                    checkbox.setChecked(extension in self.DEFAULT_IMAGE_EXTENSIONS)
        elif tab_widget == self.map_settings_tab:
            self.apple_maps_radio.setChecked(True)  # Default to Apple Maps
        elif tab_widget == self.similarity_settings_tab:
            # Reset similarity settings to defaults
            self.similarity_metric_combo.setCurrentIndex(0)  # Cosine
        elif tab_widget == self.captioning_settings_tab:
            from config import CAPTION_DEFAULTS
            self.caption_lms_host_edit.setText(CAPTION_DEFAULTS['caption_lms_host'])
            self.caption_system_prompt_edit.setPlainText(CAPTION_DEFAULTS['caption_system_prompt'])
            self.caption_user_prompt_edit.setPlainText(CAPTION_DEFAULTS['caption_user_prompt'])
            self.caption_max_words_spinbox.setValue(CAPTION_DEFAULTS['caption_max_words'])
            self.caption_temperature_spinbox.setValue(CAPTION_DEFAULTS['caption_temperature'])
        elif tab_widget == self.lora_settings_tab:
            from imagegen_plugins.lora_catalog_settings import (
                DEFAULT_ENABLED_LORA_IDS_BY_MODEL,
            )

            model_key = self._current_lora_model_key()
            if not hasattr(self, "_lora_draft_by_model"):
                self._lora_draft_by_model = {}
            self._lora_draft_by_model[model_key] = {
                "enabled_ids": list(
                    DEFAULT_ENABLED_LORA_IDS_BY_MODEL.get(model_key, ())
                ),
                "hidden_ids": [],
            }
            self._show_lora_draft_for_model(model_key)
        elif tab_widget == self.favorites_tab:
            if hasattr(self, 'favorite_destination_input_fields'):
                for field in self.favorite_destination_input_fields:
                    field.setText("")
                for label in self.favorite_destination_validation_labels:
                    label.setText("")
                    label.setToolTip("")
        elif tab_widget == self.theme_settings_tab:
            tid = self.theme_preset_combo.currentData()
            if tid in ("dark", "light", "user"):
                theme_updates: dict = {}
                if tid == "user":
                    defaults = merge_user_theme_colors(None)
                    self.current_settings["user_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["user_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["user_theme_colors"] = copy.deepcopy(defaults)
                elif tid == "dark":
                    defaults = merge_dark_theme_colors(None)
                    self.current_settings["dark_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["dark_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["dark_theme_colors"] = copy.deepcopy(defaults)
                elif tid == "light":
                    defaults = merge_light_theme_colors(None)
                    self.current_settings["light_theme_colors"] = copy.deepcopy(defaults)
                    self.original_settings["light_theme_colors"] = copy.deepcopy(defaults)
                    theme_updates["light_theme_colors"] = copy.deepcopy(defaults)
                bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
                bts[tid] = default_browse_transparency_entry()
                bts_copy = copy.deepcopy(bts)
                self.current_settings["browse_transparency_settings"] = bts_copy
                self.original_settings["browse_transparency_settings"] = copy.deepcopy(bts_copy)
                theme_updates["browse_transparency_settings"] = bts_copy
                if theme_updates:
                    get_config().update_settings(theme_updates)
                self._populate_theme_tab_swatches()
                self._load_browse_transparency_entry(tid)
                self._last_theme_preset_id = tid
                self._apply_theme_tab_from_dialog()
        elif tab_widget == self.cache_management_tab:
            # There are no editable fields on cache tab (just action buttons), so do nothing.
            pass
        elif tab_widget == self.faces_tab:
            # Reload from file to restore last saved state
            if hasattr(self, '_faces_subjects') and hasattr(self, '_faces_scroll_content'):
                self._faces_subjects[:] = []
                from faces.known_faces_manager import load as load_faces
                self._faces_subjects.extend(load_faces())
                self._faces_subjects_at_load = copy.deepcopy(self._faces_subjects)
                self._faces_rebuild_cards()

    def setup_app_settings_tab(self):
        """Setup the application settings tab (macOS Preferences pane style)."""
        layout = QVBoxLayout(self.app_settings_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(20, 12, 20, 20)
        inner_layout.setSpacing(18)

        # ----- Thumbnails -----
        thumb_title, thumb_panel = mac_preference_section("Thumbnails", inner)

        filter_container = QWidget()
        filter_layout = QVBoxLayout(filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)

        self.filter_pattern_layout = QHBoxLayout()
        self.filter_pattern_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_pattern_layout.setSpacing(8)
        self.filter_pattern_input = QLineEdit()
        self.filter_pattern_input.setToolTip(
            "Filter images by filename using glob pattern\n"
            "(e.g., '*.jpg', 'IMG_*', etc.)"
        )
        self.filter_pattern_input.setPlaceholderText("e.g., *.jpg, IMG_*")
        self.filter_pattern_input.setMinimumWidth(140)
        self.filter_pattern_input.setMaximumWidth(180)
        self.filter_pattern_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.filter_pattern_input.setStyleSheet("QLineEdit { padding: 4px; }")
        self.filter_pattern_input.textChanged.connect(self.validate_filter_pattern)

        self.filter_validation_label = QLabel("")
        self.filter_validation_label.setObjectName("macPreferenceRowSubtitle")

        self.apply_filter_button = QPushButton("Apply")
        self.apply_filter_button.setToolTip("Apply filter immediately")
        self.apply_filter_button.clicked.connect(self.apply_filter_now)
        self.apply_filter_button.setFixedHeight(28)
        self.apply_filter_button.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 10px;
                font-size: 12px;
                border: 1px solid {BORDER_DEFAULT_HEX};
            }}
            QPushButton:focus {{
                border: 2px solid {BORDER_HOVER_HEX};
                outline: none;
            }}
            QPushButton:disabled {{
                color: {TEXT_DISABLED_HEX};
                border-color: {TAB_BUTTON_HOVER_BG_HEX};
            }}
        """)

        self.filter_pattern_layout.addWidget(self.filter_pattern_input)
        self.filter_pattern_layout.addWidget(self.filter_validation_label)
        self.filter_pattern_layout.addWidget(self.apply_filter_button)

        self.match_count_label = QLabel("")
        self.match_count_label.setObjectName("macPreferenceRowSubtitle")

        filter_layout.addLayout(self.filter_pattern_layout)
        filter_layout.addWidget(self.match_count_label)

        thumb_panel.add_form_row(
            "Filter Pattern",
            filter_container,
            tooltip="Filter images by filename using glob patterns.",
        )

        self.show_extensions_checkbox = thumb_panel.add_toggle(
            f"Always show file extensions (cycle with {CMD_SYMBOL}-I)",
            tooltip=(
                "Always show file extensions on file names.\n"
                "If unchecked, file extensions are only\n"
                "shown when multiple files have the same base name."
            ),
            subtitle=f"Use {CMD_SYMBOL}-I to cycle display of names, etc.",
        )

        self.drag_drop_auto_date_change_checkbox = thumb_panel.add_toggle(
            "Drag/drop changes dates when sorted by date",
            tooltip=(
                "When sorted by date, moving icons in thumbnail view\n"
                "automatically adjusts file dates to preserve the new\n"
                "sort order."
            ),
            subtitle="Changes file date when dragging to maintain sort order by date.",
        )

        self.allow_thumbnail_locking_checkbox = thumb_panel.add_toggle(
            f"Allow thumbnail locking ({SHIFT_SYMBOL}-{CMD_SYMBOL}-L)",
            tooltip=(
                "Allow marking thumbnails as locked to keep them in\n"
                "place while organizing images in a directory."
            ),
            subtitle="Experimental. Locks thumbnail positions in order.",
        )

        self.allow_quick_mass_rename_checkbox = thumb_panel.add_toggle(
            f"Allow Quick Mass Rename ({SHIFT_SYMBOL}-{CMD_SYMBOL}-M)",
            tooltip=(
                "Allow Quick rename. Warning: This can rename large\n"
                "numbers of files without confirmation."
            ),
            subtitle="Warning: This can rename large numbers of files without confirmation.",
        )

        inner_layout.addWidget(thumb_title)
        inner_layout.addWidget(thumb_panel)

        # ----- Browse -----
        browse_title, browse_panel = mac_preference_section("Browse", inner)

        self.space_mode_combo = QComboBox()
        self.space_mode_combo.addItem("Exit to thumbnails", userData="exit")
        self.space_mode_combo.addItem("Show next image", userData="advance")
        self.space_mode_combo.setToolTip("Default behavior for space key in browse mode")
        self.space_mode_combo.setFixedHeight(28)
        self.space_mode_combo.setMinimumWidth(160)
        self.space_mode_combo.setStyleSheet("QComboBox { font-size: 12px; padding: 4px; }")
        browse_panel.add_form_row(
            "Space Key",
            self.space_mode_combo,
            tooltip="Default behavior for the space key in browse mode.",
            subtitle=f"Use {SHIFT_SYMBOL}-Space in browse to toggle show next image/exit browse.",
        )

        save_history_control = QWidget()
        save_history_layout = QVBoxLayout(save_history_control)
        save_history_layout.setContentsMargins(0, 0, 0, 0)
        save_history_layout.setSpacing(4)
        save_history_slider_row = QWidget()
        save_history_slider_layout = QHBoxLayout(save_history_slider_row)
        save_history_slider_layout.setContentsMargins(0, 0, 0, 0)
        save_history_slider_layout.setSpacing(8)
        self.browse_image_history_save_after_slider = QSlider(Qt.Horizontal)
        self.browse_image_history_save_after_slider.setMinimum(0)
        self.browse_image_history_save_after_slider.setMaximum(10)
        self.browse_image_history_save_after_slider.setSingleStep(1)
        self.browse_image_history_save_after_slider.setPageStep(2)
        self.browse_image_history_save_after_slider.setTickInterval(2)
        self.browse_image_history_save_after_slider.setTickPosition(QSlider.TicksBelow)
        self.browse_image_history_save_after_slider.setMinimumWidth(160)
        self.browse_image_history_save_after_slider.setToolTip(
            "Time in seconds before the currently browsed image\n"
            "is added to Image History.\n\n"
            "This can be used to group together images that are not\n"
            "in the current thumbnail list by viewing individual\n"
            "images and then pressing F3 to show them in the same\n"
            "thumbnail view."
        )
        self.browse_image_history_save_after_slider.valueChanged.connect(
            self._on_browse_image_history_save_after_slider_changed
        )
        self.browse_image_history_save_after_value_label = QLabel()
        self.browse_image_history_save_after_value_label.setMinimumWidth(72)
        self.browse_image_history_save_after_value_label.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )
        save_history_slider_layout.addWidget(self.browse_image_history_save_after_slider, 1)
        save_history_slider_layout.addWidget(self.browse_image_history_save_after_value_label, 0)
        save_history_layout.addWidget(save_history_slider_row)
        browse_panel.add_form_row(
            "Remember image after",
            save_history_control,
            tooltip=(
                "After this time, the current image is added to Image\n"
                "History that you can see by pressing F3."
            ),
            subtitle="For Image History (F3)",
        )

        inner_layout.addWidget(browse_title)
        inner_layout.addWidget(browse_panel)

        # ----- General -----
        general_title, general_panel = mac_preference_section("General", inner)

        self.confirm_delete_checkbox = general_panel.add_toggle(
            f"Delete confirmation on {CMD_SYMBOL}-Delete",
            tooltip="Show confirmation dialog when deleting files.",
            subtitle=f"Show confirmation dialog when deleting files with {CMD_SYMBOL}-Delete.",
        )

        self.wrap_around_checkbox = general_panel.add_toggle(
            "Wrap around",
            tooltip=(
                "Allow navigation to wrap from end to beginning and\n"
                "vice versa."
            ),
            subtitle="Allow cursor navigation to wrap from end to beginning.",
        )

        self.raise_status_bar_on_cursor_near_bottom_checkbox = general_panel.add_toggle(
            "Raise status bar when cursor nears bottom",
            tooltip=(
                "When the status bar is hidden, move the cursor near the\n"
                "bottom edge of the window to temporarily show it."
            ),
            subtitle=(
                "When off, a hidden status bar stays hidden near the bottom edge."
            ),
        )

        self.ignore_exif_rotation_checkbox = general_panel.add_toggle(
            "Use EXIF rotation",
            tooltip=(
                "Apply automatic EXIF rotation correction.\n"
                "When unchecked, images are displayed without rotation\n"
                "correction.\n"
                "Manual rotation (Shift+arrow keys) still works in\n"
                "fullscreen."
            ),
            subtitle="Rotate images based on EXIF data if available.",
        )

        self.debug_checkbox = general_panel.add_toggle(
            f"Debug mode ({SHIFT_SYMBOL}-{CMD_SYMBOL}-D)",
            tooltip="Show key popup overlay for debugging keyboard events.",
            subtitle=f"Enter debug mode. Meaning varies. Use {CTRL_SYMBOL}-L to view log.",
        )

        self.use_prompt_filter_exits_checkbox = general_panel.add_toggle(
            "Use prompt filter exits",
            tooltip=(
                "When enabled, run external prompt filter scripts\n"
                "configured via PROWSER_TEXT_AI_EXIT (LMStudio / caption\n"
                "prompts) and PROWSER_IMAGE_AI_EXIT (image generation\n"
                "prompts) before model calls."
            ),
            subtitle="Use Exit code to modify prompt data before model calls.",
        )

        inner_layout.addWidget(general_title)
        inner_layout.addWidget(general_panel)

        # ----- Image generation -----
        from imagegen_plugins.image_gen_dim_limits import (
            APP_MAX_GENERATION_DIMENSION_CEILING,
            APP_MAX_GENERATION_DIMENSION_DEFAULT,
            APP_MAX_GENERATION_DIMENSION_MIN,
            APP_MAX_GENERATION_DIMENSION_STEP,
            APP_SERIES_COOLDOWN_SECONDS_DEFAULT,
            APP_SERIES_COOLDOWN_SECONDS_MAX,
            align_generation_dimension,
            app_series_cooldown_seconds,
        )

        imagegen_title, imagegen_panel = mac_preference_section("Image Generation", inner)

        _dim_step = APP_MAX_GENERATION_DIMENSION_STEP
        _dim_slider_max = (
            APP_MAX_GENERATION_DIMENSION_CEILING - APP_MAX_GENERATION_DIMENSION_MIN
        ) // _dim_step

        max_dim_control = QWidget()
        max_dim_row_layout = QHBoxLayout(max_dim_control)
        max_dim_row_layout.setContentsMargins(0, 0, 0, 0)
        max_dim_row_layout.setSpacing(8)
        self.imagegen_max_generation_dimension_slider = QSlider(Qt.Horizontal)
        self.imagegen_max_generation_dimension_slider.setMinimum(0)
        self.imagegen_max_generation_dimension_slider.setMaximum(_dim_slider_max)
        self.imagegen_max_generation_dimension_slider.setSingleStep(1)
        self.imagegen_max_generation_dimension_slider.setPageStep(4)
        self.imagegen_max_generation_dimension_slider.setMinimumWidth(160)
        self.imagegen_max_generation_dimension_slider.setToolTip(
            "Maximum edge length (width or height) for image\n"
            "generation.\n"
            "Individual models may impose lower limits."
        )
        self.imagegen_max_generation_dimension_slider.valueChanged.connect(
            self._on_imagegen_max_generation_dimension_slider_changed
        )
        self.imagegen_max_generation_dimension_value_label = QLabel()
        self.imagegen_max_generation_dimension_value_label.setMinimumWidth(72)
        self.imagegen_max_generation_dimension_value_label.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )
        max_dim_row_layout.addWidget(self.imagegen_max_generation_dimension_slider, 1)
        max_dim_row_layout.addWidget(self.imagegen_max_generation_dimension_value_label, 0)
        imagegen_panel.add_form_row(
            "Max generation dimension",
            max_dim_control,
            tooltip="Maximum edge length for image generation.",
            subtitle="Models may impose lower limits.",
        )

        cooldown_control = QWidget()
        cooldown_control_layout = QVBoxLayout(cooldown_control)
        cooldown_control_layout.setContentsMargins(0, 0, 0, 0)
        cooldown_control_layout.setSpacing(4)
        cooldown_row = QWidget()
        cooldown_row_layout = QHBoxLayout(cooldown_row)
        cooldown_row_layout.setContentsMargins(0, 0, 0, 0)
        cooldown_row_layout.setSpacing(8)
        self.imagegen_series_cooldown_slider = QSlider(Qt.Horizontal)
        self.imagegen_series_cooldown_slider.setMinimum(0)
        self.imagegen_series_cooldown_slider.setMaximum(APP_SERIES_COOLDOWN_SECONDS_MAX)
        self.imagegen_series_cooldown_slider.setSingleStep(1)
        self.imagegen_series_cooldown_slider.setPageStep(10)
        self.imagegen_series_cooldown_slider.setMinimumWidth(160)
        self.imagegen_series_cooldown_slider.setToolTip(
            "Number of seconds between each generation in a series."
        )
        self.imagegen_series_cooldown_slider.valueChanged.connect(
            self._on_imagegen_series_cooldown_slider_changed
        )
        self.imagegen_series_cooldown_value_label = QLabel()
        self.imagegen_series_cooldown_value_label.setMinimumWidth(72)
        self.imagegen_series_cooldown_value_label.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )
        cooldown_row_layout.addWidget(self.imagegen_series_cooldown_slider, 1)
        cooldown_row_layout.addWidget(self.imagegen_series_cooldown_value_label, 0)
        cooldown_control_layout.addWidget(cooldown_row)
        imagegen_panel.add_form_row(
            "Cooldown time",
            cooldown_control,
            tooltip="Number of seconds between each generation in a series.",
            subtitle="Seconds between generations in a series.",
        )

        self.imagegen_add_chat_prefix_postfix_checkbox = imagegen_panel.add_gear_toggle(
            "Add prefix/postfix from chat",
            on_gear_clicked=self._open_chat_prefix_postfix_library,
            tooltip=(
                "When enabled, prefix and postfix rules marked for images\n"
                "in the chat prefix/postfix library are applied to image\n"
                "generation prompts."
            ),
            subtitle="Apply chat prefix/postfix rules to image prompts.",
            gear_tooltip="Edit prefix and postfix rules",
        )

        default_dim_index = (
            align_generation_dimension(APP_MAX_GENERATION_DIMENSION_DEFAULT)
            - APP_MAX_GENERATION_DIMENSION_MIN
        ) // _dim_step
        self.imagegen_max_generation_dimension_slider.setValue(default_dim_index)
        self._update_imagegen_max_generation_dimension_label()

        self.imagegen_series_cooldown_slider.setValue(
            app_series_cooldown_seconds(
                {"imagegen_series_cooldown_seconds": APP_SERIES_COOLDOWN_SECONDS_DEFAULT}
            )
        )
        self._update_imagegen_series_cooldown_label()

        imagegen_section = QWidget()
        imagegen_section_layout = QVBoxLayout(imagegen_section)
        imagegen_section_layout.setContentsMargins(0, 0, 0, 0)
        imagegen_section_layout.setSpacing(6)
        imagegen_section_layout.addWidget(imagegen_title)
        imagegen_section_layout.addWidget(imagegen_panel)
        inner_layout.addWidget(imagegen_section)
        self._imagegen_general_settings_group = imagegen_section

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
    
    def _add_theme_color_swatch_row(
        self,
        column_layout: QVBoxLayout,
        label_text: str,
        key: str,
        width_key: Optional[str] = None,
        width_tooltip: Optional[str] = None,
        color_tooltip: Optional[str] = None,
    ):
        """Three columns: fixed label | fixed swatch | slider column (or empty spacer)."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 3, 0, 3)
        h.setSpacing(10)
        lbl = QLabel(label_text)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(self.THEME_LABEL_COL_WIDTH)
        h.addWidget(lbl)

        sw_outer = QWidget()
        sw_outer.setFixedWidth(self.THEME_SWATCH_COL_WIDTH)
        sw_l = QHBoxLayout(sw_outer)
        sw_l.setContentsMargins(0, 0, 0, 0)
        sw_l.addStretch()
        btn = QPushButton()
        btn.setText("")
        btn.setFixedSize(28, 28)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn.setStyleSheet("""
            QPushButton { min-height: 28px; min-width: 28px; max-height: 28px; max-width: 28px;
                          height: 28px; width: 28px; padding: 0px; margin: 0px; border: 1px solid white; }
        """)
        btn.setToolTip(color_tooltip or THEME_COLOR_SWATCH_TOOLTIPS.get(key, "Click to choose color"))
        btn.clicked.connect(lambda checked=False, k=key: self._choose_user_theme_color(k))
        self._user_theme_color_buttons[key] = btn
        sw_l.addWidget(btn)
        sw_l.addStretch()
        h.addWidget(sw_outer)

        third = QWidget()
        third_l = QHBoxLayout(third)
        third_l.setContentsMargins(0, 0, 0, 0)
        third.setMinimumWidth(self.THEME_SLIDER_COL_MIN_WIDTH)
        if width_key:
            s = QSlider(Qt.Horizontal)
            s.setRange(0, MAX_THEME_BORDER_WIDTH_PX)
            s.setSingleStep(1)
            s.setPageStep(1)
            s.setTickPosition(QSlider.TickPosition.NoTicks)
            s.setToolTip(width_tooltip or "")
            s.setFixedHeight(22)
            s.valueChanged.connect(
                lambda _v, k=width_key: self._schedule_user_theme_preview_live(k)
            )
            vl = QLabel("0")
            vl.setFixedWidth(26)
            vl.setAlignment(Qt.AlignCenter)
            s.valueChanged.connect(lambda v, lbl=vl: lbl.setText(str(v)))
            self._border_width_sliders[width_key] = s
            self._border_width_value_labels[width_key] = vl
            third_l.addWidget(s, 1)
            third_l.addWidget(vl)
        else:
            third_l.addStretch()
        h.addWidget(third, 1)
        column_layout.addWidget(row)

    def _add_theme_chrome_border_width_row(self, column_layout):
        """Row: label | spacer | slider for splitter / status bar top border thickness."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 3, 0, 3)
        h.setSpacing(10)
        lbl = QLabel("Splitter & status bar width:")
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(self.THEME_LABEL_COL_WIDTH)
        h.addWidget(lbl)

        sw_outer = QWidget()
        sw_outer.setFixedWidth(self.THEME_SWATCH_COL_WIDTH)
        h.addWidget(sw_outer)

        third = QWidget()
        third_l = QHBoxLayout(third)
        third_l.setContentsMargins(0, 0, 0, 0)
        third.setMinimumWidth(self.THEME_SLIDER_COL_MIN_WIDTH)
        s = QSlider(Qt.Horizontal)
        s.setRange(MIN_VIEW_CHROME_BORDER_WIDTH_PX, MAX_VIEW_CHROME_BORDER_WIDTH_PX)
        s.setSingleStep(1)
        s.setPageStep(1)
        s.setTickPosition(QSlider.TickPosition.NoTicks)
        s.setToolTip(
            "Thickness of main splitters and the line above the\n"
            "status bar (px). 0 = hidden."
        )
        s.setFixedHeight(22)
        s.valueChanged.connect(
            lambda _v, k="view_border_width_px": self._schedule_user_theme_preview_live(k)
        )
        vl = QLabel("2")
        vl.setFixedWidth(26)
        vl.setAlignment(Qt.AlignCenter)
        s.valueChanged.connect(lambda v, lbl=vl: lbl.setText(str(v)))
        self._border_width_sliders["view_border_width_px"] = s
        self._border_width_value_labels["view_border_width_px"] = vl
        third_l.addWidget(s, 1)
        third_l.addWidget(vl)
        h.addWidget(third, 1)
        column_layout.addWidget(row)

    def setup_theme_settings_tab(self):
        """Theme preset: vertical sections, scroll vertically only; per-border width sliders."""
        layout = QVBoxLayout(self.theme_settings_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setMinimumWidth(
            self.THEME_LABEL_COL_WIDTH
            + self.THEME_SWATCH_COL_WIDTH
            + self.THEME_SLIDER_COL_MIN_WIDTH
            + self.THEME_INNER_WIDTH_EXTRA
        )
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(12, 8, 20, 16)
        outer.setSpacing(16)

        preset_group = QGroupBox("Preset")
        preset_row = QHBoxLayout(preset_group)
        preset_row.setContentsMargins(8, 12, 8, 8)
        preset_row.setSpacing(12)
        preset_row.addWidget(QLabel("Use palette from:"))
        self.theme_preset_combo = QComboBox()
        self.theme_preset_combo.addItem("Dark", "dark")
        self.theme_preset_combo.addItem("Light", "light")
        self.theme_preset_combo.addItem("User", "user")
        self.theme_preset_combo.setToolTip("Each preset has its own saved color overrides.")
        self.theme_preset_combo.setMinimumWidth(200)
        self.theme_preset_combo.currentIndexChanged.connect(self._on_theme_preset_changed)
        preset_row.addWidget(self.theme_preset_combo)
        preset_row.addStretch()
        outer.addWidget(preset_group)

        self._user_theme_color_hex: dict = {}
        self._user_theme_color_buttons: dict = {}
        self._border_width_sliders: dict = {}
        self._border_width_value_labels: dict = {}
        self._theme_collapse_groups: dict[str, CollapsibleThemeGroup] = {}

        gb_text = CollapsibleThemeGroup("Text & background", state_key="text_background")
        v_text = gb_text.content_layout()
        v_text.setContentsMargins(8, 10, 8, 8)
        v_text.setSpacing(4)
        for label_text, key in (
            ("Application background:", "default_background_color_hex"),
            ("Main text:", "text_color_hex"),
        ):
            self._add_theme_color_swatch_row(v_text, label_text, key)
        outer.addWidget(gb_text)

        gb_dialogs = CollapsibleThemeGroup("Dialogs", state_key="dialogs")
        v_dialogs = gb_dialogs.content_layout()
        v_dialogs.setContentsMargins(8, 10, 8, 8)
        v_dialogs.setSpacing(4)
        for label_text, key in (
            ("Dialog background:", "dialog_background_hex"),
            ("Dialog text:", "dialog_text_color_hex"),
            ("Input backgrounds:", "dialog_input_background_hex"),
        ):
            self._add_theme_color_swatch_row(v_dialogs, label_text, key)
        outer.addWidget(gb_dialogs)

        gb_chrome = CollapsibleThemeGroup("Sidebar, panes and status bar", state_key="sidebar_chrome")
        v_chrome = gb_chrome.content_layout()
        v_chrome.setContentsMargins(8, 10, 8, 8)
        v_chrome.setSpacing(4)
        for label_text, key in (
            ("View titlebars bar:", "sidebar_header_bg_hex"),
            ("Sidebar background:", "sidebar_background_color_hex"),
            ("Sidebar text:", "sidebar_text_color_hex"),
            ("Status bar background:", "status_bar_background_color_hex"),
            ("Status bar text:", "status_bar_text_color_hex"),
            ("View borders:", "default_border_color_hex"),
        ):
            self._add_theme_color_swatch_row(v_chrome, label_text, key)
        self._add_theme_chrome_border_width_row(v_chrome)
        outer.addWidget(gb_chrome)

        gb_buttons = CollapsibleThemeGroup("Button settings", state_key="button_settings")
        v_buttons = gb_buttons.content_layout()
        v_buttons.setContentsMargins(8, 10, 8, 8)
        v_buttons.setSpacing(4)
        for label_text, key in (
            ("Button background:", "button_bg_default_hex"),
            ("Button border:", "button_border_default_hex"),
            ("Button text:", "button_text_default_hex"),
            ("Button hover background:", "button_bg_hover_hex"),
            ("Button hover border:", "button_border_hover_hex"),
            ("Button hover text:", "button_text_hover_hex"),
        ):
            self._add_theme_color_swatch_row(v_buttons, label_text, key)
        outer.addWidget(gb_buttons)

        gb_thumb = CollapsibleThemeGroup("Thumbnails and image selection", state_key="thumbnails_selection")
        v_thumb = gb_thumb.content_layout()
        v_thumb.setContentsMargins(8, 10, 8, 8)
        v_thumb.setSpacing(2)
        self._add_theme_color_swatch_row(
            v_thumb,
            "Thumbnail grid background:",
            "thumbnail_grid_background_color_hex",
        )
        self._add_theme_color_swatch_row(
            v_thumb,
            "Thumbnail text:",
            "thumbnail_text_color_hex",
        )
        self._add_theme_color_swatch_row(
            v_thumb,
            "Image border:",
            "default_image_color_hex",
            width_key="default_image_border_width_index",
            width_tooltip="Border around non-selected thumbnails\n(0 = hidden)",
        )
        self._add_theme_color_swatch_row(v_thumb, "Image background:", "default_image_background_color_hex")
        self._add_theme_color_swatch_row(
            v_thumb,
            "Active image border:",
            "current_image_border_color_hex",
            width_key="current_image_border_width_index",
            width_tooltip="Border for the active image thumbnail",
        )
        self._add_theme_color_swatch_row(v_thumb, "Active image background:", "current_image_background_color_hex")
        self._add_theme_color_swatch_row(
            v_thumb,
            "Multiselect Image border:",
            "multiselect_border_color_hex",
            width_key="multiselect_border_width_index",
            width_tooltip="Border when multiple thumbnails are selected",
        )
        self._add_theme_color_swatch_row(v_thumb, "Multiselect image background:", "multiselect_background_color_hex")
        outer.addWidget(gb_thumb)

        gb_browse = CollapsibleThemeGroup("Browse Colors", state_key="browse_colors")
        browse_form = QFormLayout()
        browse_content = gb_browse.content_layout()
        browse_content.setContentsMargins(0, 0, 0, 0)
        browse_content.addLayout(browse_form)
        browse_form.setContentsMargins(8, 10, 8, 8)
        browse_form.setVerticalSpacing(12)
        browse_form.setHorizontalSpacing(16)
        browse_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        transparency_color_container = QWidget()
        transparency_color_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        transparency_color_layout = QHBoxLayout(transparency_color_container)
        transparency_color_layout.setContentsMargins(0, 0, 0, 0)
        transparency_color_layout.setSpacing(14)
        self.transparency_color_button = QPushButton()
        self.transparency_color_button.setText("")
        self.transparency_color_button.setFixedSize(28, 28)
        self.transparency_color_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.transparency_color_button.setStyleSheet("""
            QPushButton { min-height: 28px; min-width: 28px; max-height: 28px; max-width: 28px;
                          height: 28px; width: 28px; padding: 0px; margin: 0px; border: 1px solid white; }
        """)
        self.transparency_color_button.setToolTip(
            "Transparency fill for transparent pixels in browse mode\n"
            "(for the palette selected above)"
        )
        self.transparency_color_button.clicked.connect(self.choose_transparency_color)
        transparency_color_layout.addWidget(self.transparency_color_button)
        or_label = QLabel("or")
        or_label.setStyleSheet("margin: 0px 4px;")
        transparency_color_layout.addWidget(or_label)
        self.use_diamonds_checkbox = QCheckBox("Use Checkerboard")
        self.use_diamonds_checkbox.setToolTip(
            "Use checkerboard pattern (tilted 45 degrees) instead of\n"
            "solid color for transparent pixels in browse mode"
        )
        self.use_diamonds_checkbox.setStyleSheet(self.SMALL_CHECKBOX_STYLE)
        self.use_diamonds_checkbox.stateChanged.connect(self._on_browse_transparency_widget_changed)
        transparency_color_layout.addWidget(self.use_diamonds_checkbox)
        transparency_color_layout.addStretch()
        transparency_color_label = QLabel("Transparency color:")
        transparency_color_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transparency_color_label.setMinimumWidth(self.THEME_LABEL_COL_WIDTH)
        browse_form.addRow(transparency_color_label, transparency_color_container)
        border_row = QWidget()
        border_row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        border_row_layout = QHBoxLayout(border_row)
        border_row_layout.setContentsMargins(0, 0, 0, 0)
        border_row_layout.setSpacing(14)
        self.browse_border_color_button = QPushButton()
        self.browse_border_color_button.setText("")
        self.browse_border_color_button.setFixedSize(28, 28)
        self.browse_border_color_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.browse_border_color_button.setStyleSheet("""
            QPushButton { min-height: 28px; min-width: 28px; max-height: 28px; max-width: 28px;
                          height: 28px; width: 28px; padding: 0px; margin: 0px; border: 1px solid white; }
        """)
        self.browse_border_color_button.setToolTip(
            "Fill color for the viewport margin when the image is\n"
            "smaller than the browse window"
        )
        self.browse_border_color_button.clicked.connect(self.choose_browse_border_color)
        border_row_layout.addWidget(self.browse_border_color_button)
        border_row_layout.addStretch()
        browse_border_label = QLabel("Browse border:")
        browse_border_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        browse_border_label.setMinimumWidth(self.THEME_LABEL_COL_WIDTH)
        browse_form.addRow(browse_border_label, border_row)
        outer.addWidget(gb_browse)

        for key, group in (
            ("text_background", gb_text),
            ("dialogs", gb_dialogs),
            ("sidebar_chrome", gb_chrome),
            ("button_settings", gb_buttons),
            ("thumbnails_selection", gb_thumb),
            ("browse_colors", gb_browse),
        ):
            self._theme_collapse_groups[key] = group
            group.expanded_changed.connect(self._on_theme_group_expanded_changed)
            group.option_set_all_expanded.connect(self._on_theme_groups_option_set_all_expanded)

        outer.addStretch(0)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

    def _apply_theme_collapse_groups_from_settings(self) -> None:
        if not hasattr(self, "_theme_collapse_groups"):
            return
        if hasattr(self, "current_settings"):
            merged = merge_theme_settings_groups_expanded(
                self.current_settings.get("theme_settings_groups_expanded")
            )
        else:
            merged = merge_theme_settings_groups_expanded(
                get_config().load_settings().get("theme_settings_groups_expanded")
            )
        for key, group in self._theme_collapse_groups.items():
            group.blockSignals(True)
            group.set_expanded(merged.get(key, False))
            group.blockSignals(False)

    def _on_theme_group_expanded_changed(self, state_key: str, expanded: bool) -> None:
        merged = merge_theme_settings_groups_expanded(
            self.current_settings.get("theme_settings_groups_expanded")
            if hasattr(self, "current_settings") else None
        )
        merged[state_key] = expanded
        self._persist_theme_collapse_groups(merged)

    def _on_theme_groups_option_set_all_expanded(self, expanded: bool) -> None:
        """Option-click on any theme section header expands or collapses every group.

        MAINTAINER: document in browser_window/dialogs/help_hidden_gems.py.
        """
        if not hasattr(self, "_theme_collapse_groups"):
            return
        merged = merge_theme_settings_groups_expanded(
            self.current_settings.get("theme_settings_groups_expanded")
            if hasattr(self, "current_settings") else None
        )
        for key in THEME_COLLAPSE_GROUP_KEYS:
            merged[key] = expanded
        for group in self._theme_collapse_groups.values():
            group.blockSignals(True)
            group.set_expanded(expanded)
            group.blockSignals(False)
        self._persist_theme_collapse_groups(merged)

    def _persist_theme_collapse_groups(self, merged: dict[str, bool]) -> None:
        merged_copy = copy.deepcopy(merged)
        if hasattr(self, "current_settings"):
            self.current_settings["theme_settings_groups_expanded"] = merged_copy
        if hasattr(self, "original_settings"):
            self.original_settings["theme_settings_groups_expanded"] = copy.deepcopy(merged_copy)
        get_config().update_setting("theme_settings_groups_expanded", merged_copy)

    def _populate_theme_tab_swatches(self):
        """Fill swatches from saved palette for the selected preset (dark / light / user)."""
        if not hasattr(self, "_user_theme_color_buttons"):
            return
        tid = self.theme_preset_combo.currentData()
        cs = self.current_settings if hasattr(self, "current_settings") else None
        if tid == "user":
            merged = merge_user_theme_colors(cs.get("user_theme_colors") if cs else None)
        elif tid == "dark":
            merged = merge_dark_theme_colors(cs.get("dark_theme_colors") if cs else None)
        elif tid == "light":
            merged = merge_light_theme_colors(cs.get("light_theme_colors") if cs else None)
        else:
            merged = default_user_theme_colors()
        self._user_theme_color_hex = {k: merged[k] for k in USER_THEME_COLOR_KEYS}
        for k in USER_THEME_COLOR_KEYS:
            self._update_user_theme_color_button(k)
        for btn in self._user_theme_color_buttons.values():
            btn.setEnabled(tid in ("dark", "light", "user"))
        if hasattr(self, "_border_width_sliders"):
            for k in THEME_BORDER_WIDTH_KEYS:
                sl = self._border_width_sliders.get(k)
                if not sl:
                    continue
                ibw = int(merged.get(k, 1))
                sl.blockSignals(True)
                sl.setValue(ibw)
                sl.blockSignals(False)
                sl.setEnabled(tid in ("dark", "light", "user"))
                if getattr(self, "_border_width_value_labels", None) and k in self._border_width_value_labels:
                    self._border_width_value_labels[k].setText(str(ibw))
        for k in VIEW_CHROME_THEME_KEYS:
            sl = self._border_width_sliders.get(k)
            if not sl:
                continue
            vw = int(merged.get(k, 2))
            sl.blockSignals(True)
            sl.setValue(vw)
            sl.blockSignals(False)
            sl.setEnabled(tid in ("dark", "light", "user"))
            if getattr(self, "_border_width_value_labels", None) and k in self._border_width_value_labels:
                self._border_width_value_labels[k].setText(str(vw))

    def _on_theme_preset_changed(self, *_args):
        prev = getattr(self, "_last_theme_preset_id", None)
        tid = self.theme_preset_combo.currentData()
        if (
            prev is not None
            and prev in ("dark", "light", "user")
            and tid in ("dark", "light", "user")
            and prev != tid
            and hasattr(self, "use_diamonds_checkbox")
        ):
            self._flush_browse_transparency_entry(prev)
        self._populate_theme_tab_swatches()
        if tid in ("dark", "light", "user"):
            self._load_browse_transparency_entry(tid)
        self._last_theme_preset_id = tid
        self._apply_theme_tab_from_dialog()

    def _flush_browse_transparency_entry(self, tid: str) -> None:
        if not tid or tid not in ("dark", "light", "user") or not hasattr(self, "use_diamonds_checkbox"):
            return
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        tc = ent.get("transparency_color", [98, 98, 98])
        try:
            rgb = [int(tc[0]), int(tc[1]), int(tc[2])]
        except (TypeError, ValueError, IndexError):
            rgb = [98, 98, 98]
        bb = ent.get("browse_border_color", [0, 0, 0])
        try:
            bb = [int(bb[0]), int(bb[1]), int(bb[2])]
        except (TypeError, ValueError, IndexError):
            bb = [0, 0, 0]
        bts[tid] = {
            "transparency_color": rgb,
            "use_diamonds": self.use_diamonds_checkbox.isChecked(),
            "browse_border_color": bb,
        }
        self.current_settings["browse_transparency_settings"] = bts

    def _load_browse_transparency_entry(self, tid: str) -> None:
        if not tid or tid not in ("dark", "light", "user") or not hasattr(self, "use_diamonds_checkbox"):
            return
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        self.current_settings["browse_transparency_settings"] = bts
        ent = bts.get(tid, default_browse_transparency_entry())
        self.use_diamonds_checkbox.blockSignals(True)
        self.use_diamonds_checkbox.setChecked(bool(ent["use_diamonds"]))
        self.use_diamonds_checkbox.blockSignals(False)
        self._update_transparency_color_button()
        self._update_browse_border_color_button()

    def _on_browse_transparency_widget_changed(self, *_args) -> None:
        if not hasattr(self, "theme_preset_combo"):
            return
        tid = self.theme_preset_combo.currentData()
        if tid not in ("dark", "light", "user"):
            return
        self._flush_browse_transparency_entry(tid)
        mw = self.parent()
        if mw and getattr(mw, "current_view_mode", None) == "browse":
            mw.update_image_display()

    def _update_user_theme_color_button(self, key: str):
        btn = self._user_theme_color_buttons.get(key)
        if not btn:
            return
        hx = self._user_theme_color_hex.get(key, "#000000")
        c = QColor(hx)
        if not c.isValid():
            c = QColor("#000000")
        btn_size = 28
        btn.setStyleSheet(f"""
            QPushButton {{
                min-height: {btn_size}px; min-width: {btn_size}px; max-height: {btn_size}px; max-width: {btn_size}px;
                height: {btn_size}px; width: {btn_size}px; padding: 0px; margin: 0px;
                background-color: {c.name()};
                border: 1px solid white;
            }}
        """)

    def _on_user_theme_color_picker_changed(self, color: QColor):
        """Live updates from the color panel; swatch updates immediately, theme apply is debounced."""
        if not color.isValid():
            return
        key = self._user_theme_color_picker_active_key
        if not key:
            return
        self._user_theme_color_hex[key] = color.name()
        self._update_user_theme_color_button(key)
        self._schedule_user_theme_preview_live(key)

    def _schedule_user_theme_preview_live(self, key: Optional[str] = None) -> None:
        """Debounce live theme preview (color picker drags and border-width sliders)."""
        if key:
            self._theme_live_preview_changed_keys.add(key)
        self._user_theme_color_live_timer.stop()
        self._user_theme_color_live_timer.start()

    def _debounced_apply_user_theme_preview_live(self):
        changed = self._theme_live_preview_changed_keys
        self._theme_live_preview_changed_keys = set()
        apply_scope = theme_apply_scope_for_keys(changed)
        self._apply_user_theme_preview_live(
            apply_scope=apply_scope,
            skip_dialog_theme=(apply_scope == "thumbnail"),
        )

    def _apply_user_theme_preview_live(
        self,
        *,
        apply_scope: str = "full",
        skip_dialog_theme: bool = False,
    ):
        """Apply palette from in-memory swatches without persisting config (live color picker)."""
        tid = self.theme_preset_combo.currentData()
        if tid not in ("dark", "light", "user"):
            return
        cfg = get_config()
        colors = self._get_user_theme_colors_from_widgets()
        kwargs = dict(
            app=QApplication.instance(),
            main_window=self.parent(),
            persist=False,
            config=cfg,
            apply_scope=apply_scope,
        )
        if tid == "user":
            kwargs["user_theme_colors"] = colors
            apply_theme("user", **kwargs)
        elif tid == "dark":
            kwargs["dark_theme_colors"] = colors
            apply_theme("dark", **kwargs)
        else:
            kwargs["light_theme_colors"] = colors
            apply_theme("light", **kwargs)
        self._mark_main_window_theme_touched()
        self._sync_theme_context()
        if not skip_dialog_theme:
            self.apply_theme()
        mw = self.parent()
        if mw:
            from theme.theme_service import sync_view_theme_menu_actions

            sync_view_theme_menu_actions(mw, tid)

    def _choose_user_theme_color(self, key: str):
        if self.theme_preset_combo.currentData() not in ("dark", "light", "user"):
            return
        hx = self._user_theme_color_hex.get(key, "#000000")
        current = QColor(hx)
        if not current.isValid():
            current = QColor("#000000")
        hex_before = self._user_theme_color_hex.get(key, "#000000")

        dlg = QColorDialog(current, self)
        dlg.setWindowTitle("Choose color")
        self._user_theme_color_picker_active_key = key
        dlg.currentColorChanged.connect(self._on_user_theme_color_picker_changed)
        result = dlg.exec()
        self._user_theme_color_live_timer.stop()
        self._theme_live_preview_changed_keys.clear()
        self._user_theme_color_picker_active_key = None
        try:
            dlg.currentColorChanged.disconnect(self._on_user_theme_color_picker_changed)
        except TypeError:
            pass

        if result == QDialog.DialogCode.Accepted:
            c = dlg.currentColor()
            if c.isValid():
                self._user_theme_color_hex[key] = c.name()
                self._update_user_theme_color_button(key)
            self._apply_theme_tab_from_dialog()
        else:
            self._user_theme_color_hex[key] = hex_before
            self._update_user_theme_color_button(key)
            self._apply_theme_tab_from_dialog()

    def _load_theme_tab_from_settings(self):
        """Populate theme tab from original_settings / config."""
        if not hasattr(self, "theme_preset_combo"):
            return
        cfg = get_config()
        s = cfg.load_settings()
        tid = (s.get("ui_theme") or "dark").lower()
        if tid == "system":
            from theme.theme_service import system_appearance_theme_id

            tid = system_appearance_theme_id()
        elif tid not in ("dark", "light", "user"):
            tid = "dark"
        idx = self.theme_preset_combo.findData(tid)
        if idx < 0:
            idx = 0
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.setCurrentIndex(idx)
        self.theme_preset_combo.blockSignals(False)

        self._populate_theme_tab_swatches()
        if tid in ("dark", "light", "user"):
            self._load_browse_transparency_entry(tid)
            self._last_theme_preset_id = tid
            # Combo reflects persisted ui_theme; apply palette so dialog chrome matches.
            if getattr(get_active_theme(), "theme_id", "dark") != tid:
                self._apply_theme_tab_from_dialog()
            else:
                self._sync_theme_context()
                self.apply_theme()

    def _get_user_theme_colors_from_widgets(self) -> dict:
        tid = self.theme_preset_combo.currentData()
        if tid == "dark":
            base = default_dark_theme_colors()
        elif tid == "light":
            base = default_light_theme_colors()
        else:
            base = default_user_theme_colors()
        out = {k: self._user_theme_color_hex.get(k, base[k]) for k in USER_THEME_COLOR_KEYS}
        for k in THEME_BORDER_WIDTH_KEYS:
            if hasattr(self, "_border_width_sliders") and k in self._border_width_sliders:
                out[k] = int(self._border_width_sliders[k].value())
            else:
                out[k] = int(base.get(k, 1))
        for k in VIEW_CHROME_THEME_KEYS:
            if hasattr(self, "_border_width_sliders") and k in self._border_width_sliders:
                out[k] = int(self._border_width_sliders[k].value())
            else:
                out[k] = int(base.get(k, 2))
        return out

    def _apply_theme_tab_from_dialog(self):
        """Live-preview theme from widgets; disk write happens in accept()."""
        cfg = get_config()
        tid = self.theme_preset_combo.currentData()
        if tid in ("dark", "light", "user") and hasattr(self, "use_diamonds_checkbox"):
            self._flush_browse_transparency_entry(tid)
        colors = self._get_user_theme_colors_from_widgets()
        if hasattr(self, "current_settings"):
            self.current_settings["ui_theme"] = tid
            if tid == "user":
                self.current_settings["user_theme_colors"] = copy.deepcopy(colors)
            elif tid == "dark":
                self.current_settings["dark_theme_colors"] = copy.deepcopy(colors)
            elif tid == "light":
                self.current_settings["light_theme_colors"] = copy.deepcopy(colors)
        kwargs = dict(
            app=QApplication.instance(),
            main_window=self.parent(),
            persist=False,
            config=cfg,
        )
        if tid == "user":
            apply_theme("user", **kwargs, user_theme_colors=colors)
        elif tid == "dark":
            apply_theme("dark", **kwargs, dark_theme_colors=colors)
        elif tid == "light":
            apply_theme("light", **kwargs, light_theme_colors=colors)
        self._mark_main_window_theme_touched()
        self._sync_theme_context()
        self.apply_theme()
        mw = self.parent()
        if mw:
            from theme.theme_service import sync_view_theme_menu_actions

            sync_view_theme_menu_actions(mw, tid)
            # Preset switch updates ui_theme + browse_transparency for active profile; repaint browse margin/border.
            if getattr(mw, "current_view_mode", None) == "browse":
                mw.update_image_display()

    def _capture_theme_snapshot_at_open(self):
        self._main_window_theme_touched = False
        cfg = get_config()
        s = cfg.load_settings()
        self._theme_snapshot_at_open = {
            "ui_theme": s.get("ui_theme", "dark"),
            "user_theme_colors": copy.deepcopy(s.get("user_theme_colors") or {}),
            "dark_theme_colors": copy.deepcopy(s.get("dark_theme_colors") or {}),
            "light_theme_colors": copy.deepcopy(s.get("light_theme_colors") or {}),
            "browse_transparency_settings": copy.deepcopy(
                merge_browse_transparency_settings(s.get("browse_transparency_settings"))
            ),
        }

    def _theme_snapshot_disk_restore_needed(self, snap: dict, settings: dict) -> bool:
        """True when cancel must rewrite theme keys back to the open-time snapshot."""
        if (settings.get("ui_theme") or "dark") != snap.get("ui_theme", "dark"):
            return True
        for key, merge_fn in (
            ("user_theme_colors", merge_user_theme_colors),
            ("dark_theme_colors", merge_dark_theme_colors),
            ("light_theme_colors", merge_light_theme_colors),
        ):
            stored = merge_fn(settings.get(key) if isinstance(settings.get(key), dict) else None)
            snap_val = merge_fn(snap.get(key) if isinstance(snap.get(key), dict) else None)
            if tuple(sorted(stored.items())) != tuple(sorted(snap_val.items())):
                return True
        o = merge_browse_transparency_settings(
            settings.get("browse_transparency_settings") if isinstance(settings.get("browse_transparency_settings"), dict) else None
        )
        n = merge_browse_transparency_settings(snap.get("browse_transparency_settings"))
        o_t = tuple(
            sorted(
                (
                    t,
                    tuple(o[t]["transparency_color"]),
                    o[t]["use_diamonds"],
                    tuple(o[t]["browse_border_color"]),
                )
                for t in ("dark", "light", "user")
            )
        )
        n_t = tuple(
            sorted(
                (
                    t,
                    tuple(n[t]["transparency_color"]),
                    n[t]["use_diamonds"],
                    tuple(n[t]["browse_border_color"]),
                )
                for t in ("dark", "light", "user")
            )
        )
        return o_t != n_t

    def _restore_theme_snapshot_at_open(self):
        get_config().set_browse_transparency_preview(None)
        if not getattr(self, "_theme_snapshot_at_open", None):
            return
        snap = self._theme_snapshot_at_open
        cfg = get_config()
        settings = cfg.load_settings()
        disk_restore = self._theme_snapshot_disk_restore_needed(snap, settings)
        if disk_restore:
            cfg.update_settings({
                "ui_theme": snap["ui_theme"],
                "user_theme_colors": copy.deepcopy(snap["user_theme_colors"]),
                "dark_theme_colors": copy.deepcopy(snap["dark_theme_colors"]),
                "light_theme_colors": copy.deepcopy(snap["light_theme_colors"]),
                "browse_transparency_settings": copy.deepcopy(
                    merge_browse_transparency_settings(snap.get("browse_transparency_settings"))
                ),
            })
        if not disk_restore and not getattr(self, "_main_window_theme_touched", False):
            return
        tid = snap["ui_theme"]
        apply_theme(
            tid,
            app=QApplication.instance(),
            main_window=self.parent(),
            persist=False,
            config=cfg,
        )
        self._sync_theme_context()
        self.apply_theme()
        mw = self.parent()
        if mw:
            from theme.theme_service import sync_view_theme_menu_actions

            sync_view_theme_menu_actions(mw, tid)

    def _update_browse_image_history_save_after_label(self) -> None:
        if not hasattr(self, 'browse_image_history_save_after_value_label'):
            return
        ms = self.browse_image_history_save_after_slider.value() * 500
        if ms <= 0:
            self.browse_image_history_save_after_value_label.setText("Immediately (0 ms)")
        else:
            sec = ms / 1000.0
            self.browse_image_history_save_after_value_label.setText(f"{ms} ms ({sec:.1f} s)")

    def _on_browse_image_history_save_after_slider_changed(self, _value: int) -> None:
        self._update_browse_image_history_save_after_label()

    def _load_imagegen_general_settings(self, settings: dict) -> None:
        """Apply persisted max dimension and series cooldown to General tab sliders."""
        if 'imagegen_max_generation_dimension' in settings and hasattr(
            self, 'imagegen_max_generation_dimension_slider'
        ):
            from imagegen_plugins.image_gen_dim_limits import (
                APP_MAX_GENERATION_DIMENSION_MIN,
                APP_MAX_GENERATION_DIMENSION_STEP,
                align_generation_dimension,
            )

            px = align_generation_dimension(
                settings['imagegen_max_generation_dimension']
            )
            index = (px - APP_MAX_GENERATION_DIMENSION_MIN) // APP_MAX_GENERATION_DIMENSION_STEP
            self.imagegen_max_generation_dimension_slider.blockSignals(True)
            self.imagegen_max_generation_dimension_slider.setValue(index)
            self.imagegen_max_generation_dimension_slider.blockSignals(False)
            self._update_imagegen_max_generation_dimension_label()
        if 'imagegen_series_cooldown_seconds' in settings and hasattr(
            self, 'imagegen_series_cooldown_slider'
        ):
            from imagegen_plugins.image_gen_dim_limits import app_series_cooldown_seconds

            sec = app_series_cooldown_seconds(settings)
            self.imagegen_series_cooldown_slider.blockSignals(True)
            self.imagegen_series_cooldown_slider.setValue(sec)
            self.imagegen_series_cooldown_slider.blockSignals(False)
            self._update_imagegen_series_cooldown_label()
        if hasattr(self, 'imagegen_add_chat_prefix_postfix_checkbox'):
            enabled = settings.get('imagegen_add_chat_prefix_postfix', True)
            self.imagegen_add_chat_prefix_postfix_checkbox.setChecked(enabled)

    def _imagegen_max_generation_dimension_px(self) -> int:
        from imagegen_plugins.image_gen_dim_limits import (
            APP_MAX_GENERATION_DIMENSION_MIN,
            APP_MAX_GENERATION_DIMENSION_STEP,
            align_generation_dimension,
        )

        index = int(self.imagegen_max_generation_dimension_slider.value())
        px = APP_MAX_GENERATION_DIMENSION_MIN + index * APP_MAX_GENERATION_DIMENSION_STEP
        return align_generation_dimension(px)

    def _update_imagegen_max_generation_dimension_label(self) -> None:
        px = self._imagegen_max_generation_dimension_px()
        self.imagegen_max_generation_dimension_value_label.setText(f"{px} px")

    def _on_imagegen_max_generation_dimension_slider_changed(self, _value: int) -> None:
        self._update_imagegen_max_generation_dimension_label()

    def _update_imagegen_series_cooldown_label(self) -> None:
        sec = int(self.imagegen_series_cooldown_slider.value())
        if sec == 1:
            self.imagegen_series_cooldown_value_label.setText("1 second")
        elif sec == 0:
            self.imagegen_series_cooldown_value_label.setText("0 seconds")
        else:
            self.imagegen_series_cooldown_value_label.setText(f"{sec} seconds")

    def _on_imagegen_series_cooldown_slider_changed(self, _value: int) -> None:
        self._update_imagegen_series_cooldown_label()

    def _open_chat_prefix_postfix_library(self) -> None:
        from chat_plugins.chat_prefix_postfix import run_chat_prefix_postfix_library

        run_chat_prefix_postfix_library(self)

    @staticmethod
    def _browse_rgb3_tuple(val, default):
        if isinstance(val, (list, tuple)) and len(val) >= 3:
            try:
                return [int(val[0]), int(val[1]), int(val[2])]
            except (TypeError, ValueError):
                pass
        return list(default)

    def _on_browse_color_dialog_changed(self, color: QColor) -> None:
        if not color.isValid():
            return
        mode = getattr(self, "_browse_color_picker_active", None)
        tid = getattr(self, "_browse_color_picker_tid", None)
        if mode not in ("border", "transparency") or tid not in ("dark", "light", "user"):
            return
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        tc = self._browse_rgb3_tuple(ent.get("transparency_color"), [98, 98, 98])
        bb = self._browse_rgb3_tuple(ent.get("browse_border_color"), [0, 0, 0])
        if mode == "border":
            bb = [color.red(), color.green(), color.blue()]
        else:
            tc = [color.red(), color.green(), color.blue()]
        bts[tid] = {
            "transparency_color": tc,
            "use_diamonds": bool(ent.get("use_diamonds", True)),
            "browse_border_color": bb,
        }
        self.current_settings["browse_transparency_settings"] = bts
        get_config().set_browse_transparency_preview(copy.deepcopy(bts))
        if mode == "border":
            self._update_browse_border_color_button()
        else:
            self._update_transparency_color_button()
        self._browse_transparency_live_timer.stop()
        self._browse_transparency_live_timer.start()

    def _debounced_browse_color_live_refresh(self) -> None:
        if not getattr(self, "_browse_color_picker_active", None):
            return
        mw = self.parent()
        if mw and getattr(mw, "current_view_mode", None) == "browse":
            mw.update_image_display()

    def choose_transparency_color(self):
        """Open color picker for the browse transparency fill of the selected theme preset."""
        cfg = get_config()
        cfg.set_browse_transparency_preview(None)
        tid = self.theme_preset_combo.currentData() if hasattr(self, "theme_preset_combo") else "dark"
        if tid not in ("dark", "light", "user"):
            tid = "dark"
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        snapshot_ent = copy.deepcopy(ent)
        tc = self._browse_rgb3_tuple(ent.get("transparency_color"), [98, 98, 98])
        current_color = QColor(tc[0], tc[1], tc[2])

        dlg = QColorDialog(current_color, self)
        dlg.setWindowTitle("Choose Transparency Color")
        self._browse_color_picker_active = "transparency"
        self._browse_color_picker_tid = tid
        dlg.currentColorChanged.connect(self._on_browse_color_dialog_changed)
        result = dlg.exec()
        self._browse_transparency_live_timer.stop()
        self._browse_color_picker_active = None
        self._browse_color_picker_tid = None
        try:
            dlg.currentColorChanged.disconnect(self._on_browse_color_dialog_changed)
        except TypeError:
            pass
        cfg.set_browse_transparency_preview(None)

        if result == QDialog.DialogCode.Accepted:
            c = dlg.currentColor()
            if c.isValid():
                bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
                ent_latest = bts.get(tid, default_browse_transparency_entry())
                bb = self._browse_rgb3_tuple(ent_latest.get("browse_border_color"), [0, 0, 0])
                bts[tid] = {
                    "transparency_color": [c.red(), c.green(), c.blue()],
                    "use_diamonds": bool(ent_latest.get("use_diamonds", True)),
                    "browse_border_color": bb,
                }
                self.current_settings["browse_transparency_settings"] = bts
            self._update_transparency_color_button()
        else:
            bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
            bts[tid] = copy.deepcopy(snapshot_ent)
            self.current_settings["browse_transparency_settings"] = bts
            self._update_transparency_color_button()
        mw = self.parent()
        if mw and getattr(mw, "current_view_mode", None) == "browse":
            mw.update_image_display()
    
    def _update_transparency_color_button(self):
        """Update the transparency color button appearance"""
        if not hasattr(self, 'transparency_color_button'):
            return
        tid = self.theme_preset_combo.currentData() if hasattr(self, "theme_preset_combo") else "dark"
        if tid not in ("dark", "light", "user"):
            tid = "dark"
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        color_rgb = ent.get("transparency_color", [98, 98, 98])
        try:
            c = QColor(int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
        except (TypeError, ValueError, IndexError):
            c = QColor(98, 98, 98)
        if not c.isValid():
            c = QColor(98, 98, 98)
        self.transparency_color_button.setStyleSheet(f"""
            QPushButton {{
                min-height: 28px; min-width: 28px; max-height: 28px; max-width: 28px;
                height: 28px; width: 28px; padding: 0px; margin: 0px;
                background-color: {c.name()};
                border: 1px solid white;
            }}
        """)

    def choose_browse_border_color(self):
        """Color picker for browse viewport margin (letterbox) for the selected theme preset."""
        cfg = get_config()
        cfg.set_browse_transparency_preview(None)
        tid = self.theme_preset_combo.currentData() if hasattr(self, "theme_preset_combo") else "dark"
        if tid not in ("dark", "light", "user"):
            tid = "dark"
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        snapshot_ent = copy.deepcopy(ent)
        bb = self._browse_rgb3_tuple(ent.get("browse_border_color"), [0, 0, 0])
        current_color = QColor(bb[0], bb[1], bb[2])

        dlg = QColorDialog(current_color, self)
        dlg.setWindowTitle("Choose Browse Border Color")
        self._browse_color_picker_active = "border"
        self._browse_color_picker_tid = tid
        dlg.currentColorChanged.connect(self._on_browse_color_dialog_changed)
        result = dlg.exec()
        self._browse_transparency_live_timer.stop()
        self._browse_color_picker_active = None
        self._browse_color_picker_tid = None
        try:
            dlg.currentColorChanged.disconnect(self._on_browse_color_dialog_changed)
        except TypeError:
            pass
        cfg.set_browse_transparency_preview(None)

        if result == QDialog.DialogCode.Accepted:
            c = dlg.currentColor()
            if c.isValid():
                bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
                ent_latest = bts.get(tid, default_browse_transparency_entry())
                tc = self._browse_rgb3_tuple(ent_latest.get("transparency_color"), [98, 98, 98])
                bts[tid] = {
                    "transparency_color": tc,
                    "use_diamonds": bool(ent_latest.get("use_diamonds", True)),
                    "browse_border_color": [c.red(), c.green(), c.blue()],
                }
                self.current_settings["browse_transparency_settings"] = bts
            self._update_browse_border_color_button()
        else:
            bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
            bts[tid] = copy.deepcopy(snapshot_ent)
            self.current_settings["browse_transparency_settings"] = bts
            self._update_browse_border_color_button()
        mw = self.parent()
        if mw and getattr(mw, "current_view_mode", None) == "browse":
            mw.update_image_display()

    def _update_browse_border_color_button(self):
        if not hasattr(self, "browse_border_color_button"):
            return
        tid = self.theme_preset_combo.currentData() if hasattr(self, "theme_preset_combo") else "dark"
        if tid not in ("dark", "light", "user"):
            tid = "dark"
        bts = merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
        ent = bts.get(tid, default_browse_transparency_entry())
        color_rgb = ent.get("browse_border_color", [0, 0, 0])
        try:
            c = QColor(int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
        except (TypeError, ValueError, IndexError):
            c = QColor(0, 0, 0)
        if not c.isValid():
            c = QColor(0, 0, 0)
        self.browse_border_color_button.setStyleSheet(f"""
            QPushButton {{
                min-height: 28px; min-width: 28px; max-height: 28px; max-width: 28px;
                height: 28px; width: 28px; padding: 0px; margin: 0px;
                background-color: {c.name()};
                border: 1px solid white;
            }}
        """)
    
    def _thumbnail_overlay_settings_from_window(self):
        """Read thumbnail filename/size overlay state from the main window (Cmd+I toggles)."""
        parent_window = self.parent()
        if parent_window:
            return (
                getattr(parent_window, 'thumbnail_filename_visible', False),
                getattr(parent_window, 'show_image_size', False),
            )
        return (
            self._overlay_filename_visible,
            self._show_image_size,
        )

    def _set_dialog_overlay_settings(self, filename_visible, show_image_size, *, dialog_edited=False):
        """Track overlay settings in dialog state (no UI controls for these)."""
        self._overlay_filename_visible = bool(filename_visible)
        self._show_image_size = bool(show_image_size)
        if dialog_edited:
            self._overlay_settings_dialog_edited = True

    def _sync_overlay_settings_from_window(self):
        """Refresh dialog overlay state and baseline from the main window."""
        filename_visible, show_image_size = self._thumbnail_overlay_settings_from_window()
        self._set_dialog_overlay_settings(filename_visible, show_image_size, dialog_edited=False)
        self._overlay_settings_dialog_edited = False
        self.original_settings['thumbnail_filename_visible'] = self._overlay_filename_visible
        self.original_settings['show_image_size'] = self._show_image_size

    def _get_overlay_settings_for_save(self):
        """Overlay values to persist: dialog edits win; otherwise live window (Cmd+I while open)."""
        if self._overlay_settings_dialog_edited:
            return self._overlay_filename_visible, self._show_image_size
        return self._thumbnail_overlay_settings_from_window()

    def validate_filter_pattern(self, pattern):
        """Validate the filter pattern input and update match count info"""
        # Clear match count initially
        self.match_count_label.setText("")
        
        if not pattern:
            self.filter_validation_label.setText("No filter applied")
            self.filter_validation_label.setStyleSheet(f"color: {TEXT_DISABLED_HEX}; font-style: italic;")
            # Enable buttons
            if hasattr(self, 'ok_button'):
                self.ok_button.setEnabled(True)
            if hasattr(self, 'apply_filter_button'):
                self.apply_filter_button.setEnabled(True)
            
            # If parent exists, show total count of files
            if self.parent() and hasattr(self.parent(), 'current_directory'):
                directory = self.parent().current_directory
                if directory and os.path.exists(directory):
                    # Count all image files in directory
                    image_extensions = get_image_extensions()
                    total_files = 0
                    for filename in os.listdir(directory):
                        file_path = f"{directory.rstrip('/')}/{filename}"
                        if os.path.isfile(file_path):
                            _, ext = os.path.splitext(filename)
                            if ext.lower() in image_extensions:
                                total_files += 1
                    self.match_count_label.setText(f"{total_files} total files in directory.")
            return True
            
        try:
            # Check for basic syntax errors
            if pattern.count('[') != pattern.count(']'):
                self.filter_validation_label.setText("Invalid: Unmatched brackets")
                self.filter_validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-style: italic;")
                # Disable buttons
                if hasattr(self, 'ok_button'):
                    self.ok_button.setEnabled(False)
                if hasattr(self, 'apply_filter_button'):
                    self.apply_filter_button.setEnabled(False)
                return False
                
            # Test the pattern with fnmatch (add trailing asterisk for testing)
            try:
                # Add trailing asterisk for fnmatch testing
                test_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(pattern)
                # Try to compile the pattern
                fnmatch.translate(test_pattern)
                self.filter_validation_label.setText("✔") # valid pattern
                self.filter_validation_label.setStyleSheet(f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-style: italic;")
                # Enable buttons
                if hasattr(self, 'ok_button'):
                    self.ok_button.setEnabled(True)
                if hasattr(self, 'apply_filter_button'):
                    self.apply_filter_button.setEnabled(True)
                
                # Count matching files if parent exists
                self.update_match_count(pattern)
                return True
            except Exception:
                self.filter_validation_label.setText("❌") # invalid pattern
                self.filter_validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-style: italic;")
                # Disable buttons
                if hasattr(self, 'ok_button'):
                    self.ok_button.setEnabled(False)
                if hasattr(self, 'apply_filter_button'):
                    self.apply_filter_button.setEnabled(False)
                return False
                
        except Exception:
            self.filter_validation_label.setText("❌") # error validating pattern
            self.filter_validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-style: italic;")
            # Disable buttons
            if hasattr(self, 'ok_button'):
                self.ok_button.setEnabled(False)
            if hasattr(self, 'apply_filter_button'):
                self.apply_filter_button.setEnabled(False)
            return False

    def update_match_count(self, pattern):
        """Count and display the number of files matching the pattern"""
        if not self.parent() or not hasattr(self.parent(), 'current_directory'):
            return
        
        try:
            # Get the current directory from parent
            directory = self.parent().current_directory
            if not directory or not os.path.exists(directory):
                return
            
            # Count image files and matching files in a single pass
            image_extensions = get_image_extensions()
            total_count = 0
            match_count = 0
            
            # Get the pattern for matching
            test_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(pattern)
            
            # Count files in a single directory scan
            for filename in os.listdir(directory):
                file_path = f"{directory.rstrip('/')}/{filename}"
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(filename)
                    if ext.lower() in image_extensions:
                        total_count += 1
                        # Check if this file matches the pattern
                        if test_pattern and fnmatch.fnmatch(filename, test_pattern):
                            match_count += 1
            
            # Display match count
            if pattern:
                self.match_count_label.setText(f"{match_count} of {total_count} files match pattern '{pattern}'.")
            else:
                self.match_count_label.setText(f"{total_count} total files in directory.")
            
            # Change color based on match percentage
            if match_count == 0:
                self.match_count_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-size: 11px;")  # Light red for no matches
            elif match_count < total_count / 5:  # Less than 20% match
                self.match_count_label.setStyleSheet(f"color: {BUTTON_TEXT_HOVER_HEX}; font-size: 11px;")
            else:
                self.match_count_label.setStyleSheet(f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-size: 11px;")  # Light green for many matches
        
        except Exception as e:
            # In case of any error, show a generic message
            self.match_count_label.setText(f"Error counting matches: {str(e)}")
            self.match_count_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-size: 11px;")
        
    def setup_slideshow_settings_tab(self):
        """Setup the slideshow settings tab"""
        layout = QVBoxLayout(self.slideshow_settings_tab)
        
        # Slideshow settings group
        slideshow_group = QGroupBox("Slideshow Configuration")
        slideshow_layout = QGridLayout(slideshow_group)
        
        # Slideshow rate setting (time between slides)
        self.slideshow_rate_spinbox = StepSpinBox()
        self.slideshow_rate_spinbox.setRange(1000, 60000)  # 1 second to 1 minute
        self.slideshow_rate_spinbox.setSingleStep(1000)  # 1000ms increments
        self.slideshow_rate_spinbox.setSuffix(" ms")
        self.slideshow_rate_spinbox.setToolTip(
            "Time between slides in milliseconds (1000ms = 1\n"
            "second)"
        )

        # Transition speed setting
        self.transition_speed_spinbox = StepSpinBox()
        self.transition_speed_spinbox.setRange(0, 10000)  # 0 to 10 seconds
        self.transition_speed_spinbox.setSingleStep(100)  # 100ms increments
        self.transition_speed_spinbox.setSuffix(" ms")
        self.transition_speed_spinbox.setToolTip(
            "Animation duration for slide transitions in\n"
            "milliseconds"
        )

        # Rotation angle setting
        self.rotation_angle_spinbox = StepSpinBox()
        self.rotation_angle_spinbox.setRange(0, 360)
        self.rotation_angle_spinbox.setSingleStep(15)
        self.rotation_angle_spinbox.setSuffix("°")
        self.rotation_angle_spinbox.setToolTip(
            "Maximum random rotation angle for slideshow images\n"
            "(0-360°)"
        )

        # Overlap percentage setting
        self.overlap_percent_spinbox = StepSpinBox()
        self.overlap_percent_spinbox.setRange(0, 200)  # 0% to 200% overlap
        self.overlap_percent_spinbox.setSingleStep(10)  # 10% increments
        self.overlap_percent_spinbox.setSuffix("%")
        self.overlap_percent_spinbox.setToolTip(
            "Overlap percentage between slide transitions (0% = no\n"
            "overlap, 100% = perfect overlap, 200% = incoming starts\n"
            "early)"
        )

        # Default direction setting
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(['right', 'left', 'top', 'bottom', 'random', 'none'])
        self.direction_combo.setToolTip("Default direction for slideshow transitions")
        self.direction_combo.setFixedHeight(28)
        self.direction_combo.setFixedWidth(80)
        self.direction_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.direction_combo.setStyleSheet("QComboBox { padding: 2px 8px; font-size: 13px; }")
        
        # -- Remove unused "direction_container" which causes the black block artifact --
        # Use the combo box directly in the grid layout. No need for a seperate container.
        # Size StepSpinBox controls for widest displayed values (suffix included).
        _slideshow_spinbox_samples = (
            (self.slideshow_rate_spinbox, "60000 ms"),
            (self.transition_speed_spinbox, "10000 ms"),
            (self.rotation_angle_spinbox, "360°"),
            (self.overlap_percent_spinbox, "200%"),
        )
        for spinbox, sample_text in _slideshow_spinbox_samples:
            spinbox.setFixedWidth(spinbox.char_width_for_text(sample_text))
            spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 2x3 grid layout
        slideshow_layout.addWidget(QLabel("Slideshow Rate:"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        slideshow_layout.addWidget(self.slideshow_rate_spinbox, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        slideshow_layout.addWidget(QLabel("Rotation angle"), 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        slideshow_layout.addWidget(self.rotation_angle_spinbox, 0, 3, Qt.AlignLeft | Qt.AlignVCenter)

        slideshow_layout.addWidget(QLabel("Transition Speed:"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        slideshow_layout.addWidget(self.transition_speed_spinbox, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        slideshow_layout.addWidget(QLabel("Overlap %"), 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        slideshow_layout.addWidget(self.overlap_percent_spinbox, 1, 3, Qt.AlignLeft | Qt.AlignVCenter)

        slideshow_layout.addWidget(QLabel("Default Direction:"), 2, 0, Qt.AlignRight | Qt.AlignVCenter)
        slideshow_layout.addWidget(self.direction_combo, 2, 1, Qt.AlignLeft | Qt.AlignVCenter)
        slideshow_layout.setColumnStretch(0, 0)
        slideshow_layout.setColumnStretch(1, 0)
        slideshow_layout.setColumnStretch(2, 0)
        slideshow_layout.setColumnStretch(3, 0)

        playback_panel = MacPreferencePanel()
        self.slideshow_back_and_forth_checkbox = playback_panel.add_toggle(
            "Back and forth",
            tooltip="Play through images forward and backward repeatedly.",
        )
        
        # Add performance warning note at the bottom
        warning_label = QLabel(
            "Note:\tThese settings can be changed via the keyboard when the\n"
            "\tslideshow is running.\n\n"
            "\t1 and 2 - Slideshow Rate between transitions\n"
            "\t3 and 4 - Transition Speed\n"
            "\t5 and 6 - Rotation Angle\n"
            "\t7 and 8 - Overlap Percent\n"
            "\t9 and 0 - Slow and fast presets\n\n"
            "\tArrow keys - Advance slide set incoming direction\n"
            "\tC - Set direction to None (fading of transition = 0)\n\n"

            "\tFor fading use direction None and adjust speeds as needed."
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(self.NOTE_TEXT_STYLE)

        layout.addWidget(slideshow_group)
        layout.addWidget(playback_panel)
        layout.addWidget(warning_label)
        layout.addStretch()

    def _cache_tab_show_source_directories(self) -> bool:
        """Source Directories group is debug-only on the Caches tab."""
        if hasattr(self, 'debug_checkbox') and self.debug_checkbox.isChecked():
            return True
        parent_window = self.parent()
        if parent_window is not None and getattr(parent_window, 'debug_mode', False):
            return True
        return bool(get_config().load_settings().get('debug_mode', False))

    def _build_cache_source_directories_group(self) -> QGroupBox:
        """Create the Source Directories group (debug-only)."""
        dirs_group = QGroupBox("Source Directories")
        dirs_layout = QVBoxLayout(dirs_group)

        self.cache_dirs_text = QTextEdit()
        self.cache_dirs_text.setToolTip(
            "Folders whose images are represented in the thumbnail\n"
            "and recognition caches (read-only)."
        )
        self.cache_dirs_text.setReadOnly(True)
        self.cache_dirs_text.setMaximumHeight(100)
        self.cache_dirs_text.setStyleSheet(f"""
            QTextEdit {{
                color: {DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                font-family: Menlo, Monaco;
                font-size: 10pt;
            }}
        """)
        dirs_layout.addWidget(self.cache_dirs_text)

        dirs_info_label = QLabel("Directories from which cached images were loaded.")
        dirs_info_label.setWordWrap(True)
        dirs_info_label.setStyleSheet(f"color: {DIALOG_TEXT_COLOR_HEX}; font-size: 10pt;")
        dirs_layout.addWidget(dirs_info_label)

        return dirs_group

    def _update_cache_source_directories_visibility(self):
        """Build/show or hide Source Directories based on current debug mode."""
        layout = getattr(self, '_cache_management_layout', None)
        controls_group = getattr(self, '_cache_controls_group', None)
        if layout is None or controls_group is None:
            return

        show = self._cache_tab_show_source_directories()
        if show:
            if self._cache_source_dirs_group is None:
                self._cache_source_dirs_group = self._build_cache_source_directories_group()
                insert_at = layout.indexOf(controls_group)
                if insert_at >= 0:
                    layout.insertWidget(insert_at, self._cache_source_dirs_group)
                else:
                    layout.insertWidget(0, self._cache_source_dirs_group)
            self._cache_source_dirs_group.setVisible(True)
            if hasattr(self, 'cache_dirs_text'):
                self.cache_dirs_text.setText("Loading cache directories...")
                QTimer.singleShot(100, self.load_cache_directories_deferred)
        elif self._cache_source_dirs_group is not None:
            self._cache_source_dirs_group.setVisible(False)

        if (
            show
            and getattr(self, 'tab_widget', None)
            and self.tab_widget.currentIndex() == self.tab_widget.indexOf(self.cache_management_tab)
            and not getattr(self, "_settings_dialog_initializing", False)
        ):
            QTimer.singleShot(50, self._adjust_size_and_persist_geometry)

    def _update_background_clip_subordinates_enabled(self) -> None:
        """Enable subordinate background-processing toggles only when parent is on."""
        if not hasattr(self, "background_clip_enabled_checkbox"):
            return
        enabled = self.background_clip_enabled_checkbox.isChecked()
        for attr in (
            "background_clip_gather_thumbnails_container",
            "background_clip_extract_faces_container",
        ):
            container = getattr(self, attr, None)
            if container is not None:
                container.setEnabled(enabled)

    def setup_cache_management_tab(self):
        """Setup the cache management tab"""
        layout = QVBoxLayout(self.cache_management_tab)
        self._cache_management_layout = layout
        self._cache_source_dirs_group = None
        WANT_CACHE_STATS = False
        
        # Cache Statistics group (conditionally shown)
        if WANT_CACHE_STATS:    
            # Cache Statistics group
            stats_group = QGroupBox("Cache Statistics")
            stats_layout = QVBoxLayout(stats_group)
            
            # Cache statistics labels
            self.cache_stats_label = QLabel("Loading cache statistics...")
            self.cache_stats_label.setWordWrap(True)
            # Use 'Menlo' which is the standard monospace font on macOS (fallbacks included)
            self.cache_stats_label.setStyleSheet(f"color: {DIALOG_TEXT_COLOR_HEX}; font-size: 11pt; font-family: Menlo, Monaco;")
            stats_layout.addWidget(self.cache_stats_label)
            
            # Refresh cache stats button
            refresh_stats_button = QPushButton("Refresh Statistics")
            refresh_stats_button.setToolTip("Refresh cache statistics")
            refresh_stats_button.clicked.connect(self.refresh_cache_statistics)
            refresh_stats_button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {BUTTON_BG_DEFAULT_HEX};
                    color: {BUTTON_TEXT_DEFAULT_HEX};
                    border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 10pt;
                }}
                QPushButton:hover {{
                    background-color: {BUTTON_BG_HOVER_HEX};
                    border: 1px solid {BUTTON_BORDER_HOVER_HEX};
                    color: {BUTTON_TEXT_HOVER_HEX};
                }}
                QPushButton:focus {{
                    border: 2px solid {BORDER_HOVER_HEX};
                    outline: none;
                }}
            """)
            stats_layout.addWidget(refresh_stats_button)
            
            layout.addWidget(stats_group)
            
        # Cache Management group
        cache_group = QGroupBox("Cache Controls")
        self._cache_controls_group = cache_group
        cache_layout = QVBoxLayout(cache_group)
        
        # Cache totals label with refresh button (above buttons)
        totals_row_layout = QHBoxLayout()
        totals_row_layout.setContentsMargins(0, 0, 0, 8)
        totals_row_layout.setSpacing(8)
        
        self.cache_totals_label = QLabel("Loading cache sizes...")
        self.cache_totals_label.setWordWrap(True)
        self.cache_totals_label.setStyleSheet(f"color: {DIALOG_TEXT_COLOR_HEX}; font-size: 11pt; font-weight: bold;")
        totals_row_layout.addWidget(self.cache_totals_label, 1)  # Allow label to expand
        
        # Refresh button
        self.refresh_cache_button = QPushButton("↺")
        self.refresh_cache_button.setToolTip("Refresh cache information")
        self.refresh_cache_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.refresh_cache_button.clicked.connect(self.refresh_cache_tab)
        self.refresh_cache_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {DIALOG_TEXT_COLOR_HEX};
                font-size: 18pt;
                padding: 2px 4px;
                min-width: 0px;
            }}
            QPushButton:hover {{
                color: {BUTTON_TEXT_HOVER_HEX};
                background-color: {BUTTON_BG_HOVER_HEX};
                border-radius: 4px;
            }}
            QPushButton:pressed {{
                color: {TEXT_DISABLED_HEX};
            }}
        """)
        self.refresh_cache_button.setCursor(Qt.PointingHandCursor)
        totals_row_layout.addWidget(self.refresh_cache_button, 0)  # Don't expand button
        
        cache_layout.addLayout(totals_row_layout)
        
        # Button row layout
        button_row_layout = QHBoxLayout()
        button_row_layout.setSpacing(6)  # Reduced spacing
        
        button_bg_default = BUTTON_BG_DEFAULT_HEX
        button_text_default = BUTTON_TEXT_DEFAULT_HEX
        button_border_default = BUTTON_BORDER_DEFAULT_HEX
        button_bg_hover = BUTTON_BG_HOVER_HEX
        button_text_hover = BUTTON_TEXT_HOVER_HEX
        button_border_hover = BUTTON_BORDER_HOVER_HEX
        button_bg_pressed = BUTTON_BG_PRESSED_HEX
        focus_bg_hex = BUTTON_BG_HOVER_HEX
        focus_border_hex = BUTTON_BORDER_HOVER_HEX
        focus_text_hex = BUTTON_TEXT_HOVER_HEX
        
        # Button style (shared) - narrower buttons using theme button colors
        button_style = f"""
            QPushButton {{
                background-color: {button_bg_default};
                color: {button_text_default};
                border: 1px solid {button_border_default};
                padding: 6px 1px;
                border-radius: 4px;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background-color: {button_bg_hover};
                color: {button_text_hover};
                border: 1px solid {button_border_hover};
            }}
            QPushButton:focus {{
                background-color: {focus_bg_hex};
                color: {focus_text_hex};
                border: 1px solid {focus_border_hex};
                outline: none;
            }}
            QPushButton:pressed {{
                background-color: {button_bg_pressed};
                color: {focus_text_hex};
            }}
        """
        
        # Clear Thumbnail Cache button
        self.clear_thumbnail_cache_button = QPushButton("Clear Thumbs")
        self.clear_thumbnail_cache_button.setToolTip(
            "Clear only the thumbnail cache.\n"
            "This will force a rebuild of thumbnail images."
        )
        self.clear_thumbnail_cache_button.clicked.connect(self.clear_thumbnail_cache)
        self.clear_thumbnail_cache_button.setStyleSheet(button_style)
        self.clear_thumbnail_cache_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button_row_layout.addWidget(self.clear_thumbnail_cache_button)
        
        # Clear Image Recognition Cache button
        self.clear_image_recognition_cache_button = QPushButton("Clear Image Rec")
        self.clear_image_recognition_cache_button.setToolTip(
            "Clear CNN and CLIP feature caches.\n"
            "This will force recalculation of all image recognition\n"
            "features."
        )
        self.clear_image_recognition_cache_button.clicked.connect(self.clear_image_recognition_cache)
        self.clear_image_recognition_cache_button.setStyleSheet(button_style)
        self.clear_image_recognition_cache_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button_row_layout.addWidget(self.clear_image_recognition_cache_button)
        
        # Clear Face Cache button
        self.clear_face_cache_button = QPushButton("Clear Face")
        self.clear_face_cache_button.setToolTip(
            "Clear cached face encodings (for Search by person) and\n"
            "face sample thumbnails (Settings Faces tab)."
        )
        self.clear_face_cache_button.clicked.connect(self.clear_face_cache)
        self.clear_face_cache_button.setStyleSheet(button_style)
        self.clear_face_cache_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button_row_layout.addWidget(self.clear_face_cache_button)
        
        # Scrub caches button
        self.scrub_caches_button = QPushButton("Scrub")
        self.scrub_caches_button.setToolTip(
            "Remove cache entries for images that no longer exist.\n"
            "This will check CNN, CLIP, face, and thumbnail caches."
        )
        self.scrub_caches_button.clicked.connect(self.scrub_caches)
        self.scrub_caches_button.setStyleSheet(button_style)
        self.scrub_caches_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button_row_layout.addWidget(self.scrub_caches_button)
        
        # Add button row to cache layout
        cache_layout.addLayout(button_row_layout)

        # Second row to avoid widening the dialog:
        button_row_layout2 = QHBoxLayout()
        button_row_layout2.setSpacing(6)

        # Clear All Caches button
        self.clear_cache_button = QPushButton("Clear All")
        self.clear_cache_button.setToolTip(
            "Clear all thumbnail, metadata, and full image caches.\n"
            "This will force a rebuild of all cached data."
        )
        self.clear_cache_button.clicked.connect(self.clear_all_caches)
        self.clear_cache_button.setStyleSheet(button_style)
        self.clear_cache_button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        button_row_layout2.addWidget(self.clear_cache_button)

        cache_layout.addLayout(button_row_layout2)
        
        # Cache info label
        cache_info_label = QLabel(
            "This may temporarily slow down the application as caches are rebuilt."
        )
        cache_info_label.setWordWrap(True)
        cache_info_label.setStyleSheet(f"color: {DIALOG_TEXT_COLOR_HEX}; font-size: 11pt;")
        # cache_layout.addWidget(cache_info_label)
        
        layout.addWidget(cache_group)

        bg_title, bg_panel = mac_preference_section("Background Processing")

        self.background_clip_enabled_checkbox = bg_panel.add_toggle(
            "Enable idle search-data collection",
            tooltip=(
                "Analyzes images to populate cache with data needed for\n"
                "similarity and text searches for files in the Favorites\n"
                "and recently used directories.\n"
                "This runs while the application is idle and does not\n"
                "interfere with normal operations, but may cause battery\n"
                "drain."
            ),
            subtitle="Use sparingly",
        )

        gather_row = bg_panel.add_subordinate_toggle(
            "Also gather thumbnails",
            tooltip=(
                "When processing images for CLIP extraction, also\n"
                "generate and cache thumbnails for images that don't\n"
                "have them yet."
            ),
        )
        self.background_clip_gather_thumbnails_checkbox = gather_row.toggle
        self.background_clip_gather_thumbnails_container = gather_row

        extract_row = bg_panel.add_subordinate_toggle(
            "Extract faces",
            tooltip=(
                "When processing images for CLIP/CNN extraction, also\n"
                "extract and cache face encodings for face search."
            ),
        )
        self.background_clip_extract_faces_checkbox = extract_row.toggle
        self.background_clip_extract_faces_container = extract_row

        self.background_clip_enabled_checkbox.toggled.connect(
            lambda _checked: self._update_background_clip_subordinates_enabled()
        )
        self._update_background_clip_subordinates_enabled()

        layout.addWidget(bg_title)
        layout.addWidget(bg_panel)
        layout.addStretch()
        
        # Load initial cache statistics (with error handling) - only if stats are enabled
        if WANT_CACHE_STATS:
            try:
                self.refresh_cache_statistics()
            except Exception as e:
                print(f"Error loading initial cache statistics: {e}")
                self.cache_stats_label.setText("Loading cache statistics...")
                if hasattr(self, 'cache_dirs_text'):
                    self.cache_dirs_text.setText("Loading cache directories...")

        if hasattr(self, 'debug_checkbox'):
            self.debug_checkbox.toggled.connect(
                lambda _checked: self._update_cache_source_directories_visibility()
            )
        self._update_cache_source_directories_visibility()

    def setup_move_destinations_tab(self):
        """Setup the move destinations tab"""
        layout = QVBoxLayout(self.move_destinations_tab)
        
        # Title
        title = QLabel("Destination Keys")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Form layout for input fields
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setVerticalSpacing(8)
        
        # Create 9 input fields
        self.move_destination_input_fields = []
        self.move_destination_validation_labels = []
        self.move_destination_browse_buttons = []
        
        for i in range(1, 10):
            # Create container for input, validation icon, and browse button
            container = QWidget()
            container.setMinimumHeight(28)
            container.setMaximumHeight(28)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            
            # Input field
            input_field = QLineEdit()
            input_field.setPlaceholderText(f"Enter path for destination {i}")
            input_field.setToolTip(
                f"Folder path for move/copy destination {i}\n"
                f"({CMD_SYMBOL}{i} / {OPTION_SYMBOL}{CMD_SYMBOL}{i})."
            )
            input_field.setMinimumHeight(28)
            input_field.textChanged.connect(lambda text, idx=i-1: self.validate_move_destination_path(idx, text))
            self.move_destination_input_fields.append(input_field)
            container_layout.addWidget(input_field)
            
            # Validation label (icon)
            validation_label = QLabel("")
            validation_label.setFixedWidth(20)
            validation_label.setAlignment(Qt.AlignCenter)
            self.move_destination_validation_labels.append(validation_label)
            container_layout.addWidget(validation_label)
            
            # Browse button with "..." label
            browse_button = QPushButton("...")
            browse_button.setToolTip(f"Browse for directory for destination {i}")
            browse_button.setFixedWidth(30)
            browse_button.setFixedHeight(28)
            browse_button.setStyleSheet(self._small_ellipsis_button_style())
            browse_button.clicked.connect(lambda checked, idx=i-1: self.browse_move_destination(idx))
            self.move_destination_browse_buttons.append(browse_button)
            container_layout.addWidget(browse_button)
            
            # Add to form layout
            form_layout.addRow(f"{CMD_SYMBOL}{i} / {OPTION_SYMBOL}{CMD_SYMBOL}{i}:", container)
        
        layout.addLayout(form_layout)
        
        # Destination menu action: none/copy/move
        action_row = QFormLayout()
        self.destination_menu_action_combo = QComboBox()
        self.destination_menu_action_combo.addItems(["None", "Copy", "Move"])
        self.destination_menu_action_combo.setToolTip(
            "None: hide destination menu items and disable keys.\n"
            "Copy: copy files. Move: move files."
        )
        self.destination_menu_action_combo.setMinimumWidth(60)
        self.destination_menu_action_combo.setMaximumWidth(60)
        action_row.setContentsMargins(0,30,0,0)
        action_row.addRow("Destination menu action:", self.destination_menu_action_combo)
        layout.addLayout(action_row)
        
        layout.addStretch()

        # Instructions immediately below input boxes
        description = QLabel(
            f"Press {CMD_SYMBOL}+number to move or copy to these destinations.\n"
            f"Press {OPTION_SYMBOL}+{CMD_SYMBOL}+number to quickly copy to a numbered destination (not undoable)."
        )
        description.setWordWrap(True)
        description.setStyleSheet(self.NOTE_TEXT_STYLE + "margin-top:0px;margin-left:40px;")
        layout.addWidget(description)

    def setup_favorites_tab(self):
        """Setup the favorites tab (similar to move tab but for favorite directories)"""
        layout = QVBoxLayout(self.favorites_tab)
        
        # Title
        title = QLabel("Favorite Directories and Image Files")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Form layout for input fields
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setVerticalSpacing(8)
        
        # Create 9 input fields
        self.favorite_destination_input_fields = []
        self.favorite_destination_validation_labels = []
        self.favorite_destination_browse_buttons = []
        
        for i in range(1, 10):
            # Create container for input, validation icon, and browse button
            container = QWidget()
            container.setMinimumHeight(28)
            container.setMaximumHeight(28)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            
            # Input field
            input_field = QLineEdit()
            input_field.setPlaceholderText(f"Enter path for favorite directory or image file {i} (Ctrl+{i})")
            input_field.setToolTip(
                f"Favorite folder or image file for Ctrl+{i}.\n"
                "Directories open in thumbnail view; image files open\n"
                "in browse view."
            )
            input_field.setMinimumHeight(28)
            input_field.textChanged.connect(lambda text, idx=i-1: self.validate_favorite_destination_path(idx, text))
            self.favorite_destination_input_fields.append(input_field)
            container_layout.addWidget(input_field)
            
            # Validation label (icon)
            validation_label = QLabel("")
            validation_label.setFixedWidth(20)
            validation_label.setAlignment(Qt.AlignCenter)
            self.favorite_destination_validation_labels.append(validation_label)
            container_layout.addWidget(validation_label)
            
            # Browse button with "..." label
            browse_button = QPushButton("...")
            browse_button.setToolTip(
                f"Browse for directory or image file for favorite {i}\n"
                f"(Ctrl+{i})"
            )
            browse_button.setFixedWidth(30)
            browse_button.setFixedHeight(28)
            browse_button.setStyleSheet(self._small_ellipsis_button_style())
            browse_button.clicked.connect(lambda checked, idx=i-1: self.browse_favorite_destination(idx))
            self.favorite_destination_browse_buttons.append(browse_button)
            container_layout.addWidget(browse_button)
            
            # Add to form layout
            form_layout.addRow(f"^{i} :", container)
        
        layout.addLayout(form_layout)
        
        # Instructions immediately below input boxes
        description = QLabel(
            "Select favorite directories or image files that can be accessed\n"
            "via Ctrl+1 through Ctrl+9.\n\n"
            "Directories open in thumbnail view, image files open directly\n"
            "in browse view."
        )
        description.setWordWrap(True)
        description.setStyleSheet(self.NOTE_TEXT_STYLE + "margin-top:8px;")
        layout.addWidget(description)
        
        layout.addStretch()

    def _ensure_faces_tab_loaded(self):
        """Load face recognition and setup Faces tab. Shows loading message, defers blocking load so tab paints first."""
        # Show loading message with graphic to the left of the text
        layout = QVBoxLayout(self.faces_tab)
        hbox = QHBoxLayout()
        hbox.addStretch()

        img_label = QLabel()
        img_label.setPixmap(
            QPixmap(asset_path('beachball.png')).scaledToHeight(50, Qt.SmoothTransformation)
        )
        img_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        img_label.setFixedSize(60, 60)

        # The message will be split into two labels,
        # the first line (yellow, larger), then rest normal
        first_line = QLabel("Loading facial recognition resources...")
        first_line.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        first_line.setWordWrap(False)
        first_line.setStyleSheet(
            self.NOTE_TEXT_STYLE + f"font-size:18px; color: {BUTTON_BORDER_HOVER_HEX}; font-weight:bold;"
        )

        rest_lines = QLabel(
            "\nMay cause a 'beachball' for a short time.\n\n"
            "This load only happens once per session."
        )
        rest_lines.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        rest_lines.setWordWrap(False)
        rest_lines.setStyleSheet(self.NOTE_TEXT_STYLE + "font-size:14px;")

        text_vbox = QVBoxLayout()
        text_vbox.setSpacing(0)
        text_vbox.setContentsMargins(0,0,0,0)
        text_vbox.addWidget(first_line)
        text_vbox.addWidget(rest_lines)

        hbox.addWidget(img_label, 0, Qt.AlignmentFlag.AlignVCenter)
        hbox.addSpacing(14)
        hbox.addLayout(text_vbox)
        hbox.addStretch()
        layout.addSpacing(12)
        layout.addLayout(hbox)
        layout.addStretch()
        QApplication.processEvents()

        # Defer blocking load to next event loop iteration so tab switch + message paint first
        QTimer.singleShot(0, self._do_blocking_faces_load)

    def _do_blocking_faces_load(self):
        """Run blocking face_recognition import and setup. Called after tab has painted."""
        try:
            from faces.face_engine import is_available
            is_available()
        except Exception:
            pass

        self._faces_tab_setup_done = True
        # Remove loading message layout before building real content.
        # Transfer to temp widget so it's removed immediately (deleteLater is deferred).
        old_layout = self.faces_tab.layout()
        if old_layout:
            temp = QWidget()
            temp.setLayout(old_layout)
            temp.deleteLater()
        self.setup_faces_tab()
        QApplication.processEvents()
        QTimer.singleShot(50, self._adjust_size_and_persist_geometry)
        idx = self.tab_widget.currentIndex()
        is_cache_tab = idx == self.tab_widget.indexOf(self.cache_management_tab)
        is_faces_tab = idx == self.tab_widget.indexOf(self.faces_tab)
        hide_reset_row = is_cache_tab or is_faces_tab
        if getattr(self, 'reset_button', None):
            self.reset_button.setVisible(not hide_reset_row)
        if getattr(self, 'option_note', None):
            self.option_note.setVisible(not hide_reset_row)
        if not hide_reset_row:
            self._update_reset_button_text()

    def setup_faces_tab(self):
        """Setup the Faces tab: known people with up to 4 face samples each."""
        layout = QVBoxLayout(self.faces_tab)
        try:
            from faces.face_engine import is_available as face_engine_available
            from faces.known_faces_manager import load as load_faces
        except ImportError:
            face_engine_available = lambda: False
            load_faces = lambda: []

        if not face_engine_available():
            msg = QLabel(
                "Face recognition is not available. Install the optional package:\n\n"
                "  pip install face_recognition\n\n"
                "Then restart the application. The Faces tab and Cache Faces (Cmd+=) will then work."
            )
            msg.setWordWrap(True)
            msg.setStyleSheet(self.NOTE_TEXT_STYLE)
            layout.addWidget(msg)
            return

        self._faces_subjects = []
        try:
            self._faces_subjects.extend(load_faces())
        except Exception:
            pass
        self._faces_subjects_at_load = copy.deepcopy(self._faces_subjects)

        btn_row = QHBoxLayout()
        examine_btn = QPushButton("Examine an image...")
        examine_btn.setToolTip(
            "Detect faces in the current browse image and assign\n"
            "them to people in this list."
        )
        examine_btn.clicked.connect(self._faces_examine_current_image)
        btn_row.addWidget(examine_btn)
        btn_row.addStretch()
        self._faces_jump_combo = QComboBox()
        self._faces_jump_combo.setMinimumWidth(200)
        self._faces_jump_combo.setToolTip("Jump to a person in the list below")
        self._faces_jump_combo.currentIndexChanged.connect(self._on_faces_jump_combo_changed)
        btn_row.addWidget(self._faces_jump_combo)
        layout.addLayout(btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(320)
        self._faces_scroll = scroll
        self._faces_scroll_content = QWidget()
        self._faces_scroll_layout = QVBoxLayout(self._faces_scroll_content)
        self._faces_scroll_layout.setContentsMargins(10, 10, 10, 10)
        self._faces_scroll_layout.setSpacing(8)
        scroll.setWidget(self._faces_scroll_content)
        layout.addWidget(scroll)

        self._faces_thumb_cache = {}  # path -> QPixmap; invalidated on remove/delete
        self._faces_rebuild_cards()
        if self._auto_extract_faces:
            self._auto_extract_faces = False
            QTimer.singleShot(0, self._faces_examine_current_image)

    def request_extract_faces_when_faces_ready(self):
        """When opening on Faces tab (e.g. from Extract faces... context menu), trigger Examine current image once the tab is ready."""
        self._auto_extract_faces = True

    def _faces_rebuild_cards(self):
        """Rebuild all face subject cards from self._faces_subjects."""
        if not hasattr(self, '_faces_scroll_layout'):
            return
        self._faces_card_by_subject_id = {}
        # Clear existing cards (keep layout, remove widget children)
        while self._faces_scroll_layout.count():
            item = self._faces_scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        subjects_sorted = sorted(getattr(self, '_faces_subjects', []), key=lambda s: (s.get("name") or "").lower())
        for subject in subjects_sorted:
            self._faces_add_card(subject)
        self._faces_refresh_jump_combo()

    def refresh_faces_from_disk_if_ready(self):
        """Reload known_faces.json and rebuild Face tab cards (clears in-memory thumb cache)."""
        if not getattr(self, "_faces_tab_setup_done", False):
            return
        if not hasattr(self, "_faces_scroll_layout"):
            return
        try:
            from faces.known_faces_manager import load as load_faces

            self._faces_subjects = []
            self._faces_subjects.extend(load_faces())
        except Exception:
            return
        self._faces_subjects_at_load = copy.deepcopy(self._faces_subjects)
        self._faces_thumb_cache = {}
        self._faces_rebuild_cards()

    def _faces_refresh_jump_combo(self) -> None:
        combo = getattr(self, '_faces_jump_combo', None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Jump to…", "")
        subjects_sorted = sorted(getattr(self, '_faces_subjects', []), key=lambda s: (s.get("name") or "").lower())
        for s in subjects_sorted:
            sid = s.get("id") or ""
            if not sid:
                continue
            combo.addItem((s.get("name") or "").strip() or "(unnamed)", sid)
        combo.blockSignals(False)

    def _faces_update_jump_combo_entry_for_subject(self, subject_id: Optional[str], new_name: str) -> None:
        combo = getattr(self, '_faces_jump_combo', None)
        if combo is None or not subject_id:
            return
        label = (new_name or "").strip() or "(unnamed)"
        for i in range(combo.count()):
            if combo.itemData(i) == subject_id:
                combo.setItemText(i, label)
                break

    def _on_faces_jump_combo_changed(self, index: int) -> None:
        if index <= 0:
            return
        combo = getattr(self, '_faces_jump_combo', None)
        scroll = getattr(self, '_faces_scroll', None)
        if combo is None or scroll is None:
            return
        sid = combo.itemData(index)
        if not sid:
            return
        card = self._faces_card_by_subject_id.get(sid)
        if card is None:
            return
        scroll.ensureWidgetVisible(card, 50, 50)

    def _faces_add_card(self, subject: dict):
        """Append one subject card to the scroll content. subject has id, name, samples."""
        from PySide6.QtCore import QSize
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(f"border: 1px solid {BORDER_DEFAULT_HEX}; border-radius: 4px; padding: 6px;")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)
        # Row 1: name | trash (compact)
        row1 = QHBoxLayout()
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Person name (unique)")
        name_edit.setToolTip(
            "Display name for this person (used in face search and\n"
            "the jump list)."
        )
        name_edit.setText(subject.get("name") or "")
        name_edit.setMinimumWidth(140)
        def _on_name_changed():
            subject["name"] = name_edit.text().strip()
            self._faces_update_jump_combo_entry_for_subject(subject.get("id"), subject["name"])
        name_edit.textChanged.connect(lambda: _on_name_changed())
        row1.addWidget(name_edit)
        samples = subject.get("samples") or []
        # Delete person: trash icon (same style as elsewhere)
        _trash_url = f"url({asset_path('trash_icon.png')})"
        _trash_hover_url = f"url({asset_path('trash_icon_hover.png')})"
        delete_btn = QPushButton()
        delete_btn.setToolTip("Delete person")
        _chrome = self._settings_chrome()
        delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_chrome.control_bg_hex};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 3px;
                padding: 0px 4px 4px 2px;
                min-width: 18px;
                max-width: 18px;
                min-height: 18px;
                max-height: 18px;
                image: {_trash_url};
            }}
            QPushButton:hover {{
                background-color: {TAB_BUTTON_HOVER_BG_HEX};
                border: 1px solid {TAB_BUTTON_HOVER_BG_HEX};
                image: {_trash_hover_url};
            }}
        """)
        def _delete():
            if subject in getattr(self, '_faces_subjects', []):
                cache = getattr(self, '_faces_thumb_cache', None)
                if cache is not None:
                    sid = subject.get("id")
                    from faces.face_sample_cache import embedding_to_face_key
                    for idx, s in enumerate(subject.get("samples") or []):
                        p = s.get("path") or ""
                        fk = embedding_to_face_key(s.get("embedding")) if s.get("embedding") else None
                        cache.pop((p, sid, idx), None)
                        cache.pop((fk, sid, idx), None)
                        cache.pop((f"nopath_{idx}", sid, idx), None)
                self._faces_subjects.remove(subject)
                self._faces_rebuild_cards()
        delete_btn.clicked.connect(_delete)
        row1.addWidget(delete_btn)
        row1.addStretch()
        card_layout.addLayout(row1)
        # Row 2: images in a line, each with trash button underneath
        samples_row = QHBoxLayout()
        for i, sample in enumerate(samples):
            path = sample.get("path") or ""
            sample_embedding = sample.get("embedding") or None
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setContentsMargins(0, 0, 4, 0)
            thumb = QLabel()
            thumb.setFixedSize(96, 96)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet(f"background: {BUTTON_BG_DEFAULT_HEX};")
            from faces.face_sample_cache import embedding_to_face_key
            face_key = embedding_to_face_key(sample_embedding) if sample_embedding else None
            cache = getattr(self, '_faces_thumb_cache', None)
            cache_key = (path or face_key or f"nopath_{i}", subject.get("id"), i)
            thumb_pix = None
            if cache is not None and cache_key in cache:
                thumb_pix = cache[cache_key]
            elif sample_embedding and isinstance(sample_embedding, list):
                try:
                    from faces.face_sample_thumbnail import ensure_face_sample_thumbnail
                    thumb_pix = ensure_face_sample_thumbnail(path, sample_embedding)
                except Exception:
                    thumb_pix = None
            if thumb_pix is not None and not thumb_pix.isNull():
                if cache is not None:
                    cache[cache_key] = thumb_pix
                thumb.setPixmap(thumb_pix)
            else:
                thumb.setText("?")
            col.addWidget(thumb)
            rem_btn = QPushButton()
            rem_btn.setToolTip("Remove sample")
            rem_btn.setFixedSize(24, 24)
            rem_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_chrome.control_bg_hex};
                    border: none;
                    border-radius: 3px;
                    min-width: 24px;
                    max-width: 24px;
                    min-height: 24px;
                    max-height: 24px;
                    image: {_trash_url};
                }}
                QPushButton:hover {{
                    background-color: {TAB_BUTTON_HOVER_BG_HEX};
                    image: {_trash_hover_url};
                }}
            """)
            def _make_rem(sample_idx):
                def _rem(checked=False):
                    sam = subject.get("samples") or []
                    removed = sam[sample_idx] if sample_idx < len(sam) else None
                    removed_path = removed.get("path") or "" if removed else ""
                    removed_fk = None
                    if removed and removed.get("embedding"):
                        from faces.face_sample_cache import embedding_to_face_key
                        removed_fk = embedding_to_face_key(removed.get("embedding"))
                    subject["samples"] = sam[:sample_idx] + sam[sample_idx + 1:]
                    cache = getattr(self, '_faces_thumb_cache', None)
                    if cache is not None:
                        sid = subject.get("id")
                        cache.pop((removed_path, sid, sample_idx), None)
                        cache.pop((removed_fk, sid, sample_idx), None)
                        cache.pop((f"nopath_{sample_idx}", sid, sample_idx), None)
                    if not (subject.get("samples") or []):
                        if subject in getattr(self, '_faces_subjects', []):
                            self._faces_subjects.remove(subject)
                    self._faces_rebuild_cards()
                return _rem
            rem_btn.clicked.connect(_make_rem(i))
            col.addWidget(rem_btn, 0, Qt.AlignRight)
            col_w = QWidget()
            col_w.setLayout(col)
            samples_row.addWidget(col_w)
        samples_row.addStretch()
        card_layout.addLayout(samples_row)
        self._faces_scroll_layout.addWidget(card)
        sid = subject.get("id") or ""
        if sid:
            self._faces_card_by_subject_id[sid] = card

    def _faces_examine_current_image(self):
        """Examine the current image for faces (as if Add person + selected current image)."""
        if getattr(self, '_face_assign_dialog_open', False):
            return
        mw = self.parent()
        path = None
        if mw and hasattr(mw, 'get_current_image_path'):
            path = mw.get_current_image_path()
        if not path or not os.path.exists(path):
            show_styled_information(self, "No image", "No current image to examine. Select an image in the browser first.")
            return
        if not hasattr(self, '_faces_subjects'):
            return
        self._face_assign_dialog_open = True
        try:
            dialog = FaceAssignDialog(self, image_path=path, subjects=self._faces_subjects)
            if not dialog.exec():
                return
        finally:
            self._face_assign_dialog_open = False
        results = dialog.get_result() or []
        if not results:
            return
        import uuid
        from faces.known_faces_manager import MAX_SAMPLES_PER_SUBJECT
        for name, image_path2, embedding in results:
            name_norm = (name or "").strip().lower()
            matched_subject = None
            for s in self._faces_subjects:
                if (s.get("name") or "").strip().lower() == name_norm:
                    matched_subject = s
                    break
            if matched_subject is None:
                matched_subject = {"id": str(uuid.uuid4()), "name": name, "samples": []}
                self._faces_subjects.append(matched_subject)
            matched_subject.setdefault("samples", [])
            if len(matched_subject["samples"]) >= MAX_SAMPLES_PER_SUBJECT:
                continue
            # Skip if we already have a sample from this image (avoid duplicate from re-extracting same photo)
            existing_paths = {s.get("path") for s in matched_subject["samples"] if s.get("path")}
            if image_path2 in existing_paths:
                continue
            if not (matched_subject.get("name") or "").strip():
                matched_subject["name"] = name
            matched_subject["samples"].append({"path": image_path2, "embedding": list(embedding)})
        self._faces_rebuild_cards()
        from faces.known_faces_manager import save as save_faces
        save_faces(self._faces_subjects)
        self._faces_subjects_at_load = copy.deepcopy(self._faces_subjects)

    def setup_exclude_destinations_tab(self):
        """Setup the exclude destinations tab (similar to favorites tab but with checkboxes)"""
        layout = QVBoxLayout(self.exclude_destinations_tab)
        
        # Title
        title = QLabel("Exclude Directories")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Form layout for input fields
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setVerticalSpacing(8)
        
        # Create 9 input fields with checkboxes
        self.exclude_destination_input_fields = []
        self.exclude_destination_checkboxes = []
        self.exclude_destination_browse_buttons = []
        
        for i in range(1, 10):
            # Create container for checkbox, input, and browse button
            container = QWidget()
            container.setMinimumHeight(28)
            container.setMaximumHeight(28)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(8)
            
            # Checkbox in its own clipping container to prevent row layout issues
            checkbox_container = QWidget()
            checkbox_container.setFixedSize(20, 28)  # Fixed size that clips overflow
            # Qt automatically clips content that exceeds fixed size bounds, no stylesheet needed
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setSpacing(0)
            
            checkbox = QCheckBox()
            checkbox.setToolTip("Enable this exclude rule when pressing Cmd-X")
            self.exclude_destination_checkboxes.append(checkbox)
            checkbox_layout.addWidget(checkbox)
            
            container_layout.addWidget(checkbox_container)
            
            # Input field
            input_field = QLineEdit()
            input_field.setPlaceholderText(f"Enter string to exclude")
            input_field.setToolTip(
                "Path substring or folder name to exclude from thumbnail\n"
                "view (Cmd-X).\n"
                "Use Browse to pick a directory."
            )
            input_field.setMinimumHeight(28)
            self.exclude_destination_input_fields.append(input_field)
            container_layout.addWidget(input_field)
            
            # Browse button with "..." label
            browse_button = QPushButton("...")
            browse_button.setToolTip(f"Browse for directory")
            browse_button.setFixedWidth(30)
            browse_button.setFixedHeight(28)
            browse_button.setStyleSheet(self._small_ellipsis_button_style())
            browse_button.clicked.connect(lambda checked, idx=i-1: self.browse_exclude_destination(idx))
            self.exclude_destination_browse_buttons.append(browse_button)
            container_layout.addWidget(browse_button)
            
            # Add to form layout with empty label to match label column width
            form_layout.addRow("", container)
        
        layout.addLayout(form_layout)
        
        # Instructions immediately below input boxes
        description = QLabel(
            "Used to exclude files in specific directories from the thumbnail view when pressing Cmd-X."
        )
        description.setWordWrap(True)
        description.setStyleSheet(self.NOTE_TEXT_STYLE + "margin-top:8px;")
        layout.addWidget(description)
        
        layout.addStretch()

    def setup_root_directories_tab(self):
        """Setup the root directories tab (macOS Preferences pane style)."""

        import os

        _excluded_directories = {
            '.nofollow', '.resolve', '.vol', '.Trashes', '.fseventsd', 'cores',
            '.Spotlight-V100', '.DocumentRevisions-V100', '.MobileBackups',
            '.PKInstallSandboxManager-SystemSoftware', '.file', '.vol'
        }

        tab_layout = QVBoxLayout(self.directories_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 12, 20, 20)
        layout.setSpacing(18)

        try:
            root_dir = "/"
            all_entries = os.listdir(root_dir)
            actual_dirs = [
                entry for entry in all_entries
                if os.path.isdir(os.path.join(root_dir, entry)) and entry not in _excluded_directories
            ]
            all_directories = sorted(actual_dirs)
        except Exception as e:
            print(f"Failed to list root directories: {e}")
            all_directories = []

        root_title, root_panel = mac_preference_section("Root Directories", inner)
        root_desc = QLabel(
            "Select which root-level directories should be shown in the file tree view."
        )
        root_desc.setObjectName("macPreferenceRowSubtitle")
        root_desc.setWordWrap(True)

        grid_items = [
            (
                directory,
                f"/{directory}",
                f"Show {directory} in the file tree view",
            )
            for directory in all_directories
        ]
        dir_grid, self.directory_checkboxes = build_column_major_toggle_grid(
            grid_items,
            num_cols=3,
            parent=root_panel,
        )
        root_panel.add_custom_row(dir_grid)

        layout.addWidget(root_title)
        layout.addWidget(root_desc)
        layout.addWidget(root_panel)

        options_title, options_panel = mac_preference_section("Scanning Options", inner)

        self.show_hidden_directories_checkbox = options_panel.add_toggle(
            "Process hidden directories",
            tooltip=(
                "Process directories starting with a period (e.g., .git,\n"
                ".vscode) in searches and file operations, not just the\n"
                "file tree."
            ),
            subtitle="Process hidden directories in searches and other operations.",
        )

        self.always_show_work_checkbox = options_panel.add_toggle(
            "Always show directories that start with 'work'",
            tooltip=(
                "Always show directories that start with 'work...' in\n"
                "the file tree, regardless of filter settings.\n"
                "This is intended to provide empty directories when tree\n"
                "filtering requires images."
            ),
            subtitle="Show an empty directories in tree starting with 'work'.",
        )

        self.follow_symlinks_checkbox = options_panel.add_toggle(
            "Follow symlinks",
            tooltip=(
                "Follow symbolic and hard links when scanning\n"
                "directories in the tree view.\n"
                "Disable this to not show the system volumes in the tree\n"
                "view."
            ),
            subtitle="Including system volumes",
        )

        layout.addWidget(options_title)
        layout.addWidget(options_panel)

        depth_title, depth_panel = mac_preference_section("Depth", inner)

        self.shift_cmd_depth_spinbox = QSpinBox()
        self.shift_cmd_depth_spinbox.setRange(1, 10)
        self.shift_cmd_depth_spinbox.setValue(4)
        self.shift_cmd_depth_spinbox.setToolTip(
            "How many levels to expand the file tree when you press\n"
            "Shift+Cmd+Return (1-10).\n"
            "Applies when tree filtering is set to show all entries."
        )
        self.shift_cmd_depth_spinbox.setFixedWidth(72)
        self.shift_cmd_depth_spinbox.setFixedHeight(28)
        depth_panel.add_form_row(
            f"{CMD_SYMBOL}{SHIFT_SYMBOL}{ENTER_SYMBOL} depth",
            self.shift_cmd_depth_spinbox,
            tooltip="The depth of directories to be opened in the\nfile tree when you press Shift+Cmd+Return.",
            subtitle="Tree expansion depth for Shift+Cmd+Return.",
        )

        self.search_depth_spinbox = QSpinBox()
        self.search_depth_spinbox.setRange(1, 10)
        self.search_depth_spinbox.setValue(4)
        self.search_depth_spinbox.setToolTip(
            "Maximum depth for recursive directory scans (1-10).\n"
            "Used by:\n"
            "• Ctrl+= (Cache Faces)\n"
            "• Shift+Cmd+C (cache subdirectories' thumbnails)\n"
            "• Recursive image search and tree \"has images\" checks\n"
            "• Similarity / background indexing over folders"
        )

        self.search_depth_spinbox.setFixedWidth(72)
        self.search_depth_spinbox.setFixedHeight(28)
        depth_panel.add_form_row(
            "Search depth",
            self.search_depth_spinbox,
            tooltip="Maximum depth for recursive directory scans.",
        )

        layout.addWidget(depth_title)
        layout.addWidget(depth_panel)

        files_title, files_panel = mac_preference_section("Image Creation & Temporary Files", inner)
        _default_image_dir = self._path_to_display(os.path.expanduser("~/Downloads"))
        files_note = QLabel(
            "When enabled, newly generated images are saved in the folder below. "
            f"When disabled, images are saved to {_default_image_dir}."
        )
        files_note.setObjectName("macPreferenceRowSubtitle")
        files_note.setWordWrap(True)

        image_path_control = QWidget()
        image_path_layout = QHBoxLayout(image_path_control)
        image_path_layout.setContentsMargins(0, 0, 0, 0)
        image_path_layout.setSpacing(8)
        self.image_creation_directory_checkbox = MacToggleSwitch()
        self.image_creation_directory_checkbox.setToolTip(
            "Use a custom folder for generated images."
        )
        image_path_layout.addWidget(self.image_creation_directory_checkbox)
        self.image_creation_directory_input_field = QLineEdit()
        self.image_creation_directory_input_field.setPlaceholderText(
            "Enter directory for generated images"
        )
        self.image_creation_directory_input_field.setToolTip(
            "Folder for newly generated images when the toggle\n"
            "is enabled.\n"
            f"When disabled, images are saved to {_default_image_dir}."
        )
        self.image_creation_directory_input_field.setMinimumHeight(28)
        image_path_layout.addWidget(self.image_creation_directory_input_field, 1)
        image_creation_browse_button = QPushButton("...")
        image_creation_browse_button.setToolTip("Browse for directory")
        image_creation_browse_button.setFixedWidth(30)
        image_creation_browse_button.setFixedHeight(28)
        image_creation_browse_button.setStyleSheet(self._small_ellipsis_button_style())
        image_creation_browse_button.clicked.connect(self.browse_image_creation_directory)
        image_path_layout.addWidget(image_creation_browse_button)

        files_panel.add_form_row(
            "Generated images folder",
            image_path_control,
            subtitle=f"Default: {_default_image_dir}",
        )

        from prowser_temp_files import default_temporary_files_directory

        _default_temp_dir = self._path_to_display(default_temporary_files_directory())
        temp_files_control = QWidget()
        temp_files_layout = QHBoxLayout(temp_files_control)
        temp_files_layout.setContentsMargins(0, 0, 0, 0)
        temp_files_layout.setSpacing(8)
        self.temporary_files_directory_input_field = QLineEdit()
        self.temporary_files_directory_input_field.setPlaceholderText(
            f"Default: {_default_temp_dir}"
        )
        self.temporary_files_directory_input_field.setToolTip(
            "Folder for temporary work files (infill, masking, image\n"
            "generation, wallpaper).\n"
            f"Leave blank to use the default:\n{_default_temp_dir}"
        )
        self.temporary_files_directory_input_field.setMinimumHeight(28)
        temp_files_layout.addWidget(self.temporary_files_directory_input_field, 1)
        temp_files_browse_button = QPushButton("...")
        temp_files_browse_button.setToolTip("Browse for temporary files directory")
        temp_files_browse_button.setFixedWidth(30)
        temp_files_browse_button.setFixedHeight(28)
        temp_files_browse_button.setStyleSheet(self._small_ellipsis_button_style())
        temp_files_browse_button.clicked.connect(self.browse_temporary_files_directory)
        temp_files_layout.addWidget(temp_files_browse_button)
        files_panel.add_form_row(
            "Temporary files",
            temp_files_control,
            subtitle=(
                "Work files for infill, masking, image generation, wallpaper, and similar "
                f"operations. Leave blank for {_default_temp_dir}"
            ),
        )

        layout.addWidget(files_title)
        layout.addWidget(files_note)
        layout.addWidget(files_panel)

        ignore_title, ignore_panel = mac_preference_section("Ignore Directories", inner)

        self.ignore_directory_input_fields = []
        self.ignore_directory_checkboxes = []
        self.ignore_directory_browse_buttons = []

        for i in range(3):
            ignore_control = QWidget()
            ignore_control_layout = QHBoxLayout(ignore_control)
            ignore_control_layout.setContentsMargins(0, 0, 0, 0)
            ignore_control_layout.setSpacing(8)

            checkbox = MacToggleSwitch()
            checkbox.setToolTip("Enable ignoring for this directory")
            self.ignore_directory_checkboxes.append(checkbox)
            ignore_control_layout.addWidget(checkbox)

            input_field = QLineEdit()
            input_field.setPlaceholderText("Enter directory to ignore")
            input_field.setToolTip(
                "Directory to skip during scans and file operations when\n"
                "the toggle is enabled."
            )
            input_field.setMinimumHeight(28)
            self.ignore_directory_input_fields.append(input_field)
            ignore_control_layout.addWidget(input_field, 1)

            browse_button = QPushButton("...")
            browse_button.setToolTip("Browse for directory")
            browse_button.setFixedWidth(30)
            browse_button.setFixedHeight(28)
            browse_button.setStyleSheet(self._small_ellipsis_button_style())
            browse_button.clicked.connect(lambda checked, idx=i: self.browse_ignore_directory(idx))
            self.ignore_directory_browse_buttons.append(browse_button)
            ignore_control_layout.addWidget(browse_button)

            ignore_panel.add_form_row(f"Ignore path {i + 1}", ignore_control, 
                subtitle=f"Skipped during scans and file operations")

        layout.addWidget(ignore_title)
        layout.addWidget(ignore_panel)

        layout.addStretch()
        scroll.setWidget(inner)
        tab_layout.addWidget(scroll)

    def setup_extensions_tab(self):
        """Setup the extensions tab (macOS Preferences pane style)."""
        from thumbnails.thumbnail_constants import IMAGE_EXTENSIONS

        tab_layout = QVBoxLayout(self.extensions_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 12, 20, 20)
        layout.setSpacing(18)

        all_extensions = sorted(IMAGE_EXTENSIONS)

        ext_title, ext_panel = mac_preference_section("Image File Extensions", inner)
        ext_desc = QLabel(
            "Select which file extensions should be recognized as image files."
        )
        ext_desc.setObjectName("macPreferenceRowSubtitle")
        ext_desc.setWordWrap(True)

        grid_items = [
            (
                extension,
                extension,
                f"Recognize {extension} files as images",
            )
            for extension in all_extensions
        ]
        ext_grid, self.extension_checkboxes = build_column_major_toggle_grid(
            grid_items,
            num_cols=3,
            parent=ext_panel,
        )
        ext_panel.add_custom_row(ext_grid)

        warning_label = QLabel(
            "Adding many extensions may affect performance. "
            "Only enable extensions you need to access."
        )
        warning_label.setObjectName("macPreferenceRowSubtitle")
        warning_label.setWordWrap(True)

        layout.addWidget(ext_title)
        layout.addWidget(ext_desc)
        layout.addWidget(ext_panel)
        layout.addWidget(warning_label)
        layout.addStretch()

        scroll.setWidget(inner)
        tab_layout.addWidget(scroll)

    def setup_map_settings_tab(self):
        """Setup the map settings tab for configuring map application preference"""
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        
        layout = QVBoxLayout(self.map_settings_tab)
        
        # ===== Map Application Group =====
        map_app_group = QGroupBox("Map Application")
        map_app_layout = QVBoxLayout(map_app_group)
        
        # Description
        description = QLabel(f"Choose which map application to use when opening location data from images ({CMD_SYMBOL}+G).")
        description.setWordWrap(True)
        description.setStyleSheet(self.NOTE_TEXT_STYLE)
        map_app_layout.addWidget(description)
        
        # Small radio button style (matching checkbox style from tree tab)
        # small_radio_style = """
        #     QRadioButton::indicator {
        #         width: 12px;
        #         height: 12px;
        #         border: 2px solid #555555;
        #         border-radius: 6px;
        #         margin-right: 10px;
        #         background-color: #2a2a2a;
        #     }
        #     QRadioButton::indicator:checked {
        #         border-color: #5ba0f2;
        #         background-color: #4a90e2;
        #         image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTgiIGhlaWdodD0iMTgiIHZpZXdCb3g9IjAgMCAxOCAxOCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPGNpcmNsZSBjeD0iOSIgY3k9IjkiIHI9IjQiIGZpbGw9IndoaXRlIi8+Cjwvc3ZnPgo=);
        #     }
        #     QRadioButton::indicator:hover {
        #         border-color: #888888;
        #     }
        #     QRadioButton::indicator:focus {
        #         border-color: #aaaaaa;
        #     }g
        # """
        
        # Create radio button group
        self.map_app_group = QButtonGroup()
        margin_padding_style="margin-left: 40px;"
        # Radio buttons for map applications
        self.apple_maps_radio = QRadioButton("Apple Maps")
        self.apple_maps_radio.setToolTip("Use Apple Maps (default)")
        self.apple_maps_radio.setStyleSheet(margin_padding_style)
        # self.apple_maps_radio.setStyleSheet(small_radio_style)
        self.map_app_group.addButton(self.apple_maps_radio, 0)
        
        self.google_maps_radio = QRadioButton("Google Maps")
        self.google_maps_radio.setToolTip("Use Google Maps in web browser")
        self.google_maps_radio.setStyleSheet(margin_padding_style)
        # self.google_maps_radio.setStyleSheet(small_radio_style)
        self.map_app_group.addButton(self.google_maps_radio, 1)
        
        self.google_earth_radio = QRadioButton("Google Earth")
        self.google_earth_radio.setToolTip("Use Google Earth application")
        self.google_earth_radio.setStyleSheet(margin_padding_style)
        # self.google_earth_radio.setStyleSheet(small_radio_style)
        self.map_app_group.addButton(self.google_earth_radio, 2)
        
        # Add radio buttons to layout
        radio_layout = QVBoxLayout()
        radio_layout.setSpacing(15)
        radio_layout.addWidget(self.apple_maps_radio)
        radio_layout.addWidget(self.google_maps_radio)
        radio_layout.addWidget(self.google_earth_radio)
        
        # Container for radio buttons
        radio_container = QWidget()
        radio_container.setLayout(radio_layout)
        map_app_layout.addWidget(radio_container)

        # Note
        note_label = QLabel("Note:\tIf your map application starts in fullscreen, you may\n\tneed to manually switch to it.")
        note_label.setWordWrap(True)
        note_label.setStyleSheet(self.NOTE_TEXT_STYLE)
        map_app_layout.addWidget(note_label)
        
        layout.addWidget(map_app_group)
        
        # ===== Image Editor Group =====
        editor_group = QGroupBox("Image Editor")
        editor_group_layout = QVBoxLayout(editor_group)
        
        # Description for editor
        editor_description = QLabel(f"Choose which image editor to use when editing images ({CMD_SYMBOL}+E).")
        editor_description.setWordWrap(True)
        editor_description.setStyleSheet(self.NOTE_TEXT_STYLE)
        editor_group_layout.addWidget(editor_description)
        
        # Editor selection UI
        editor_layout = QHBoxLayout()
        editor_layout.setContentsMargins(40, 10, 40, 10)
        
        # Label showing current selection
        self.editor_selection_label = QLabel("Preview")
        self.editor_selection_label.setStyleSheet("padding: 5px;")
        editor_layout.addWidget(self.editor_selection_label)
        
        # Button to select editor
        self.select_editor_button = QPushButton("Select Editor...")
        self.select_editor_button.setToolTip(
            f"Choose which application opens when you edit an image\n"
            f"({CMD_SYMBOL}+E)."
        )
        self.select_editor_button.clicked.connect(self._select_image_editor)
        editor_layout.addWidget(self.select_editor_button)
        
        editor_container = QWidget()
        editor_container.setLayout(editor_layout)
        editor_group_layout.addWidget(editor_container)
        
        layout.addWidget(editor_group)
        layout.addStretch()

    def setup_similarity_settings_tab(self):
        """Setup the similarity settings tab"""
        layout = QVBoxLayout(self.similarity_settings_tab)
        
        # Similarity Settings group
        similarity_group = QGroupBox("Image Similarity Settings")
        similarity_layout = QFormLayout(similarity_group)
        similarity_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        # Similarity metric setting
        self.similarity_metric_combo = QComboBox()
        self.similarity_metric_combo.addItems(["Cosine", "Euclidean", "Manhattan"])
        self.similarity_metric_combo.setToolTip(
            "Similarity metric for image similarity sorting:\n"
            "Cosine: Measures angle between feature vectors\n"
            "(default, good for normalized features)\n"
            "Euclidean: Measures straight-line distance between\n"
            "vectors\n"
            "Manhattan: Measures sum of absolute differences (L1\n"
            "distance)"
        )
        self.similarity_metric_combo.setFixedHeight(28)
        self.similarity_metric_combo.setMinimumWidth(0)
        self.similarity_metric_combo.setMaximumWidth(180)
        self.similarity_metric_combo.setStyleSheet("QComboBox {font-size: 12px; }")
        self.similarity_metric_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        similarity_layout.addRow("Similarity Metric:", self.similarity_metric_combo)
        
        # ResNet Model Selection
        resnet_model_label = QLabel("ResNet Model:")
        resnet_model_layout = QVBoxLayout()
        resnet_model_layout.setSpacing(10)
        
        # Create button group for radio buttons
        self.resnet_model_button_group = QButtonGroup()
        
        # ResNet18 radio button
        self.resnet_model_18_radio = QRadioButton("ResNet18 (fastest)")
        self.resnet_model_18_radio.setToolTip(
            "Smallest model, fastest processing, good quality"
        )
        self.resnet_model_button_group.addButton(self.resnet_model_18_radio, 0)
        resnet_model_layout.addWidget(self.resnet_model_18_radio)
        
        # ResNet50 radio button
        self.resnet_model_50_radio = QRadioButton("ResNet50 (balanced)")
        self.resnet_model_50_radio.setToolTip(
            "Medium model, balanced speed and quality"
        )
        self.resnet_model_button_group.addButton(self.resnet_model_50_radio, 1)
        resnet_model_layout.addWidget(self.resnet_model_50_radio)
        
        # ResNet101 radio button
        self.resnet_model_101_radio = QRadioButton("ResNet101 (best quality)")
        self.resnet_model_101_radio.setToolTip(
            "Largest model, slower processing, best quality"
        )
        self.resnet_model_button_group.addButton(self.resnet_model_101_radio, 2)
        resnet_model_layout.addWidget(self.resnet_model_101_radio)
        
        similarity_layout.addRow(resnet_model_label, resnet_model_layout)
        
        layout.addWidget(similarity_group)
        
        # CLIP Model Selection group
        clip_model_group = QGroupBox("Search by Text Settings")
        clip_model_layout = QVBoxLayout(clip_model_group)
        clip_model_layout.setSpacing(20)
        
        # Create button group for radio buttons
        self.clip_model_button_group = QButtonGroup()
        
        # OpenAI model radio button
        self.clip_model_openai_radio = QRadioButton("openai/clip-vit-base-patch32\nSmaller model, faster processing, good quality")
        self.clip_model_openai_radio.setToolTip(
            "Smaller model, faster processing, good quality"
        )
        self.clip_model_button_group.addButton(self.clip_model_openai_radio, 0)
        clip_model_layout.addWidget(self.clip_model_openai_radio)
        
        # Zer0int model radio button
        self.clip_model_zer0int_radio = QRadioButton("openai/clip-vit-large-patch14\nSlower feature extraction, better quality")
        self.clip_model_zer0int_radio.setToolTip(
            "Larger model, much slower feature extraction,\n"
            "Significantly better quality"
        )
        self.clip_model_button_group.addButton(self.clip_model_zer0int_radio, 1)
        clip_model_layout.addWidget(self.clip_model_zer0int_radio)
        advice_label = QLabel(
            "Note:\tThe larger model is significantly slower to scan new images,\n"
            "\tbut subsequent uses run quickly."
        )
        advice_label.setWordWrap(True)
        advice_label.setStyleSheet(self.NOTE_TEXT_STYLE)
        clip_model_layout.addWidget(advice_label)
        
        layout.addWidget(clip_model_group)
        layout.addStretch()

    def setup_captioning_settings_tab(self):
        """Setup the AI captioning (LMStudio) settings tab"""
        from config import CAPTION_DEFAULTS

        layout = QVBoxLayout(self.captioning_settings_tab)

        default_system = CAPTION_DEFAULTS['caption_system_prompt']
        default_user = CAPTION_DEFAULTS['caption_user_prompt']
        default_max_words = CAPTION_DEFAULTS['caption_max_words']
        default_temp = CAPTION_DEFAULTS['caption_temperature']
        default_lms_host = CAPTION_DEFAULTS['caption_lms_host']

        caption_group = QGroupBox("AI Captioning (LMStudio)")
        caption_layout = QFormLayout(caption_group)
        caption_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.caption_lms_host_edit = QLineEdit()
        self.caption_lms_host_edit.setText(default_lms_host)
        self.caption_lms_host_edit.setPlaceholderText("localhost:1234")
        self.caption_lms_host_edit.setToolTip(
            "LMStudio API host and port (e.g. localhost:1234)"
        )
        self.caption_lms_host_edit.setMinimumWidth(180)
        caption_layout.addRow("LMS host:", self.caption_lms_host_edit)

        self.caption_system_prompt_edit = QTextEdit()
        self.caption_system_prompt_edit.setPlainText(default_system)
        self.caption_system_prompt_edit.setPlaceholderText("System prompt for the vision model…")
        self.caption_system_prompt_edit.setMinimumHeight(120)
        self.caption_system_prompt_edit.setToolTip(
            "System prompt sent to the model.\n"
            "Use {CAPTION_WORD_COUNT} for the max word count."
        )
        caption_layout.addRow("System prompt:", self.caption_system_prompt_edit)

        self.caption_user_prompt_edit = QTextEdit()
        self.caption_user_prompt_edit.setPlainText(default_user)
        self.caption_user_prompt_edit.setPlaceholderText("User prompt for the vision model…")
        self.caption_user_prompt_edit.setMinimumHeight(120)
        self.caption_user_prompt_edit.setToolTip(
            "User prompt sent with the image.\n"
            "Use {CAPTION_WORD_COUNT} for the max word count."
        )
        caption_layout.addRow("User prompt:", self.caption_user_prompt_edit)

        self.caption_max_words_spinbox = QSpinBox()
        self.caption_max_words_spinbox.setRange(10, 2000)
        self.caption_max_words_spinbox.setValue(default_max_words)
        self.caption_max_words_spinbox.setToolTip(
            "Target word count for the caption (used in prompts)"
        )
        self.caption_max_words_spinbox.setMinimumWidth(100)
        caption_layout.addRow("Caption max words:", self.caption_max_words_spinbox)

        self.caption_temperature_spinbox = QDoubleSpinBox()
        self.caption_temperature_spinbox.setRange(0.0, 3.0)
        self.caption_temperature_spinbox.setSingleStep(0.1)
        self.caption_temperature_spinbox.setValue(default_temp)
        self.caption_temperature_spinbox.setToolTip(
            "Model temperature (0=deterministic, higher=more\n"
            "creative)"
        )
        self.caption_temperature_spinbox.setMinimumWidth(100)
        self.caption_temperature_spinbox.setDecimals(1)
        caption_layout.addRow("Temperature (0–3):", self.caption_temperature_spinbox)

        layout.addWidget(caption_group)
        layout.addStretch()

    def _lora_add_button_style(self) -> str:
        _plus_url = f"url({asset_path('series_plus_icon.png')})"
        _plus_hover_url = f"url({asset_path('series_plus_icon_hover.png')})"
        c = self._settings_chrome()
        return f"""
            QPushButton#loraAddDownloadedButton {{
                background-color: {c.control_bg_hex};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 5px;
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                image: {_plus_url};
            }}
            QPushButton#loraAddDownloadedButton:focus {{
                border: 1px solid {CURRENT_IMAGE_BORDER_COLOR_HEX};
                outline: none;
            }}
            QPushButton#loraAddDownloadedButton:hover {{
                background-color: {TAB_BUTTON_HOVER_BG_HEX};
                border: 1px solid {TAB_BUTTON_HOVER_BG_HEX};
                image: {_plus_hover_url};
            }}
            QPushButton#loraAddDownloadedButton:pressed {{
                background-color: {SIDEBAR_SPLITTER_HANDLE_HEX};
            }}
        """

    def _lora_trash_button_style(self) -> str:
        _trash_url = f"url({asset_path('trash_icon.png')})"
        _trash_hover_url = f"url({asset_path('trash_icon_hover.png')})"
        c = self._settings_chrome()
        return f"""
            QPushButton {{
                background-color: {c.control_bg_hex};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 3px;
                padding: 0px 4px 4px 2px;
                min-width: 18px;
                max-width: 18px;
                min-height: 18px;
                max-height: 18px;
                image: {_trash_url};
            }}
            QPushButton:focus {{
                border: 1px solid {CURRENT_IMAGE_BORDER_COLOR_HEX};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {TAB_BUTTON_HOVER_BG_HEX};
                border: 1px solid {TAB_BUTTON_HOVER_BG_HEX};
                image: {_trash_hover_url};
            }}
            QPushButton:pressed {{
                background-color: {SIDEBAR_SPLITTER_HANDLE_HEX};
            }}
        """

    def _lora_edit_button_style(self) -> str:
        _edit_url = f"url({asset_path('edit_icon.png')})"
        _edit_hover_url = f"url({asset_path('edit_icon_hover.png')})"
        c = self._settings_chrome()
        return f"""
            QPushButton {{
                background-color: {c.control_bg_hex};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 3px;
                padding: 0px 4px 4px 2px;
                min-width: 18px;
                max-width: 18px;
                min-height: 18px;
                max-height: 18px;
                image: {_edit_url};
            }}
            QPushButton:focus {{
                border: 1px solid {CURRENT_IMAGE_BORDER_COLOR_HEX};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {TAB_BUTTON_HOVER_BG_HEX};
                border: 1px solid {TAB_BUTTON_HOVER_BG_HEX};
                image: {_edit_hover_url};
            }}
            QPushButton:pressed {{
                background-color: {SIDEBAR_SPLITTER_HANDLE_HEX};
            }}
        """

    def _apply_min_bundle_settings_visibility(self) -> None:
        """Hide settings for features omitted from --min PyInstaller bundles."""
        try:
            from bundle_capabilities import imagegen_ui_enabled, faces_ui_enabled
        except ImportError:
            return
        if not imagegen_ui_enabled():
            group = getattr(self, "_imagegen_general_settings_group", None)
            if group is not None:
                group.setVisible(False)
        if not faces_ui_enabled():
            if hasattr(self, "clear_face_cache_button"):
                self.clear_face_cache_button.setVisible(False)
            container = getattr(self, "background_clip_extract_faces_container", None)
            if container is not None:
                container.setVisible(False)

    def setup_lora_settings_tab(self):
        """LoRA catalog tab: per base model dropdown, enable / install / delete."""
        from config import get_config
        from imagegen_plugins.hf_model_ids import FLUX1_DEV
        from imagegen_plugins.lora_model_registry import lora_models_for_settings

        layout = QVBoxLayout(self.lora_settings_tab)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        model_grid = QGridLayout()
        model_grid.setHorizontalSpacing(8)
        model_grid.setVerticalSpacing(2)
        model_lbl = QLabel("Model:")
        model_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        model_grid.addWidget(model_lbl, 0, 0, Qt.AlignmentFlag.AlignTop)
        self._lora_model_combo = QComboBox()
        self._lora_model_combo.setObjectName("loraSettingsModelCombo")
        self._lora_model_combo.setToolTip(
            "Base image generation model whose LoRA adapters are\n"
            "listed below."
        )
        self._lora_model_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._lora_model_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._lora_model_combo.setMinimumContentsLength(36)
        # Global theme caps QComboBox at 160px; fill the row after "Model:".
        self._lora_model_combo.setMaximumWidth(4096)
        self._lora_model_combo.setStyleSheet(
            "QComboBox#loraSettingsModelCombo { max-width: 4096px; }"
        )
        for model in lora_models_for_settings():
            self._lora_model_combo.addItem(model.display_name, model.model_key)
        model_grid.addWidget(self._lora_model_combo, 0, 1)
        self._lora_available_in_label = QLabel()
        self._lora_available_in_label.setWordWrap(True)
        self._lora_available_in_label.setStyleSheet(self.NOTE_TEXT_STYLE)
        model_grid.addWidget(self._lora_available_in_label, 1, 1)
        model_grid.setColumnStretch(1, 1)
        layout.addLayout(model_grid)

        self._lora_intro_label = QLabel()
        self._lora_intro_label.setWordWrap(True)
        self._lora_intro_label.setStyleSheet(self.NOTE_TEXT_STYLE)
        layout.addWidget(self._lora_intro_label)

        cfg_settings = get_config().load_settings()
        self._lora_model_key: str = FLUX1_DEV
        self._lora_catalog_loaded = False
        self._lora_checkboxes: dict = {}
        self._lora_row_widgets: dict = {}
        self._lora_draft_by_model: dict = {}
        self._lora_syncing_checkboxes = False

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._lora_rows_host = QWidget()
        self._lora_rows_host.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._lora_rows_layout = QVBoxLayout(self._lora_rows_host)
        self._lora_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._lora_rows_layout.setSpacing(8)
        self._lora_rows_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        scroll.setWidget(self._lora_rows_host)
        layout.addWidget(scroll, 1)

        self._lora_model_combo.currentIndexChanged.connect(self._on_lora_model_combo_changed)
        self._load_lora_drafts_from_settings(cfg_settings)
        initial_model_key = self._resolve_lora_model_key(cfg_settings)
        idx = self._lora_model_combo.findData(initial_model_key)
        if idx >= 0:
            self._lora_model_combo.blockSignals(True)
            self._lora_model_combo.setCurrentIndex(idx)
            self._lora_model_combo.blockSignals(False)
        self._show_lora_draft_for_model(initial_model_key)
        self._lora_catalog_loaded = True

    def _ensure_lora_tab_ready(self) -> None:
        """Load LoRA drafts from disk once (parent-window path may skip dialog load_settings)."""
        if getattr(self, "_lora_catalog_loaded", False):
            return
        if not hasattr(self, "_lora_checkboxes"):
            return
        from config import get_config

        self._load_lora_settings(get_config().load_settings())

    def _current_lora_model_key(self) -> str:
        if hasattr(self, "_lora_model_combo"):
            mk = self._lora_model_combo.currentData()
            if mk:
                return str(mk)
        from imagegen_plugins.hf_model_ids import FLUX1_DEV
        return getattr(self, "_lora_model_key", FLUX1_DEV)

    def _update_lora_available_in_text(self) -> None:
        if not hasattr(self, "_lora_available_in_label"):
            return
        from imagegen_plugins.lora_model_registry import lora_model_available_in_label

        text = lora_model_available_in_label(self._current_lora_model_key())
        self._lora_available_in_label.setText(text)
        self._lora_available_in_label.setVisible(bool(text))

    def _update_lora_intro_text(self) -> None:
        if not hasattr(self, "_lora_intro_label"):
            return
        from imagegen_plugins.lora_model_registry import lora_settings_model

        model_key = self._current_lora_model_key()
        model = lora_settings_model(model_key)
        self._update_lora_available_in_text()
        if model is None:
            self._lora_intro_label.setText("")
            return
        text = (
            f"LoRAs listed here are valid for {model.display_name} only. "
            "Only LoRAs that passed Check LoRAs for this model are listed (run Tools → Debug → "
            "Check LoRAs if the list is empty). Enable and Install adapters for the generation menu. "
            "The app does not change your selected base model when you pick a LoRA."
        )
        self._lora_intro_label.setText(text)

    def _load_lora_drafts_from_settings(self, settings: Optional[dict] = None) -> None:
        """Load per-model LoRA enable drafts (session source of truth)."""
        from config import get_config
        from imagegen_plugins.lora_catalog_settings import model_state
        from imagegen_plugins.lora_model_registry import LORA_SETTINGS_MODEL_ORDER

        if settings is None:
            settings = get_config().load_settings()
        drafts: dict = {}
        for model_key in LORA_SETTINGS_MODEL_ORDER:
            st = model_state(settings, model_key)
            drafts[model_key] = {
                "enabled_ids": list(st["enabled_ids"]),
                "hidden_ids": [],
            }
        self._lora_draft_by_model = drafts
        self._lora_draft_at_load = self._normalized_lora_drafts(drafts)

    def _normalized_lora_drafts(self, drafts: Optional[dict] = None) -> dict:
        source = drafts if drafts is not None else getattr(self, "_lora_draft_by_model", {})
        if not isinstance(source, dict):
            return {}
        return {
            str(mk): {
                "enabled_ids": sorted((sl or {}).get("enabled_ids") or []),
                "hidden_ids": sorted((sl or {}).get("hidden_ids") or []),
            }
            for mk, sl in source.items()
            if isinstance(sl, dict)
        }

    def _lora_drafts_changed(self) -> bool:
        if not hasattr(self, "_lora_checkboxes"):
            return False
        model_key = getattr(self, "_lora_model_key", None) or self._current_lora_model_key()
        self._save_lora_widgets_to_draft(model_key)
        baseline = getattr(self, "_lora_draft_at_load", None)
        if baseline is None:
            return True
        return self._normalized_lora_drafts() != baseline

    def _lora_draft_slice(self, model_key: str) -> dict:
        draft = getattr(self, "_lora_draft_by_model", {}).get(model_key)
        if isinstance(draft, dict):
            return {
                "enabled_ids": list(draft.get("enabled_ids") or []),
                "hidden_ids": list(draft.get("hidden_ids") or []),
            }
        return {"enabled_ids": [], "hidden_ids": []}

    def _save_lora_widgets_to_draft(self, model_key: str) -> None:
        if not model_key:
            return
        if not hasattr(self, "_lora_draft_by_model"):
            self._lora_draft_by_model = {}
        self._lora_draft_by_model[model_key] = {
            "enabled_ids": self._get_lora_enabled_ids_from_widgets(),
            "hidden_ids": [],
        }

    def _show_lora_draft_for_model(self, model_key: str) -> None:
        """Rebuild grid and checkmarks for one base model from in-memory draft."""
        slice_ = self._lora_draft_slice(model_key)
        self._lora_model_key = model_key
        self._update_lora_intro_text()
        self._rebuild_lora_settings_grid()
        self._apply_lora_settings_to_widgets(slice_["enabled_ids"])

    def _lora_settings_overlay(self, base_settings: dict) -> dict:
        """Merge in-memory LoRA draft for the current base model."""
        from imagegen_plugins.lora_catalog_settings import migrate_lora_catalog

        cfg = dict(base_settings)
        imagegen = dict(cfg.get("imagegen") or {})
        lc = migrate_lora_catalog(dict(imagegen.get("lora_catalog") or {}))
        model_key = self._current_lora_model_key()
        bm = dict(lc.get("by_model") or {})
        slice_ = self._lora_draft_slice(model_key)
        bm[model_key] = slice_
        lc["by_model"] = bm
        imagegen["lora_catalog"] = lc
        cfg["imagegen"] = imagegen
        return cfg

    def _flush_lora_tab_to_disk(self) -> bool:
        """Write per-model LoRA drafts to settings.json when they changed."""
        if not hasattr(self, "_lora_checkboxes"):
            return False
        self._ensure_lora_tab_ready()
        model_key = getattr(self, "_lora_model_key", None) or self._current_lora_model_key()
        self._save_lora_widgets_to_draft(model_key)
        return self._persist_all_lora_drafts_to_disk()

    def _persist_all_lora_drafts_to_disk(self) -> bool:
        from config import get_config
        from imagegen_plugins.image_gen_persistence import save_lora_catalog_state

        if not self._lora_drafts_changed():
            return False
        drafts = getattr(self, "_lora_draft_by_model", None)
        if not isinstance(drafts, dict) or not drafts:
            return False
        save_lora_catalog_state(
            by_model={
                str(mk): {
                    "enabled_ids": list((sl or {}).get("enabled_ids") or []),
                    "hidden_ids": [],
                }
                for mk, sl in drafts.items()
                if isinstance(sl, dict)
            }
        )
        get_config().update_settings(
            {"imagegen_lora_model_key": self._current_lora_model_key()}
        )
        self._lora_draft_at_load = self._normalized_lora_drafts(drafts)
        return True

    def _on_lora_model_combo_changed(self, _index: int = 0) -> None:
        self._ensure_lora_tab_ready()
        previous_model_key = getattr(self, "_lora_model_key", None)
        new_model_key = self._current_lora_model_key()
        if previous_model_key and previous_model_key != new_model_key:
            self._save_lora_widgets_to_draft(previous_model_key)

        if new_model_key:
            self._show_lora_draft_for_model(new_model_key)
        self._persist_session_lora_model_key()

    def _install_lora_catalog_entry(self, lora_id: str) -> None:
        from PySide6.QtCore import QThread, Signal
        from PySide6.QtWidgets import QApplication

        from imagegen_plugins.mflux_lora_presets import resolve_lora_path

        progress = QProgressDialog("Downloading LoRA weights…", "Cancel", 0, 0, self)
        progress.setWindowTitle("Install LoRA")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        cancel_flag = [False]
        progress.canceled.connect(lambda: cancel_flag.__setitem__(0, True))

        class InstallWorker(QThread):
            finished_ok = Signal(bool, str)

            def run(self) -> None:
                if cancel_flag[0]:
                    self.finished_ok.emit(False, "Cancelled")
                    return
                try:
                    resolve_lora_path(lora_id)
                    self.finished_ok.emit(True, "")
                except Exception as e:
                    self.finished_ok.emit(False, str(e))

        worker = InstallWorker(self)

        def on_done(ok: bool, err: str) -> None:
            progress.close()
            if ok:
                self._rebuild_lora_settings_grid()
                self._apply_lora_settings_to_widgets(
                    self._get_lora_enabled_ids_from_widgets()
                )
            elif err and err != "Cancelled":
                show_styled_warning(self, "Install LoRA", err)

        worker.finished_ok.connect(on_done)
        worker.start()

    def _open_add_downloaded_lora_dialog(self) -> None:
        from imagegen_plugins.lora_import_dialog import run_add_downloaded_lora_dialog

        self._ensure_lora_tab_ready()
        model_key = self._current_lora_model_key()
        if run_add_downloaded_lora_dialog(self, model_key=model_key):
            self._reload_lora_drafts_and_grid()
            mw = self.parent()
            if mw is not None and hasattr(mw, "refresh_open_imagegen_lora_combos"):
                mw.refresh_open_imagegen_lora_combos()

    def _open_edit_lora_dialog(self, lora_id: str) -> None:
        from imagegen_plugins.lora_import_dialog import run_edit_lora_dialog

        self._ensure_lora_tab_ready()
        model_key = self._current_lora_model_key()
        if run_edit_lora_dialog(self, lora_id=lora_id, model_key=model_key):
            self._reload_lora_drafts_and_grid()
            mw = self.parent()
            if mw is not None and hasattr(mw, "refresh_open_imagegen_lora_combos"):
                mw.refresh_open_imagegen_lora_combos()

    def _reload_lora_drafts_and_grid(self) -> None:
        from config import get_config

        self._load_lora_drafts_from_settings(get_config().load_settings())
        self._show_lora_draft_for_model(self._current_lora_model_key())

    def _delete_lora_catalog_entry(self, lora_id: str) -> None:
        """Delete downloaded LoRA weights from disk (with confirmation)."""
        from imagegen_plugins.hf_model_ids import lora_model_display_name
        from imagegen_plugins.lora_catalog import (
            delete_installed_lora_files,
            get_lora_entry,
            lora_disk_delete_allowed,
            lora_shared_model_labels,
        )
        from imagegen_plugins.lora_user_entries import is_user_lora_id

        entry = get_lora_entry(lora_id)
        if entry is None:
            return

        label = entry.display_name
        model_key = self._current_lora_model_key()
        model_label = lora_model_display_name(model_key) if model_key else "this model"
        from config import get_config

        cfg_settings = self._lora_settings_overlay(get_config().load_settings())
        drafts = getattr(self, "_lora_draft_by_model", {}) or {}
        if not lora_disk_delete_allowed(entry, cfg_settings, draft_by_model=drafts):
            show_styled_warning(
                self,
                "Delete LoRA",
                f"«{label}» is shared by multiple base models and is still enabled on at least "
                "one of them. Disable it on every model that uses this file before deleting.",
            )
            return

        shared = lora_shared_model_labels(entry, cfg_settings)
        shared_note = ""
        if shared:
            shared_note = (
                "\n\nThis file is shared by: "
                + ", ".join(shared)
                + ". Deleting removes it for all of them."
            )

        if is_user_lora_id(lora_id):
            message = (
                f"Delete imported LoRA «{label}» from disk and remove it from settings?\n\n"
                f"This affects {model_label}.{shared_note}"
            )
            title = "Delete LoRA"
        else:
            message = (
                f"Delete downloaded weights for «{label}» from disk?\n\n"
                "You can Install them again later from this screen."
                f"{shared_note}"
            )
            title = "Delete LoRA"

        reply = show_styled_question(
            self,
            title,
            message,
            default_no=True,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if is_user_lora_id(lora_id):
                from imagegen_plugins.image_gen_persistence import remove_user_lora

                remove_user_lora(lora_id)
                self._reload_lora_drafts_and_grid()
            else:
                from imagegen_plugins.image_gen_persistence import (
                    remove_lora_enabled_everywhere,
                )

                delete_installed_lora_files(entry)
                remove_lora_enabled_everywhere(lora_id)
                self._reload_lora_drafts_and_grid()
        except Exception as e:
            show_styled_warning(self, "Delete LoRA", str(e))
            return

        mw = self.parent()
        if mw is not None and hasattr(mw, "refresh_open_imagegen_lora_combos"):
            mw.refresh_open_imagegen_lora_combos()

    def _rebuild_lora_settings_grid(self) -> None:
        """Rebuild LoRA rows for the selected base model."""
        if not hasattr(self, "_lora_rows_layout"):
            return
        from config import get_config
        from imagegen_plugins.lora_catalog import (
            catalog_entries_for_model,
            is_lora_installed,
            lora_choice_label,
            lora_disk_delete_allowed,
        )

        while self._lora_rows_layout.count():
            item = self._lora_rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    while sub.count():
                        sub_item = sub.takeAt(0)
                        sub_widget = sub_item.widget()
                        if sub_widget is not None:
                            sub_widget.deleteLater()
        self._lora_checkboxes = {}
        self._lora_row_widgets = {}
        cfg_settings = self._lora_settings_overlay(get_config().load_settings())
        model_key = self._current_lora_model_key()
        drafts = getattr(self, "_lora_draft_by_model", {}) or {}

        row_count = 0
        for entry in catalog_entries_for_model(cfg_settings, model_key):
            installed = is_lora_installed(entry.lora_id)
            cb = MacToggleSwitch()
            cb.setToolTip(entry.repo_id or entry.local_path or entry.lora_id)
            cb.stateChanged.connect(self._on_lora_checkbox_state_changed)
            self._lora_checkboxes[entry.lora_id] = cb

            name_lbl = QLabel(lora_choice_label(entry, model_key=model_key))
            name_lbl.setToolTip(entry.lora_id)
            if installed:
                font = QFont(name_lbl.font())
                base_pt = font.pointSize()
                if base_pt <= 0:
                    base_pt = 12
                font.setPointSize(base_pt + 1)
                font.setBold(True)
                name_lbl.setFont(font)

            status_parts = [entry.lora_id]
            if entry.repo_id:
                status_parts.append(entry.repo_id)
            if entry.mflux_compatible is True:
                status_parts.append("MFLUX verified")
            elif entry.mflux_compatible is None:
                status_parts.append("untested")
            from imagegen_plugins.lora_user_entries import is_user_lora_id

            if is_user_lora_id(entry.lora_id):
                status_parts.append("imported")
            status_parts.append("installed" if installed else "not installed")
            status_lbl = QLabel(" · ".join(status_parts))
            status_lbl.setStyleSheet(f"color: {TEXT_DISABLED_HEX}; font-size: 11px;")
            status_lbl.setWordWrap(True)

            desc_w = QWidget()
            desc_layout = QVBoxLayout(desc_w)
            desc_layout.setContentsMargins(0, 0, 0, 0)
            desc_layout.setSpacing(2)
            desc_layout.addWidget(name_lbl)
            comment_text = (entry.comment or "").strip()
            if comment_text:
                comment_lbl = QLabel(comment_text)
                comment_lbl.setWordWrap(True)
                comment_lbl.setStyleSheet(self.NOTE_TEXT_STYLE)
                desc_layout.addWidget(comment_lbl)
            desc_layout.addWidget(status_lbl)
            desc_w.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )

            install_btn = None
            if not installed and (entry.repo_id or entry.local_path):
                install_btn = QPushButton("Install")
                install_btn.setToolTip(f"Download {entry.display_name}")
                install_btn.clicked.connect(
                    lambda checked=False, lid=entry.lora_id: self._install_lora_catalog_entry(
                        lid
                    )
                )

            del_btn = None
            if installed and lora_disk_delete_allowed(
                entry, cfg_settings, draft_by_model=drafts
            ):
                del_btn = QPushButton()
                del_btn.setToolTip(
                    f"Delete {lora_choice_label(entry, model_key=model_key)} from disk"
                )
                del_btn.setStyleSheet(self._lora_trash_button_style())
                del_btn.clicked.connect(
                    lambda checked=False, lid=entry.lora_id: self._delete_lora_catalog_entry(
                        lid
                    )
                )

            edit_btn = QPushButton()
            edit_btn.setToolTip(
                f"Edit LoRA details…\n{lora_choice_label(entry, model_key=model_key)}"
            )
            edit_btn.setStyleSheet(self._lora_edit_button_style())
            edit_btn.clicked.connect(
                lambda checked=False, lid=entry.lora_id: self._open_edit_lora_dialog(lid)
            )

            row_w = QWidget()
            row_layout = QHBoxLayout(row_w)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            row_layout.addWidget(desc_w, 1)
            if install_btn is not None:
                row_layout.addWidget(
                    install_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
                )
            row_layout.addWidget(
                edit_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
            if del_btn is not None:
                row_layout.addWidget(
                    del_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
                )
            row_layout.addWidget(
                cb, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
            row_w.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            self._lora_rows_layout.addWidget(row_w)

            row_widgets = [desc_w]
            if install_btn is not None:
                row_widgets.append(install_btn)
            row_widgets.append(edit_btn)
            if del_btn is not None:
                row_widgets.append(del_btn)
            row_widgets.append(cb)
            self._lora_row_widgets[entry.lora_id] = tuple(row_widgets)
            row_count += 1
        if row_count == 0:
            empty = QLabel(
                "No LoRAs passed Check LoRAs for this base model yet. "
                "Run Tools → Debug → Check LoRAs, or pick another model above."
            )
            empty.setStyleSheet(self.NOTE_TEXT_STYLE)
            self._lora_rows_layout.addWidget(empty)
        self._lora_rows_layout.addStretch(1)

    def _on_lora_checkbox_state_changed(self, _state: int = 0) -> None:
        if getattr(self, "_lora_syncing_checkboxes", False):
            return
        model_key = getattr(self, "_lora_model_key", None) or self._current_lora_model_key()
        self._save_lora_widgets_to_draft(model_key)

    def _get_lora_enabled_ids_from_widgets(self) -> List[str]:
        if not hasattr(self, "_lora_checkboxes"):
            return []
        return [lid for lid, cb in self._lora_checkboxes.items() if cb.isChecked()]

    def _apply_lora_settings_to_widgets(self, enabled_ids: List[str]) -> None:
        if not hasattr(self, "_lora_checkboxes"):
            return
        enabled = set(enabled_ids or [])
        self._lora_syncing_checkboxes = True
        try:
            for lora_id, cb in self._lora_checkboxes.items():
                cb.setChecked(lora_id in enabled)
        finally:
            self._lora_syncing_checkboxes = False

    def browse_move_destination(self, index: int):
        """Open directory picker dialog for move destination"""
        # Determine starting directory
        # Use current value if it exists and is valid, otherwise use home directory
        current_path = self.move_destination_input_fields[index].text().strip()
        # Expand ~ to full path for directory picker
        if current_path:
            current_path = self._display_to_path(current_path)
        start_directory = current_path if current_path and os.path.isdir(current_path) else os.path.expanduser("~")
        
        # Open directory picker dialog
        # QFileDialog.getExistingDirectory shows folders only by default on macOS
        directory = QFileDialog.getExistingDirectory(
            self,
            f"Select Directory for Destination {index + 1}",
            start_directory
        )
        
        # Update the input field if a directory was selected (convert to display format)
        if directory:
            display_path = self._path_to_display(directory)
            self.move_destination_input_fields[index].setText(display_path)
            # Validation will be triggered automatically by textChanged signal
    
    def validate_move_destination_path(self, index: int, path: str):
        """Validate a move destination path and update the validation icon"""
        validation_label = self.move_destination_validation_labels[index]
        
        if not path or not path.strip():
            # Empty path - no icon
            validation_label.setText("")
            validation_label.setToolTip("")
            return True
        
        path = path.strip()
        # Expand ~ to full path for validation
        full_path = self._display_to_path(path)
        
        # Check if path exists and is a directory
        if os.path.isdir(full_path):
            # Valid directory - green checkmark
            validation_label.setText("✓")
            validation_label.setStyleSheet(f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-size: 14px; font-weight: bold;")
            validation_label.setToolTip(f"Valid directory:\n{full_path}")
            return True
        else:
            # Invalid path - red X
            validation_label.setText("✗")
            validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-size: 14px; font-weight: bold;")
            if os.path.exists(full_path):
                validation_label.setToolTip(
                    f"Path exists but is not a directory:\n"
                    f"{full_path}"
                )
            else:
                validation_label.setToolTip(f"Path does not exist: {full_path}")
            return False

    def browse_exclude_destination(self, index: int):
        """Open directory picker dialog for exclude destination"""
        # Determine starting directory
        # Use current value if it exists and is valid, otherwise use home directory
        current_path = self.exclude_destination_input_fields[index].text().strip()
        # Expand ~ to full path for directory picker
        if current_path:
            current_path = self._display_to_path(current_path)
        start_directory = current_path if current_path and os.path.isdir(current_path) else os.path.expanduser("~")
        
        # Open directory picker dialog
        # QFileDialog.getExistingDirectory shows folders only by default on macOS
        directory = QFileDialog.getExistingDirectory(
            self,
            f"Select Directory for Exclude {index + 1}",
            start_directory
        )
        
        # Update the input field if a directory was selected (convert to display format)
        if directory:
            display_path = self._path_to_display(directory)
            self.exclude_destination_input_fields[index].setText(display_path)
            # Validation will be triggered automatically by textChanged signal

    def browse_image_creation_directory(self):
        """Open directory picker dialog for image creation directory."""
        current_path = self.image_creation_directory_input_field.text().strip()
        if current_path:
            current_path = self._display_to_path(current_path)
        start_directory = (
            current_path
            if current_path and os.path.isdir(current_path)
            else os.path.expanduser("~/Downloads")
        )
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Image Creation Directory",
            start_directory,
        )
        if directory:
            display_path = self._path_to_display(directory)
            self.image_creation_directory_input_field.setText(display_path)

    def browse_temporary_files_directory(self):
        """Open directory picker dialog for temporary work files directory."""
        from prowser_temp_files import default_temporary_files_directory

        current_path = self.temporary_files_directory_input_field.text().strip()
        if current_path:
            current_path = self._display_to_path(current_path)
        default_path = default_temporary_files_directory()
        start_directory = (
            current_path
            if current_path and os.path.isdir(current_path)
            else (default_path if os.path.isdir(default_path) else "/tmp")
        )
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Temporary Files Directory",
            start_directory,
        )
        if directory:
            display_path = self._path_to_display(directory)
            self.temporary_files_directory_input_field.setText(display_path)

    def browse_ignore_directory(self, index: int):
        """Open directory picker dialog for ignore directory"""
        # Determine starting directory
        # Use current value if it exists and is valid, otherwise use home directory
        current_path = self.ignore_directory_input_fields[index].text().strip()
        # Expand ~ to full path for directory picker
        if current_path:
            current_path = self._display_to_path(current_path)
        start_directory = current_path if current_path and os.path.isdir(current_path) else os.path.expanduser("~")
        
        # Open directory picker dialog
        # QFileDialog.getExistingDirectory shows folders only by default on macOS
        directory = QFileDialog.getExistingDirectory(
            self,
            f"Select Directory to Ignore {index + 1}",
            start_directory
        )
        
        # Update the input field if a directory was selected (convert to display format)
        if directory:
            display_path = self._path_to_display(directory)
            self.ignore_directory_input_fields[index].setText(display_path)
    
    def browse_favorite_destination(self, index: int):
        """Open file/directory picker dialog for favorite destination"""
        # Determine starting directory
        # Use current value if it exists and is valid, otherwise use home directory
        current_path = self.favorite_destination_input_fields[index].text().strip()
        # Expand ~ to full path for directory picker
        if current_path:
            current_path = self._display_to_path(current_path)
            if os.path.isdir(current_path):
                start_directory = current_path
            elif os.path.isfile(current_path):
                start_directory = os.path.dirname(current_path)
            else:
                start_directory = os.path.expanduser("~")
        else:
            start_directory = os.path.expanduser("~")
        
        # Use QFileDialog to allow selecting both files and directories
        from thumbnails.thumbnail_constants import get_image_extensions
        image_exts = get_image_extensions()
        image_filter = "Image Files (" + " ".join(f"*{ext}" for ext in sorted(image_exts)) + ");;All Files (*)"
        
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.AnyFile)  # Allow selecting a single file or directory
        dialog.setOption(QFileDialog.ShowDirsOnly, False)  # Show both files and directories
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setDirectory(start_directory)
        dialog.setNameFilter(image_filter)
        dialog.setWindowTitle(f"Select Directory or Image File for Favorite {index + 1} (Ctrl+{index + 1})")
        
        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                selected_path = selected[0]
                # Convert to display format
                display_path = self._path_to_display(selected_path)
                # Validate that it's either a directory or an image file
                if os.path.isdir(selected_path):
                    self.favorite_destination_input_fields[index].setText(display_path)
                elif os.path.isfile(selected_path):
                    _, ext = os.path.splitext(selected_path)
                    if ext.lower() in image_exts:
                        self.favorite_destination_input_fields[index].setText(display_path)
                    else:
                        # Show error for non-image files
                        from utils import show_styled_warning
                        show_styled_warning(self, "Invalid File", 
                                          f"Selected file is not an image file:\n\n{selected_path}")
                # Validation will be triggered automatically by textChanged signal
    
    def validate_favorite_destination_path(self, index: int, path: str):
        """Validate a favorite destination path and update the validation icon"""
        validation_label = self.favorite_destination_validation_labels[index]
        
        if not path or not path.strip():
            # Empty path - no icon
            validation_label.setText("")
            validation_label.setToolTip("")
            return True
        
        path = path.strip()
        # Expand ~ to full path for validation
        full_path = self._display_to_path(path)
        
        # Check if path exists and is a directory
        if os.path.isdir(full_path):
            # Valid directory - green checkmark
            validation_label.setText("✓")
            validation_label.setStyleSheet(f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-size: 14px; font-weight: bold;")
            validation_label.setToolTip(f"Valid directory:\n{full_path}")
            return True
        elif os.path.isfile(full_path):
            # Check if it's an image file
            from utils import validate_image_file, get_file_extension
            
            if validate_image_file(full_path):
                # Valid image file - green checkmark
                validation_label.setText("✓")
                validation_label.setStyleSheet(f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-size: 14px; font-weight: bold;")
                validation_label.setToolTip(f"Valid image file:\n{full_path}")
                return True
            else:
                # File exists but is not an image file - red X
                ext = get_file_extension(full_path)
                validation_label.setText("✗")
                validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-size: 14px; font-weight: bold;")
                validation_label.setToolTip(
                    f"File is not an image file\n"
                    f"(extension: {ext if ext else 'none'})"
                )
                return False
        else:
            # Invalid path - red X
            validation_label.setText("✗")
            validation_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-size: 14px; font-weight: bold;")
            if os.path.exists(full_path):
                validation_label.setToolTip(
                    f"Path exists but is not a directory or image file:\n"
                    f"{full_path}"
                )
            else:
                validation_label.setToolTip(f"Path does not exist: {full_path}")
            return False
    
    def load_cache_directories_deferred(self):
        """Load cache directories in a deferred manner to avoid blocking the UI"""
        if not hasattr(self, 'cache_dirs_text'):
            return
        try:
             # Force sync multiprocessing cache to ensure metadata is available
            
            if self.parent() and hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                stats = self.parent().cache_manager.get_cache_statistics()
                dirs_text = "\n".join(stats['cache_directories'])
                if not dirs_text:
                    dirs_text = "No cache directories found"
                self.cache_dirs_text.setText(dirs_text)
            else:
                self.cache_dirs_text.setText("Cache manager not available")
        except Exception as e:
            print(f"Error loading cache directories: {e}")
            self.cache_dirs_text.setText("Error loading cache directories")

    def load_current_settings(self):
        """Load current settings from configuration and parent window"""
        try:
            # Get current configuration
            config = get_config()
            config.set_browse_transparency_preview(None)
            
            # Store original settings for comparison
            self.original_settings = config.load_settings()
            self.current_settings = self.original_settings.copy()
            
            # Get current values from parent window if available
            parent_window = self.parent()
            if parent_window:
                # Use current values from parent window instead of saved config
                self.debug_checkbox.setChecked(parent_window.debug_mode)
                self.original_settings['debug_mode'] = parent_window.debug_mode
                
                self.confirm_delete_checkbox.setChecked(parent_window.confirm_delete)
                self.original_settings['confirm_delete'] = parent_window.confirm_delete
                
                self.original_settings['browse_view_actual_size'] = getattr(parent_window, 'is_actual_size', False)
                
                bh_ms = getattr(parent_window, 'browse_image_history_save_after_ms', None)
                if bh_ms is None:
                    bh_ms = self.original_settings.get('browse_image_history_save_after_ms', 3000)
                try:
                    bh_ms = max(0, min(5000, int(bh_ms)))
                except (TypeError, ValueError):
                    bh_ms = 3000
                self.original_settings['browse_image_history_save_after_ms'] = bh_ms
                if hasattr(self, 'browse_image_history_save_after_slider'):
                    self.browse_image_history_save_after_slider.blockSignals(True)
                    self.browse_image_history_save_after_slider.setValue(max(0, min(10, round(bh_ms / 500))))
                    self.browse_image_history_save_after_slider.blockSignals(False)
                    self._update_browse_image_history_save_after_label()
                
                self.wrap_around_checkbox.setChecked(parent_window.wrap_around)
                self.original_settings['wrap_around'] = parent_window.wrap_around

                raise_status_bar_on_cursor_near_bottom = getattr(
                    parent_window, 'raise_status_bar_on_cursor_near_bottom', True
                )
                self.raise_status_bar_on_cursor_near_bottom_checkbox.setChecked(
                    raise_status_bar_on_cursor_near_bottom
                )
                self.original_settings['raise_status_bar_on_cursor_near_bottom'] = (
                    raise_status_bar_on_cursor_near_bottom
                )

                use_prompt_filter_exits = getattr(
                    parent_window, 'use_prompt_filter_exits', False
                )
                self.use_prompt_filter_exits_checkbox.setChecked(use_prompt_filter_exits)
                self.original_settings['use_prompt_filter_exits'] = use_prompt_filter_exits
                
                # Set ignore EXIF rotation setting (reversed: checkbox checked = use EXIF = ignore_exif=False)
                ignore_exif_rotation = getattr(parent_window, 'ignore_exif_rotation', False)
                if not hasattr(parent_window, 'ignore_exif_rotation'):
                    # Fallback to config if not set on window
                    ignore_exif_rotation = self.original_settings.get('ignore_exif_rotation', False)
                # Reverse logic: checkbox checked (True) means use EXIF (ignore_exif=False)
                self.ignore_exif_rotation_checkbox.setChecked(not ignore_exif_rotation)
                self.original_settings['ignore_exif_rotation'] = ignore_exif_rotation
                
                # Set drag drop auto date change setting
                drag_drop_auto_date_change = getattr(parent_window, 'drag_drop_auto_date_change', False)
                self.drag_drop_auto_date_change_checkbox.setChecked(drag_drop_auto_date_change)
                self.original_settings['drag_drop_auto_date_change'] = drag_drop_auto_date_change
                
                # Set allow thumbnail locking setting
                allow_thumbnail_locking = getattr(parent_window, 'allow_thumbnail_locking', False)
                if not hasattr(parent_window, 'allow_thumbnail_locking'):
                    # Fallback to config if not set on window
                    allow_thumbnail_locking = self.original_settings.get('allow_thumbnail_locking', False)
                    if 'allow_thumbnail_locking' not in self.original_settings:
                        # Load from config
                        config = get_config()
                        settings = config.load_settings()
                        allow_thumbnail_locking = settings.get('allow_thumbnail_locking', False)
                self.allow_thumbnail_locking_checkbox.setChecked(allow_thumbnail_locking)
                self.original_settings['allow_thumbnail_locking'] = allow_thumbnail_locking
                
                # Set allow quick mass rename setting
                allow_quick_mass_rename = getattr(parent_window, 'allow_quick_mass_rename', False)
                if not hasattr(parent_window, 'allow_quick_mass_rename'):
                    # Fallback to config if not set on window
                    allow_quick_mass_rename = self.original_settings.get('allow_quick_mass_rename', False)
                    if 'allow_quick_mass_rename' not in self.original_settings:
                        # Load from config
                        config = get_config()
                        settings = config.load_settings()
                        allow_quick_mass_rename = settings.get('allow_quick_mass_rename', False)
                self.allow_quick_mass_rename_checkbox.setChecked(allow_quick_mass_rename)
                self.original_settings['allow_quick_mass_rename'] = allow_quick_mass_rename
                
                # Set show extensions setting
                show_extensions = getattr(parent_window, 'show_extensions', False)
                if not hasattr(parent_window, 'show_extensions'):
                    # Fallback to config if not set on window
                    show_extensions = self.original_settings.get('show_extensions', False)
                self.show_extensions_checkbox.setChecked(show_extensions)
                self.original_settings['show_extensions'] = show_extensions
                
                # Set show filename / image size (no UI; toggled via Cmd+I)
                thumbnail_filename_visible = getattr(parent_window, 'thumbnail_filename_visible', False)
                if not hasattr(parent_window, 'thumbnail_filename_visible'):
                    settings = config.load_settings()
                    thumbnail_filename_visible = settings.get('thumbnail_filename_visible', False)
                show_image_size = getattr(parent_window, 'show_image_size', False)
                if not hasattr(parent_window, 'show_image_size'):
                    show_image_size = self.original_settings.get('show_image_size', False)
                    if 'show_image_size' not in self.original_settings:
                        settings = config.load_settings()
                        show_image_size = settings.get('show_image_size', False)
                self._set_dialog_overlay_settings(
                    thumbnail_filename_visible, show_image_size, dialog_edited=False
                )
                self._overlay_settings_dialog_edited = False
                self.original_settings['thumbnail_filename_visible'] = self._overlay_filename_visible
                self.original_settings['show_image_size'] = self._show_image_size
                
                settings = config.load_settings()
                bts = merge_browse_transparency_settings(settings.get("browse_transparency_settings"))
                self.original_settings["browse_transparency_settings"] = copy.deepcopy(bts)
                self.current_settings["browse_transparency_settings"] = copy.deepcopy(bts)
                
                # Set filtered tree setting (UI removed, value set from Tree Filtering menu and persisted)
                filtered_tree = getattr(parent_window, 'filtered_tree', 'images')
                # Convert boolean to string for backward compatibility
                if isinstance(filtered_tree, bool):
                    filtered_tree = 'use_filter' if filtered_tree else 'images'
                self.original_settings['filtered_tree'] = filtered_tree
                
                # Set space key mode
                space_mode = getattr(parent_window, 'space_key_mode', 'exit')
                for i in range(self.space_mode_combo.count()):
                    if self.space_mode_combo.itemData(i) == space_mode:
                        self.space_mode_combo.setCurrentIndex(i)
                        break
                self.original_settings['space_key_mode'] = space_mode
                
                # Set similarity metric from config
                settings = config.load_settings()
                similarity_metric = settings.get('similarity_metric', 'cosine')
                # Map config values to display names
                metric_map = {
                    'cosine': 'Cosine',
                    'euclidean': 'Euclidean',
                    'manhattan': 'Manhattan'
                }
                metric_display = metric_map.get(similarity_metric, 'Cosine')
                # Find and set the matching combo box item
                index = self.similarity_metric_combo.findText(metric_display)
                if index >= 0:
                    self.similarity_metric_combo.setCurrentIndex(index)
                self.original_settings['similarity_metric'] = similarity_metric
                
                # Load background CLIP extraction setting
                background_clip_enabled = settings.get('background_clip_enabled', False)
                if hasattr(self, 'background_clip_enabled_checkbox'):
                    self.background_clip_enabled_checkbox.setChecked(background_clip_enabled)
                self.original_settings['background_clip_enabled'] = background_clip_enabled
                # Load "Also gather thumbnails" setting (enabled only when background CLIP is enabled)
                background_clip_gather_thumbnails = settings.get('background_clip_gather_thumbnails', True)
                if hasattr(self, 'background_clip_gather_thumbnails_checkbox'):
                    self.background_clip_gather_thumbnails_checkbox.setChecked(background_clip_gather_thumbnails)
                self.original_settings['background_clip_gather_thumbnails'] = background_clip_gather_thumbnails
                # Load "Extract faces" setting (enabled only when background CLIP is enabled)
                background_clip_extract_faces = settings.get('background_clip_extract_faces', False)
                if hasattr(self, 'background_clip_extract_faces_checkbox'):
                    self.background_clip_extract_faces_checkbox.setChecked(background_clip_extract_faces)
                self.original_settings['background_clip_extract_faces'] = background_clip_extract_faces
                self._update_background_clip_subordinates_enabled()
                
                # Set CLIP model name from config
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
                if hasattr(self, 'clip_model_button_group'):
                    if clip_model_name == 'openai/clip-vit-base-patch32':
                        self.clip_model_openai_radio.setChecked(True)
                    elif clip_model_name == 'openai/clip-vit-large-patch14':
                        self.clip_model_zer0int_radio.setChecked(True)
                    else:
                        # Default to openai if unknown model
                        self.clip_model_openai_radio.setChecked(True)
                        clip_model_name = 'openai/clip-vit-base-patch32'
                self.original_settings['clip_model_name'] = clip_model_name
                
                # Set ResNet model from config
                resnet_model = settings.get('resnet_model', 'resnet18')
                if hasattr(self, 'resnet_model_button_group'):
                    if resnet_model == 'resnet18':
                        self.resnet_model_18_radio.setChecked(True)
                    elif resnet_model == 'resnet50':
                        self.resnet_model_50_radio.setChecked(True)
                    elif resnet_model == 'resnet101':
                        self.resnet_model_101_radio.setChecked(True)
                    else:
                        # Default to resnet18 if unknown model
                        self.resnet_model_18_radio.setChecked(True)
                        resnet_model = 'resnet18'
                self.original_settings['resnet_model'] = resnet_model
                
                # Set filter pattern from parent window (normalize for display)
                filter_pattern = getattr(parent_window, 'filter_pattern', '')
                self._load_filter_pattern(filter_pattern)
                # Update original settings to match what's displayed
                self.original_settings['filter_pattern'] = filter_pattern
                
                # Load depth settings from config
                settings = config.load_settings()
                shift_cmd_depth = settings.get('shift_cmd_depth', self.DEFAULT_SHIFT_CMD_DEPTH)
                self.shift_cmd_depth_spinbox.setValue(shift_cmd_depth)
                self.original_settings['shift_cmd_depth'] = shift_cmd_depth
                search_depth = settings.get('search_depth', self.DEFAULT_SEARCH_DEPTH)
                self.search_depth_spinbox.setValue(search_depth)
                self.original_settings['search_depth'] = search_depth
                
                # Enhanced image similarity settings from parent window
                # Load similarity metric from parent if available
                settings = config.load_settings()
                similarity_metric = settings.get('similarity_metric', 'cosine')
                # Map config values to display names (CLIP no longer available)
                metric_map = {
                    'cosine': 'Cosine',
                    'euclidean': 'Euclidean',
                    'manhattan': 'Manhattan'
                }
                # If somehow clip is set, default to cosine
                if similarity_metric == 'clip':
                    similarity_metric = 'cosine'
                metric_display = metric_map.get(similarity_metric, 'Cosine')
                
                # Find and set the matching combo box item
                index = self.similarity_metric_combo.findText(metric_display)
                if index >= 0:
                    self.similarity_metric_combo.setCurrentIndex(index)
                self.original_settings['similarity_metric'] = similarity_metric
                
                # Set CLIP model name from config
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
                if hasattr(self, 'clip_model_button_group'):
                    if clip_model_name == 'openai/clip-vit-base-patch32':
                        self.clip_model_openai_radio.setChecked(True)
                    elif clip_model_name == 'openai/clip-vit-large-patch14':
                        self.clip_model_zer0int_radio.setChecked(True)
                    else:
                        # Default to openai if unknown model
                        self.clip_model_openai_radio.setChecked(True)
                        clip_model_name = 'openai/clip-vit-base-patch32'
                self.original_settings['clip_model_name'] = clip_model_name
                
                # Set ResNet model from config
                resnet_model = settings.get('resnet_model', 'resnet18')
                if hasattr(self, 'resnet_model_button_group'):
                    if resnet_model == 'resnet18':
                        self.resnet_model_18_radio.setChecked(True)
                    elif resnet_model == 'resnet50':
                        self.resnet_model_50_radio.setChecked(True)
                    elif resnet_model == 'resnet101':
                        self.resnet_model_101_radio.setChecked(True)
                    else:
                        # Default to resnet18 if unknown model
                        self.resnet_model_18_radio.setChecked(True)
                        resnet_model = 'resnet18'
                self.original_settings['resnet_model'] = resnet_model
            
                # Load slideshow settings and other config-based settings (even when parent window is available)
                settings = config.load_settings()
                self._load_slideshow_settings(settings)
                self._load_move_destinations(settings)
                self._load_favorite_destinations(settings)
                self._load_exclude_destinations(settings)
                self._load_root_directories(settings)
                self._load_image_creation_directory(settings)
                self._load_temporary_files_directory(settings)
                self._load_ignore_directories(settings)
                
                # Load show hidden directories setting
                if hasattr(self, 'show_hidden_directories_checkbox'):
                    show_hidden = settings.get('show_hidden_directories', False)
                    self.show_hidden_directories_checkbox.setChecked(show_hidden)
                    self.original_settings['show_hidden_directories'] = show_hidden
                
                # Load always show work setting
                if hasattr(self, 'always_show_work_checkbox'):
                    always_show_work = settings.get('always_show_work', False)
                    self.always_show_work_checkbox.setChecked(always_show_work)
                    self.original_settings['always_show_work'] = always_show_work
                
                # Load follow symlinks setting
                if hasattr(self, 'follow_symlinks_checkbox'):
                    follow_symlinks = settings.get('follow_symlinks', False)
                    self.follow_symlinks_checkbox.setChecked(follow_symlinks)
                    self.original_settings['follow_symlinks'] = follow_symlinks
                
                self._load_image_extensions(settings)
                self._load_map_settings(settings)
                self._load_editor_settings(settings)
                self._load_captioning_settings(settings)
                self._load_lora_settings(settings)
                
            else:
                # Fall back to config values if no parent window
                settings = config.load_settings()
                
                debug_mode = settings.get('debug_mode', False)
                self.debug_checkbox.setChecked(debug_mode)
                
                confirm_delete = settings.get('confirm_delete', True)
                self.confirm_delete_checkbox.setChecked(confirm_delete)

                use_prompt_filter_exits = settings.get('use_prompt_filter_exits', False)
                self.use_prompt_filter_exits_checkbox.setChecked(use_prompt_filter_exits)
                self.original_settings['use_prompt_filter_exits'] = use_prompt_filter_exits
                
                ignore_exif_rotation = settings.get('ignore_exif_rotation', False)
                # Reverse logic: checkbox checked (True) means use EXIF (ignore_exif=False)
                self.ignore_exif_rotation_checkbox.setChecked(not ignore_exif_rotation)
                self.original_settings['ignore_exif_rotation'] = ignore_exif_rotation
                
                drag_drop_auto_date_change = settings.get('drag_drop_auto_date_change', False)
                self.drag_drop_auto_date_change_checkbox.setChecked(drag_drop_auto_date_change)
                self.original_settings['drag_drop_auto_date_change'] = drag_drop_auto_date_change
                
                # Set allow thumbnail locking setting
                allow_thumbnail_locking = settings.get('allow_thumbnail_locking', False)
                self.allow_thumbnail_locking_checkbox.setChecked(allow_thumbnail_locking)
                self.original_settings['allow_thumbnail_locking'] = allow_thumbnail_locking
                
                # Set allow quick mass rename setting
                allow_quick_mass_rename = settings.get('allow_quick_mass_rename', False)
                self.allow_quick_mass_rename_checkbox.setChecked(allow_quick_mass_rename)
                self.original_settings['allow_quick_mass_rename'] = allow_quick_mass_rename
                
                # Set show extensions setting
                show_extensions = settings.get('show_extensions', False)
                self.show_extensions_checkbox.setChecked(show_extensions)
                self.original_settings['show_extensions'] = show_extensions
                
                # Set show filename / image size (no UI; toggled via Cmd+I)
                thumbnail_filename_visible = settings.get('thumbnail_filename_visible', False)
                show_image_size = settings.get('show_image_size', False)
                self._set_dialog_overlay_settings(
                    thumbnail_filename_visible, show_image_size, dialog_edited=False
                )
                self._overlay_settings_dialog_edited = False
                self.original_settings['thumbnail_filename_visible'] = self._overlay_filename_visible
                self.original_settings['show_image_size'] = self._show_image_size
                
                bts = merge_browse_transparency_settings(settings.get("browse_transparency_settings"))
                self.original_settings["browse_transparency_settings"] = copy.deepcopy(bts)
                self.current_settings["browse_transparency_settings"] = copy.deepcopy(bts)
                
                # Load filtered tree setting (UI removed, value set from Tree Filtering menu and persisted)
                filtered_tree = settings.get('filtered_tree', 'images')
                # Convert boolean to string for backward compatibility
                if isinstance(filtered_tree, bool):
                    filtered_tree = 'use_filter' if filtered_tree else 'images'
                self.original_settings['filtered_tree'] = filtered_tree
                
                # Enhanced image similarity settings
                # Load similarity metric from config
                similarity_metric = settings.get('similarity_metric', 'cosine')
                # Map config values to display names (CLIP no longer available)
                metric_map = {
                    'cosine': 'Cosine',
                    'euclidean': 'Euclidean',
                    'manhattan': 'Manhattan'
                }
                # If somehow clip is set, default to cosine
                if similarity_metric == 'clip':
                    similarity_metric = 'cosine'
                metric_display = metric_map.get(similarity_metric, 'Cosine')
                
                # Find and set the matching combo box item
                index = self.similarity_metric_combo.findText(metric_display)
                if index >= 0:
                    self.similarity_metric_combo.setCurrentIndex(index)
                self.original_settings['similarity_metric'] = similarity_metric
                
                # Set CLIP model name from config
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
                if hasattr(self, 'clip_model_button_group'):
                    if clip_model_name == 'openai/clip-vit-base-patch32':
                        self.clip_model_openai_radio.setChecked(True)
                    elif clip_model_name == 'openai/clip-vit-large-patch14':
                        self.clip_model_zer0int_radio.setChecked(True)
                    else:
                        # Default to openai if unknown model
                        self.clip_model_openai_radio.setChecked(True)
                        clip_model_name = 'openai/clip-vit-base-patch32'
                self.original_settings['clip_model_name'] = clip_model_name
                
                # Set similarity metric from config
                similarity_metric = settings.get('similarity_metric', 'cosine')
                # Map config values to display names
                metric_map = {
                    'cosine': 'Cosine',
                    'euclidean': 'Euclidean',
                    'manhattan': 'Manhattan'
                }
                metric_display = metric_map.get(similarity_metric, 'Cosine')
                # Find and set the matching combo box item
                index = self.similarity_metric_combo.findText(metric_display)
                if index >= 0:
                    self.similarity_metric_combo.setCurrentIndex(index)
                self.original_settings['similarity_metric'] = similarity_metric
                
                # Filter settings (normalize for display)
                filter_pattern = settings.get('filter_pattern', '')
                self._load_filter_pattern(filter_pattern)
                
                # Load depth settings from config
                shift_cmd_depth = settings.get('shift_cmd_depth', self.DEFAULT_SHIFT_CMD_DEPTH)
                self.shift_cmd_depth_spinbox.setValue(shift_cmd_depth)
                self.original_settings['shift_cmd_depth'] = shift_cmd_depth
                search_depth = settings.get('search_depth', self.DEFAULT_SEARCH_DEPTH)
                self.search_depth_spinbox.setValue(search_depth)
                self.original_settings['search_depth'] = search_depth
                
                # Load slideshow settings and other config-based settings
                self._load_slideshow_settings(settings)
                self._load_move_destinations(settings)
                self._load_favorite_destinations(settings)
                self._load_exclude_destinations(settings)
                self._load_root_directories(settings)
                self._load_image_creation_directory(settings)
                self._load_temporary_files_directory(settings)
                self._load_ignore_directories(settings)
                
                # Load show hidden directories setting
                if hasattr(self, 'show_hidden_directories_checkbox'):
                    show_hidden = settings.get('show_hidden_directories', False)
                    self.show_hidden_directories_checkbox.setChecked(show_hidden)
                    self.original_settings['show_hidden_directories'] = show_hidden
                
                # Load always show work setting
                if hasattr(self, 'always_show_work_checkbox'):
                    always_show_work = settings.get('always_show_work', False)
                    self.always_show_work_checkbox.setChecked(always_show_work)
                    self.original_settings['always_show_work'] = always_show_work
                
                # Load follow symlinks setting
                if hasattr(self, 'follow_symlinks_checkbox'):
                    follow_symlinks = settings.get('follow_symlinks', False)
                    self.follow_symlinks_checkbox.setChecked(follow_symlinks)
                    self.original_settings['follow_symlinks'] = follow_symlinks
                
                self._load_image_extensions(settings)
                self._load_map_settings(settings)
                self._load_editor_settings(settings)
                self._load_captioning_settings(settings)
                self._load_lora_settings(settings)

            settings = config.load_settings()
            self._load_imagegen_general_settings(settings)
                
            self._load_theme_tab_from_settings()
            cfg = get_config()
            _ts = cfg.load_settings()
            self.original_settings['ui_theme'] = _ts.get('ui_theme', 'dark')
            self.original_settings['user_theme_colors'] = copy.deepcopy(
                merge_user_theme_colors(_ts.get('user_theme_colors'))
            )
            self.original_settings['dark_theme_colors'] = copy.deepcopy(
                merge_dark_theme_colors(_ts.get('dark_theme_colors'))
            )
            self.original_settings['light_theme_colors'] = copy.deepcopy(
                merge_light_theme_colors(_ts.get('light_theme_colors'))
            )
            theme_groups_expanded = merge_theme_settings_groups_expanded(
                _ts.get("theme_settings_groups_expanded")
            )
            self.original_settings["theme_settings_groups_expanded"] = copy.deepcopy(theme_groups_expanded)
            if hasattr(self, "current_settings"):
                self.current_settings['user_theme_colors'] = copy.deepcopy(
                    merge_user_theme_colors(_ts.get('user_theme_colors'))
                )
                self.current_settings['dark_theme_colors'] = copy.deepcopy(
                    merge_dark_theme_colors(_ts.get('dark_theme_colors'))
                )
                self.current_settings['light_theme_colors'] = copy.deepcopy(
                    merge_light_theme_colors(_ts.get('light_theme_colors'))
                )
                self.current_settings["theme_settings_groups_expanded"] = copy.deepcopy(theme_groups_expanded)
            _bts_ts = merge_browse_transparency_settings(_ts.get("browse_transparency_settings"))
            self.original_settings["browse_transparency_settings"] = copy.deepcopy(_bts_ts)
            if hasattr(self, "current_settings"):
                self.current_settings["browse_transparency_settings"] = copy.deepcopy(_bts_ts)

            self._apply_theme_collapse_groups_from_settings()

            # Update match count
            self.update_match_count(self.filter_pattern_input.text())

            self._update_cache_source_directories_visibility()
            
        except Exception as e:
            print(f"Failed to load settings: {e}")

    def _calculate_overlap_delay(self):
        """Calculate overlap delay from percentage"""
        overlap_percent = self.overlap_percent_spinbox.value()
        transition_speed = self.transition_speed_spinbox.value()
        # Convert percentage to delay: delay = (100 - percent) * transition_speed / 100
        try:
            overlap_delay = (100 - overlap_percent) * transition_speed / 100
        except Exception:
            overlap_delay = self.DEFAULT_OVERLAP_DELAY
        return int(overlap_delay)

    def _calculate_overlap_percent(self, overlap_delay, transition_speed):
        """Calculate overlap percentage from delay"""
        try:
            return int(100 - (overlap_delay / transition_speed * 100))
        except Exception:
            return self.DEFAULT_OVERLAP_PERCENT

    def _load_slideshow_settings(self, settings):
        """Load slideshow settings from config"""
        self.slideshow_rate_spinbox.setValue(settings.get('slideshow_rate', self.DEFAULT_SLIDESHOW_RATE))
        self.transition_speed_spinbox.setValue(settings.get('slideshow_transition_speed', self.DEFAULT_TRANSITION_SPEED))
        self.rotation_angle_spinbox.setValue(settings.get('slideshow_max_rotation', 0))
        
        # Calculate overlap percentage from delay
        overlap_delay = settings.get('slideshow_overlap_delay', self.DEFAULT_OVERLAP_DELAY)
        transition_speed = settings.get('slideshow_transition_speed', self.DEFAULT_TRANSITION_SPEED)
        overlap_percent = self._calculate_overlap_percent(overlap_delay, transition_speed)
        self.overlap_percent_spinbox.setValue(overlap_percent)
        
        self.direction_combo.setCurrentText(settings.get('slideshow_direction', self.DEFAULT_SLIDESHOW_DIRECTION))
        self.slideshow_back_and_forth_checkbox.setChecked(
            settings.get('slideshow_back_and_forth', self.DEFAULT_SLIDESHOW_BACK_AND_FORTH)
        )
        
        # Update original settings
        self.original_settings['slideshow_rate'] = settings.get('slideshow_rate', self.DEFAULT_SLIDESHOW_RATE)
        self.original_settings['slideshow_transition_speed'] = settings.get('slideshow_transition_speed', self.DEFAULT_TRANSITION_SPEED)
        self.original_settings['slideshow_max_rotation'] = settings.get('slideshow_max_rotation', 0)
        self.original_settings['slideshow_overlap_percent'] = overlap_percent
        self.original_settings['slideshow_direction'] = settings.get('slideshow_direction', self.DEFAULT_SLIDESHOW_DIRECTION)
        self.original_settings['slideshow_back_and_forth'] = settings.get(
            'slideshow_back_and_forth', self.DEFAULT_SLIDESHOW_BACK_AND_FORTH
        )

    def _load_move_destinations(self, settings):
        """Load move destinations from config"""
        if not hasattr(self, 'move_destination_input_fields'):
            return
        
        destinations = settings.get('move_destinations', [None] * 9)
        # Ensure we have exactly 9 items
        destinations = (destinations + [None] * 9)[:9]
        
        # Load into input fields (convert to display format)
        for i, dest in enumerate(destinations):
            if dest:
                display_path = self._path_to_display(dest)
                self.move_destination_input_fields[i].setText(display_path)
                self.validate_move_destination_path(i, display_path)
            else:
                self.move_destination_input_fields[i].setText("")
        
        self.original_settings['move_destinations'] = destinations

        # Load destination menu action
        action = settings.get('destination_menu_action', 'move')
        if action not in ('none', 'copy', 'move'):
            action = 'move'
        if hasattr(self, 'destination_menu_action_combo'):
            idx = {'none': 0, 'copy': 1, 'move': 2}.get(action, 2)
            self.destination_menu_action_combo.setCurrentIndex(idx)
        self.original_settings['destination_menu_action'] = action

    def _get_destination_menu_action(self):
        """Get destination menu action from combo: 'none', 'copy', or 'move'"""
        if hasattr(self, 'destination_menu_action_combo'):
            return ['none', 'copy', 'move'][self.destination_menu_action_combo.currentIndex()]
        return 'move'

    def _load_favorite_destinations(self, settings):
        """Load favorite destinations from config"""
        if not hasattr(self, 'favorite_destination_input_fields'):
            return
        
        favorites = settings.get('favorite_directories', [None] * 9)
        # Ensure we have exactly 9 items
        favorites = (favorites + [None] * 9)[:9]
        
        # Load into input fields (convert to display format)
        for i, fav in enumerate(favorites):
            if fav:
                display_path = self._path_to_display(fav)
                self.favorite_destination_input_fields[i].setText(display_path)
                self.validate_favorite_destination_path(i, display_path)
            else:
                self.favorite_destination_input_fields[i].setText("")
        
        self.original_settings['favorite_directories'] = favorites

    def _load_exclude_destinations(self, settings):
        """Load exclude destinations from config"""
        if not hasattr(self, 'exclude_destination_input_fields'):
            return
        
        exclude_dirs = settings.get('exclude_directories', [])
        if not isinstance(exclude_dirs, list):
            exclude_dirs = []
        
        # Ensure we have at least 9 items (pad with empty dicts)
        while len(exclude_dirs) < 9:
            exclude_dirs.append({'path': None, 'enabled': False})
        exclude_dirs = exclude_dirs[:9]
        
        # Load into input fields and checkboxes (convert to display format)
        for i, exclude_dir in enumerate(exclude_dirs):
            if isinstance(exclude_dir, dict):
                path = exclude_dir.get('path')
                enabled = exclude_dir.get('enabled', False)
            else:
                # Backward compatibility: if it's just a string, treat as path with enabled=False
                path = exclude_dir if exclude_dir else None
                enabled = False
            
            if path:
                display_path = self._path_to_display(path)
                self.exclude_destination_input_fields[i].setText(display_path)
            else:
                self.exclude_destination_input_fields[i].setText("")
            
            if hasattr(self, 'exclude_destination_checkboxes'):
                self.exclude_destination_checkboxes[i].setChecked(enabled)
        
        self.original_settings['exclude_directories'] = exclude_dirs

    def _load_image_creation_directory(self, settings):
        """Load image creation directory from config."""
        if not hasattr(self, "image_creation_directory_input_field"):
            return
        entry = settings.get("image_creation_directory") or {}
        if not isinstance(entry, dict):
            entry = {}
        path = entry.get("path")
        enabled = entry.get("enabled", False)
        if path:
            self.image_creation_directory_input_field.setText(
                self._path_to_display(path)
            )
        else:
            self.image_creation_directory_input_field.setText("")
        if hasattr(self, "image_creation_directory_checkbox"):
            self.image_creation_directory_checkbox.setChecked(enabled)
        self.original_settings["image_creation_directory"] = {
            "path": path,
            "enabled": enabled,
        }

    def _load_temporary_files_directory(self, settings):
        """Load temporary files directory from config."""
        if not hasattr(self, "temporary_files_directory_input_field"):
            return
        path = settings.get("temporary_files_directory")
        if path:
            self.temporary_files_directory_input_field.setText(
                self._path_to_display(path)
            )
        else:
            self.temporary_files_directory_input_field.setText("")
        self.original_settings["temporary_files_directory"] = path

    def _load_ignore_directories(self, settings):
        """Load ignore directories from config"""
        if not hasattr(self, 'ignore_directory_input_fields'):
            return
        
        ignore_dirs = settings.get('ignore_directories', [])
        if not isinstance(ignore_dirs, list):
            ignore_dirs = []
        
        # Ensure we have at least 3 items (pad with empty dicts)
        while len(ignore_dirs) < 3:
            ignore_dirs.append({'path': None, 'enabled': False})
        ignore_dirs = ignore_dirs[:3]
        
        # Load into input fields and checkboxes (convert to display format)
        for i, ignore_dir in enumerate(ignore_dirs):
            if isinstance(ignore_dir, dict):
                path = ignore_dir.get('path')
                enabled = ignore_dir.get('enabled', False)
            else:
                # Backward compatibility: if it's just a string, treat as path with enabled=True
                path = ignore_dir if ignore_dir else None
                enabled = True if path else False
            
            if path:
                display_path = self._path_to_display(path)
                self.ignore_directory_input_fields[i].setText(display_path)
            else:
                self.ignore_directory_input_fields[i].setText("")
            
            if hasattr(self, 'ignore_directory_checkboxes'):
                self.ignore_directory_checkboxes[i].setChecked(enabled)
        
        self.original_settings['ignore_directories'] = ignore_dirs

    def _load_root_directories(self, settings):
        """Load root directories from config"""
        if not hasattr(self, 'directory_checkboxes'):
            return
        
        enabled_directories = settings.get('root_directories', self.DEFAULT_ROOT_DIRECTORIES)
        if not isinstance(enabled_directories, list):
            enabled_directories = self.DEFAULT_ROOT_DIRECTORIES
        
        # Normalize: remove leading slashes from loaded directories for comparison with checkbox names
        # (checkboxes use names without leading slashes, but config stores with slashes)
        # Handle both old format (without slashes) and new format (with slashes) for backward compatibility
        normalized_loaded = []
        normalized_with_slashes = []
        for dir_path in enabled_directories:
            # Remove leading slash if present for comparison with checkbox names
            normalized_name = dir_path[1:] if dir_path.startswith('/') else dir_path
            normalized_loaded.append(normalized_name)
            # Ensure we store with leading slash for file_tree_handler
            normalized_with_slashes.append(f"/{normalized_name}")
        
        # Set checkboxes based on saved settings (compare normalized names)
        for directory, checkbox in self.directory_checkboxes.items():
            checkbox.setChecked(directory in normalized_loaded)
        
        # Store normalized version (with leading slashes) in original_settings for proper comparison
        self.original_settings['root_directories'] = normalized_with_slashes

    def _load_image_extensions(self, settings):
        """Load image extensions from config"""
        if not hasattr(self, 'extension_checkboxes'):
            return
        
        enabled_extensions = settings.get('image_extensions', self.DEFAULT_IMAGE_EXTENSIONS)
        if not isinstance(enabled_extensions, list):
            enabled_extensions = self.DEFAULT_IMAGE_EXTENSIONS
        
        # Set checkboxes based on saved settings
        for extension, checkbox in self.extension_checkboxes.items():
            checkbox.setChecked(extension in enabled_extensions)
        
        self.original_settings['image_extensions'] = enabled_extensions

    def _load_map_settings(self, settings):
        """Load map application preference from config"""
        if not hasattr(self, 'map_app_group'):
            return
        
        map_app = settings.get('map_application', 'apple_maps')
        
        # Set radio button based on saved preference
        if map_app == 'google_maps':
            self.google_maps_radio.setChecked(True)
        elif map_app == 'google_earth':
            self.google_earth_radio.setChecked(True)
        else:
            # Default to Apple Maps
            self.apple_maps_radio.setChecked(True)
        
        self.original_settings['map_application'] = map_app
    
    def _load_captioning_settings(self, settings):
        """Load AI captioning settings from config"""
        if not hasattr(self, 'caption_system_prompt_edit'):
            return
        from config import CAPTION_DEFAULTS
        self.caption_lms_host_edit.setText(
            settings.get('caption_lms_host', CAPTION_DEFAULTS['caption_lms_host'])
        )
        self.caption_system_prompt_edit.setPlainText(
            settings.get('caption_system_prompt', CAPTION_DEFAULTS['caption_system_prompt'])
        )
        self.caption_user_prompt_edit.setPlainText(
            settings.get('caption_user_prompt', CAPTION_DEFAULTS['caption_user_prompt'])
        )
        self.caption_max_words_spinbox.setValue(
            settings.get('caption_max_words', CAPTION_DEFAULTS['caption_max_words'])
        )
        self.caption_temperature_spinbox.setValue(
            settings.get('caption_temperature', CAPTION_DEFAULTS['caption_temperature'])
        )
        self.original_settings['caption_lms_host'] = self.caption_lms_host_edit.text()
        self.original_settings['caption_system_prompt'] = self.caption_system_prompt_edit.toPlainText()
        self.original_settings['caption_user_prompt'] = self.caption_user_prompt_edit.toPlainText()
        self.original_settings['caption_max_words'] = self.caption_max_words_spinbox.value()
        self.original_settings['caption_temperature'] = self.caption_temperature_spinbox.value()

    def _load_lora_settings(self, settings):
        """Load per-model LoRA enable state from config."""
        if not hasattr(self, "_lora_checkboxes"):
            return

        self._lora_catalog_loaded = False
        self._load_lora_drafts_from_settings(settings)
        model_key = self._resolve_lora_model_key(settings)
        if hasattr(self, "_lora_model_combo"):
            idx = self._lora_model_combo.findData(model_key)
            if idx >= 0:
                self._lora_model_combo.blockSignals(True)
                self._lora_model_combo.setCurrentIndex(idx)
                self._lora_model_combo.blockSignals(False)
        self._show_lora_draft_for_model(model_key)
        self._lora_catalog_loaded = True
        slice_ = self._lora_draft_slice(model_key)
        self.original_settings["imagegen_lora_model_key"] = model_key
        self.original_settings["imagegen_lora_enabled_ids"] = list(slice_["enabled_ids"])
    
    def _load_editor_settings(self, settings):
        """Load image editor preference from config"""
        if not hasattr(self, 'editor_selection_label'):
            return
        
        editor_app = settings.get('image_editor_app', 'Preview')
        
        # Update label to show current selection
        self.editor_selection_label.setText(editor_app)
        
        self.original_settings['image_editor_app'] = editor_app
    
    def _get_image_editor_apps(self) -> List[Tuple[str, str]]:
        """Get list of (app_name, app_path) tuples for apps that can handle image files"""
        if not MACOS_APP_SELECTION_AVAILABLE:
            return []
        
        apps = []
        apps_seen = set()  # Track apps we've already added to avoid duplicates
        
        try:
            # Method 1: Use LSCopyApplicationURLsForURL with a sample image file
            # This is what Finder uses and returns more comprehensive results
            # Important: Use a file with a real image extension (.png, .jpg) to get comprehensive results
            from LaunchServices import LSCopyApplicationURLsForURL
            from prowser_temp_files import prowser_mkstemp_path

            # Create a temporary PNG file to query for apps
            # Using a real image extension ensures we get all apps that can handle images
            temp_img_path = None
            try:
                temp_img_path = prowser_mkstemp_path(suffix='.png', prefix='image_editor_probe_')
                with open(temp_img_path, 'wb') as temp_img:
                    temp_img.write(b'\x89PNG\r\n\x1a\n')  # Minimal PNG header
                
                file_url = NSURL.fileURLWithPath_(temp_img_path)
                app_urls = LSCopyApplicationURLsForURL(file_url, kLSRolesAll)
                if app_urls:
                    app_count = app_urls.count()
                    for i in range(app_count):
                        app_url = app_urls.objectAtIndex_(i)
                        app_path_str = str(app_url.path())
                        # Extract app name from path
                        app_name = os.path.basename(app_path_str)
                        if app_name.endswith('.app'):
                            app_name = app_name[:-4]
                        
                        # Only add if not already seen and app exists
                        if app_path_str not in apps_seen and os.path.exists(app_path_str):
                            apps_seen.add(app_path_str)
                            apps.append((app_name, app_path_str))
                
                # Clean up temp file
                if os.path.exists(temp_img_path):
                    os.unlink(temp_img_path)
            except Exception:
                # Clean up temp file if it exists
                if temp_img_path and os.path.exists(temp_img_path):
                    try:
                        os.unlink(temp_img_path)
                    except Exception:
                        pass
            
            # Method 2: Also use LSCopyAllRoleHandlersForContentType as a supplement
            # This catches apps that register for the content type but might not be in method 1
            handlers = LSCopyAllRoleHandlersForContentType(kUTTypeImage, kLSRolesAll)
            
            if handlers:
                workspace = NSWorkspace.sharedWorkspace()
                handler_count = handlers.count()
                
                for i in range(handler_count):
                    bundle_id = str(handlers.objectAtIndex_(i))
                    app_path = workspace.absolutePathForAppBundleWithIdentifier_(bundle_id)
                    if app_path:
                        app_path_str = str(app_path)
                        # Only add if not already seen
                        if app_path_str not in apps_seen:
                            apps_seen.add(app_path_str)
                            app_name = os.path.basename(app_path_str)
                            if app_name.endswith('.app'):
                                app_name = app_name[:-4]
                            apps.append((app_name, app_path_str))
        except Exception:
            pass
        
        # Sort by name
        apps.sort(key=lambda x: x[0].lower())
        return apps
    
    def _select_image_editor(self):
        """Open native macOS dialog to select an image editor application"""
        # Get list of image editor apps registered for images
        image_editors = self._get_image_editor_apps() if MACOS_APP_SELECTION_AVAILABLE else []
        
        # If we have registered image editors, show them first with option for "Other..."
        if image_editors and MACOS_APP_SELECTION_AVAILABLE:
            # Create custom dialog showing suggested image editors
            editor_dialog = QDialog(self)
            editor_dialog.setWindowTitle("Select Image Editor")
            editor_dialog.setMinimumWidth(450)
            editor_dialog.setMinimumHeight(300)
            
            layout = QVBoxLayout(editor_dialog)
            layout.setSpacing(10)
            
            # Title
            title = QLabel("Suggested Image Editors")
            title_font = QFont()
            title_font.setPointSize(13)
            title_font.setBold(True)
            title.setFont(title_font)
            layout.addWidget(title)
            
            # Description
            desc = QLabel("Applications registered to open image files:")
            desc.setStyleSheet(self.NOTE_TEXT_STYLE)
            layout.addWidget(desc)
            
            # Scroll area for app list
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMinimumHeight(200)
            
            editor_list = QWidget()
            editor_list_layout = QVBoxLayout(editor_list)
            editor_list_layout.setContentsMargins(10, 10, 10, 10)
            editor_list_layout.setSpacing(5)
            
            selected_app = [None]  # Use list to allow modification in nested function
            
            for app_name, app_path in image_editors:
                btn = QPushButton(app_name)
                btn.setToolTip(app_path)
                btn.setStyleSheet(self._picker_list_button_style())
                btn.clicked.connect(lambda checked=False, name=app_name, path=app_path: 
                    selected_app.__setitem__(0, (name, path)) or editor_dialog.accept())
                editor_list_layout.addWidget(btn)
            
            editor_list_layout.addStretch()
            scroll.setWidget(editor_list)
            layout.addWidget(scroll)
            
            # Separator
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Sunken)
            layout.addWidget(separator)
            
            # "Other..." button to show all apps
            show_other = [False]  # Use list to allow modification in nested function
            
            def show_other_dialog():
                show_other[0] = True
                editor_dialog.accept()
            
            other_button = QPushButton("Other...")
            other_button.setToolTip("Browse for any application not listed above")
            other_button.setStyleSheet(self._picker_list_button_style())
            other_button.clicked.connect(show_other_dialog)
            layout.addWidget(other_button)
            
            # Buttons
            button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
            button_box.rejected.connect(editor_dialog.reject)
            layout.addWidget(button_box)
            
            # Show dialog
            dialog_result = editor_dialog.exec()
            
            if dialog_result == QDialog.Accepted:
                if selected_app[0]:
                    app_name, app_path = selected_app[0]
                    self.editor_selection_label.setText(app_name)
                    return
                elif show_other[0]:
                    # User clicked "Other..." - continue to show full file dialog below
                    pass
                else:
                    return
            else:
                # User cancelled
                return
        
        # Show full application selection dialog using native NSOpenPanel
        # (either no image editors found, or user chose "Other...")
        if MACOS_APP_SELECTION_AVAILABLE and NSOpenPanel:
            try:
                # Create NSOpenPanel - this is the native macOS "Open With" dialog
                panel = NSOpenPanel.openPanel()
                panel.setTitle_("Select Image Editor")
                panel.setPrompt_("Choose")
                panel.setCanChooseFiles_(True)
                panel.setCanChooseDirectories_(False)
                panel.setAllowsMultipleSelection_(False)
                panel.setCanCreateDirectories_(False)
                
                # Set to show .app files only
                panel.setAllowedFileTypes_(["app"])
                
                # Start in /Applications
                apps_dir = NSURL.fileURLWithPath_("/Applications")
                panel.setDirectoryURL_(apps_dir)
                
                # Show the panel modally
                result = panel.runModal()
                
                if result == NSModalResponseOK:
                    urls = panel.URLs()
                    if urls and urls.count() > 0:
                        selected_url = urls.objectAtIndex_(0)
                        app_path = str(selected_url.path())
                        
                        # Extract app name from path
                        app_name = os.path.basename(app_path)
                        if app_name.endswith('.app'):
                            app_name = app_name[:-4]  # Remove .app extension
                        
                        # Update the label
                        self.editor_selection_label.setText(app_name)
                        return
            except Exception:
                # Fall through to QFileDialog fallback
                pass
        
        # Fallback to QFileDialog if native dialogs are not available
        start_dir = '/Applications'
        if not os.path.exists(start_dir):
            start_dir = os.path.expanduser('~/Applications')
            if not os.path.exists(start_dir):
                start_dir = os.path.expanduser('~')
        
        dialog = QFileDialog(self, "Select Image Editor Application")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setDirectory(start_dir)
        dialog.setNameFilter("Applications (*.app)")
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setOption(QFileDialog.DontUseNativeDialog, False)
        
        if dialog.exec():
            selected_files = dialog.selectedFiles()
            if selected_files:
                app_path = selected_files[0]
                # Extract app name from path (e.g., "/Applications/Pixelmator Pro.app" -> "Pixelmator Pro")
                app_name = os.path.basename(app_path)
                if app_name.endswith('.app'):
                    app_name = app_name[:-4]  # Remove .app extension
                
                # Update the label
                self.editor_selection_label.setText(app_name)
    
    def _get_image_editor(self):
        """Get selected image editor application name"""
        if not hasattr(self, 'editor_selection_label'):
            return 'Preview'
        
        editor_name = self.editor_selection_label.text()
        return editor_name if editor_name else 'Preview'

    def _load_filter_pattern(self, filter_pattern):
        """Load filter pattern into input field (normalize for display)"""
        if filter_pattern:
            normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
            self.filter_pattern_input.setText(normalized_pattern)
        else:
            self.filter_pattern_input.setText(filter_pattern)


    def _faces_subjects_changed(self) -> bool:
        if not hasattr(self, "_faces_subjects"):
            return False
        baseline = getattr(self, "_faces_subjects_at_load", None)
        if baseline is None:
            return True
        return copy.deepcopy(self._faces_subjects) != copy.deepcopy(baseline)

    def accept(self):
        """Apply settings and close dialog"""
        try:
            get_config().set_browse_transparency_preview(None)
            lora_persisted = False
            if hasattr(self, "_lora_checkboxes"):
                self._ensure_lora_tab_ready()
                lora_persisted = self._flush_lora_tab_to_disk()
            # Validate faces before close (persist only if changed)
            if hasattr(self, '_faces_subjects'):
                names_seen = {}
                for s in self._faces_subjects:
                    name = (s.get("name") or "").strip()
                    if not name:
                        show_styled_warning(
                            self, "Empty name",
                            "Every person must have a non-empty name. Remove or name any \"New person\" entries."
                        )
                        return
                    key = name.lower()
                    if key in names_seen:
                        show_styled_warning(
                            self, "Duplicate name",
                            f"A person with the name \"{name}\" already exists. Names must be unique."
                        )
                        return
                    names_seen[key] = True

            from prowser_temp_files import validate_temporary_files_directory_for_settings

            temp_dir_error = validate_temporary_files_directory_for_settings(
                self.get_temporary_files_directory()
            )
            if temp_dir_error:
                show_styled_warning(
                    self,
                    "Temporary files directory",
                    temp_dir_error,
                )
                return

            # Get current settings
            new_settings = self.get_settings()
            
            # Check if any settings actually changed
            has_changes = False
            changed_keys: set = set()
            limit_or_filter_changed = False
            favorites_changed = False
            move_destinations_changed = False
            
            # Optimized: Remove redundant prints, compact special handling, and minimize logic
            for key, new_value in new_settings.items():
                original_value = self.original_settings.get(key)
                # Treat None and "" as equivalent for filter_pattern
                if key == 'filter_pattern':
                    original_value = original_value or ""
                    new_value = new_value or ""
                elif key in (
                    'imagegen_lora_enabled_ids',
                    'imagegen_lora_model_key',
                    'imagegen_lora_deleted_ids',
                ):
                    original_value = sorted(original_value or [])
                    new_value = sorted(new_value or [])
                elif key == 'browse_transparency_settings':
                    o = merge_browse_transparency_settings(
                        original_value if isinstance(original_value, dict) else None
                    )
                    n = merge_browse_transparency_settings(new_value if isinstance(new_value, dict) else None)
                    original_value = tuple(
                        sorted(
                            (
                                t,
                                tuple(o[t]["transparency_color"]),
                                o[t]["use_diamonds"],
                                tuple(o[t]["browse_border_color"]),
                            )
                            for t in ("dark", "light", "user")
                        )
                    )
                    new_value = tuple(
                        sorted(
                            (
                                t,
                                tuple(n[t]["transparency_color"]),
                                n[t]["use_diamonds"],
                                tuple(n[t]["browse_border_color"]),
                            )
                            for t in ("dark", "light", "user")
                        )
                    )
                elif key == 'favorite_directories':
                    # Compare favorite_directories lists properly - normalize to same length and compare element by element
                    # Ensure both are lists of 9 items (None where empty)
                    orig_favs = (original_value or [])[:9]
                    orig_favs = (orig_favs + [None] * 9)[:9]
                    new_favs = (new_value or [])[:9]
                    new_favs = (new_favs + [None] * 9)[:9]
                    # Compare element by element (treating None and empty string as equivalent)
                    original_value = tuple(str(v) if v else '' for v in orig_favs)
                    new_value = tuple(str(v) if v else '' for v in new_favs)
                elif key == 'user_theme_colors':
                    o = merge_user_theme_colors(original_value if isinstance(original_value, dict) else None)
                    n = merge_user_theme_colors(new_value if isinstance(new_value, dict) else None)
                    original_value = tuple(sorted(o.items()))
                    new_value = tuple(sorted(n.items()))
                elif key == 'dark_theme_colors':
                    o = merge_dark_theme_colors(original_value if isinstance(original_value, dict) else None)
                    n = merge_dark_theme_colors(new_value if isinstance(new_value, dict) else None)
                    original_value = tuple(sorted(o.items()))
                    new_value = tuple(sorted(n.items()))
                elif key == 'light_theme_colors':
                    o = merge_light_theme_colors(original_value if isinstance(original_value, dict) else None)
                    n = merge_light_theme_colors(new_value if isinstance(new_value, dict) else None)
                    original_value = tuple(sorted(o.items()))
                    new_value = tuple(sorted(n.items()))
                elif key == 'ui_theme':
                    if self._ui_theme_values_equal(original_value, new_value):
                        continue
                if original_value != new_value:
                    has_changes = True
                    changed_keys.add(key)
                    if key == 'filter_pattern':
                        limit_or_filter_changed = True
                    elif key == 'favorite_directories':
                        favorites_changed = True
                    elif key == 'move_destinations':
                        move_destinations_changed = True
            
            # Check if image_extensions changed
            if 'image_extensions' in changed_keys:
                clear_image_extensions_cache()

            if hasattr(self, '_faces_subjects') and self._faces_subjects_changed():
                from faces.known_faces_manager import save as save_faces

                save_faces(self._faces_subjects)
                self._faces_subjects_at_load = copy.deepcopy(self._faces_subjects)
            
            config = get_config()
            _skip_persist_keys = frozenset({
                '_limit_or_filter_changed',
                'imagegen_lora_enabled_ids',
                'imagegen_lora_model_key',
                'imagegen_lora_deleted_ids',
            })
            if has_changes:
                settings_updates = {
                    key: value
                    for key, value in new_settings.items()
                    if key in changed_keys and key not in _skip_persist_keys
                }
                if settings_updates:
                    config.update_settings(settings_updates)

            if lora_persisted:
                mw = self.parent()
                if mw is not None and hasattr(mw, "refresh_open_imagegen_lora_combos"):
                    mw.refresh_open_imagegen_lora_combos()
            if "imagegen_max_generation_dimension" in changed_keys:
                mw = self.parent()
                if mw is not None and hasattr(mw, "refresh_open_imagegen_dim_limits"):
                    mw.refresh_open_imagegen_dim_limits()
            
            # Emit only changed settings so handlers skip unrelated work
            if has_changes:
                payload = {key: new_settings[key] for key in changed_keys}
                payload['_limit_or_filter_changed'] = limit_or_filter_changed
                self.settings_changed.emit(payload)
            elif favorites_changed or move_destinations_changed:
                payload = {}
                if favorites_changed:
                    payload['favorite_directories'] = new_settings['favorite_directories']
                if move_destinations_changed:
                    payload['move_destinations'] = new_settings['move_destinations']
                payload['_limit_or_filter_changed'] = False
                self.settings_changed.emit(payload)

            # Save current tab for next time (session-only)
            current_idx = self.tab_widget.currentIndex()
            if current_idx >= 0:
                current_widget = self.tab_widget.widget(current_idx)
                if current_widget is not None:
                    tab_id = self._get_tab_name(current_widget)
                    if tab_id:
                        SettingsDialog._last_tab_id = tab_id
            self._persist_session_lora_model_key()

            # Close dialog (_schedule_post_settings_menu_refresh runs via accepted signal)
            super().accept()
            
        except Exception as e:
            show_styled_critical(
                self,
                "Error Applying Settings",
                f"An error occurred while applying settings:\n\n{str(e)}"
            )

    def reject(self):
        """Cancel dialog and close"""
        self._restore_theme_snapshot_at_open()
        # Save current tab for next time (session-only)
        current_idx = self.tab_widget.currentIndex()
        if current_idx >= 0:
            current_widget = self.tab_widget.widget(current_idx)
            if current_widget is not None:
                tab_id = self._get_tab_name(current_widget)
                if tab_id:
                    SettingsDialog._last_tab_id = tab_id
        self._persist_session_lora_model_key()
        super().reject()

    def get_settings(self):
        """Get the current settings from the dialog"""
        settings = {
            'debug_mode': self.debug_checkbox.isChecked(),
            'confirm_delete': self.confirm_delete_checkbox.isChecked(),
            'browse_image_history_save_after_ms': (
                self.browse_image_history_save_after_slider.value() * 500
                if hasattr(self, 'browse_image_history_save_after_slider') else 3000
            ),
            'space_key_mode': self.space_mode_combo.currentData(),
            'slideshow_rate': self.slideshow_rate_spinbox.value(),
            'slideshow_transition_speed': self.transition_speed_spinbox.value(),
            'slideshow_direction': self.direction_combo.currentText(),
            'slideshow_max_rotation': self.rotation_angle_spinbox.value(),
            'slideshow_overlap_percent': self.overlap_percent_spinbox.value(),
            'slideshow_overlap_delay': self._calculate_overlap_delay(),
            'slideshow_back_and_forth': self.slideshow_back_and_forth_checkbox.isChecked(),
            'wrap_around': self.wrap_around_checkbox.isChecked(),
            'raise_status_bar_on_cursor_near_bottom': (
                self.raise_status_bar_on_cursor_near_bottom_checkbox.isChecked()
            ),
            'use_prompt_filter_exits': self.use_prompt_filter_exits_checkbox.isChecked(),
            'ignore_exif_rotation': not self.ignore_exif_rotation_checkbox.isChecked(),  # Reversed: checked = use EXIF (ignore_exif=False)
            'drag_drop_auto_date_change': self.drag_drop_auto_date_change_checkbox.isChecked(),
            'allow_thumbnail_locking': self.allow_thumbnail_locking_checkbox.isChecked(),
            'allow_quick_mass_rename': self.allow_quick_mass_rename_checkbox.isChecked(),
            'show_extensions': self.show_extensions_checkbox.isChecked(),
            'thumbnail_filename_visible': self._get_overlay_settings_for_save()[0],
            'show_image_size': self._get_overlay_settings_for_save()[1],
            'imagegen_max_generation_dimension': (
                self._imagegen_max_generation_dimension_px()
                if hasattr(self, 'imagegen_max_generation_dimension_slider')
                else 1024
            ),
            'imagegen_series_cooldown_seconds': (
                int(self.imagegen_series_cooldown_slider.value())
                if hasattr(self, 'imagegen_series_cooldown_slider')
                else 60
            ),
            'imagegen_add_chat_prefix_postfix': (
                self.imagegen_add_chat_prefix_postfix_checkbox.isChecked()
                if hasattr(self, 'imagegen_add_chat_prefix_postfix_checkbox')
                else True
            ),
            'filtered_tree': self.original_settings.get('filtered_tree', 'images'),  # UI removed, value set from Tree Filtering menu and persisted
            'filter_pattern': ImageBrowserConfig.normalize_filter_pattern(self.filter_pattern_input.text().strip()),
            'shift_cmd_depth': self.shift_cmd_depth_spinbox.value(),
            'search_depth': self.search_depth_spinbox.value(),
            'move_destinations': self.get_move_destinations(),
            'destination_menu_action': self._get_destination_menu_action(),
            'favorite_directories': self.get_favorite_directories(),
            'exclude_directories': self.get_exclude_destinations(),
            'root_directories': self.get_root_directories(),
            'image_extensions': self.get_image_extensions(),
            'show_hidden_directories': self.show_hidden_directories_checkbox.isChecked() if hasattr(self, 'show_hidden_directories_checkbox') else False,
            'always_show_work': self.always_show_work_checkbox.isChecked() if hasattr(self, 'always_show_work_checkbox') else False,
            'follow_symlinks': self.follow_symlinks_checkbox.isChecked() if hasattr(self, 'follow_symlinks_checkbox') else False,
            'ignore_directories': self.get_ignore_directories(),
            'image_creation_directory': self.get_image_creation_directory(),
            'temporary_files_directory': self.get_temporary_files_directory(),
            'map_application': self._get_map_application(),
            'image_editor_app': self._get_image_editor(),
        }
        
        # Get similarity metric from settings (CLIP is no longer an option)
        similarity_metric = self._get_similarity_metric()
        # Ensure we're not using CLIP (shouldn't be possible, but be safe)
        if similarity_metric == 'clip':
            similarity_metric = 'cosine'
        
        settings['similarity_metric'] = similarity_metric
        settings['similarity_search_mode'] = 'image'  # Always image mode for cmd-K
        
        # Always use Accurate mode (hardcoded)
        settings['similarity_mode'] = 'accurate'
        
        # Get CLIP model name from radio buttons
        if hasattr(self, 'clip_model_button_group'):
            if self.clip_model_openai_radio.isChecked():
                settings['clip_model_name'] = 'openai/clip-vit-base-patch32'
            elif self.clip_model_zer0int_radio.isChecked():
                settings['clip_model_name'] = 'openai/clip-vit-large-patch14'
            else:
                # Default to openai if nothing selected
                settings['clip_model_name'] = 'openai/clip-vit-base-patch32'
        
        # Get background CLIP extraction setting
        settings['background_clip_enabled'] = (
            self.background_clip_enabled_checkbox.isChecked() 
            if hasattr(self, 'background_clip_enabled_checkbox') 
            else False
        )
        # Get "Also gather thumbnails" setting
        settings['background_clip_gather_thumbnails'] = (
            self.background_clip_gather_thumbnails_checkbox.isChecked() 
            if hasattr(self, 'background_clip_gather_thumbnails_checkbox') 
            else True
        )
        # Get "Extract faces" setting
        if (
            hasattr(self, "background_clip_extract_faces_checkbox")
            and getattr(self, "background_clip_extract_faces_container", None) is not None
            and self.background_clip_extract_faces_container.isVisible()
        ):
            settings['background_clip_extract_faces'] = (
                self.background_clip_extract_faces_checkbox.isChecked()
            )
        else:
            settings['background_clip_extract_faces'] = self.original_settings.get(
                'background_clip_extract_faces', False
            )
        
        # Get ResNet model from radio buttons
        if hasattr(self, 'resnet_model_button_group'):
            if self.resnet_model_18_radio.isChecked():
                settings['resnet_model'] = 'resnet18'
            elif self.resnet_model_50_radio.isChecked():
                settings['resnet_model'] = 'resnet50'
            elif self.resnet_model_101_radio.isChecked():
                settings['resnet_model'] = 'resnet101'
            else:
                # Default to resnet18 if nothing selected
                settings['resnet_model'] = 'resnet18'
        
        # Get captioning settings
        if hasattr(self, 'caption_system_prompt_edit'):
            settings['caption_lms_host'] = self.caption_lms_host_edit.text().strip()
            settings['caption_system_prompt'] = self.caption_system_prompt_edit.toPlainText().strip()
            settings['caption_user_prompt'] = self.caption_user_prompt_edit.toPlainText().strip()
            settings['caption_max_words'] = self.caption_max_words_spinbox.value()
            settings['caption_temperature'] = self.caption_temperature_spinbox.value()
        
        if hasattr(self, '_lora_checkboxes'):
            model_key = self._current_lora_model_key()
            self._save_lora_widgets_to_draft(model_key)
            slice_ = self._lora_draft_slice(model_key)
            settings['imagegen_lora_model_key'] = model_key
            settings['imagegen_lora_enabled_ids'] = list(slice_["enabled_ids"])
        
        if hasattr(self, 'theme_preset_combo'):
            tid = self.theme_preset_combo.currentData()
            if tid in ("dark", "light", "user") and hasattr(self, "use_diamonds_checkbox"):
                self._flush_browse_transparency_entry(tid)
            settings['ui_theme'] = self._get_ui_theme_for_save()
            if tid == "user":
                settings['user_theme_colors'] = self._get_user_theme_colors_from_widgets()
            else:
                settings['user_theme_colors'] = merge_user_theme_colors(
                    self.current_settings.get("user_theme_colors")
                )
            if tid == "dark":
                settings['dark_theme_colors'] = self._get_user_theme_colors_from_widgets()
            else:
                settings['dark_theme_colors'] = merge_dark_theme_colors(
                    self.current_settings.get("dark_theme_colors")
                )
            if tid == "light":
                settings['light_theme_colors'] = self._get_user_theme_colors_from_widgets()
            else:
                settings['light_theme_colors'] = merge_light_theme_colors(
                    self.current_settings.get("light_theme_colors")
                )
            settings["browse_transparency_settings"] = copy.deepcopy(
                merge_browse_transparency_settings(self.current_settings.get("browse_transparency_settings"))
            )
        
        return settings
    
    def get_root_directories(self):
        """Get enabled root directories as a list with leading slashes"""
        enabled = []
        if hasattr(self, 'directory_checkboxes'):
            for directory, checkbox in self.directory_checkboxes.items():
                if checkbox.isChecked():
                    # Add leading slash for full path (file_tree_handler expects this format)
                    enabled.append(f"/{directory}")
        else:
            # Default if checkboxes not initialized - add leading slashes
            enabled = [f"/{d}" for d in self.DEFAULT_ROOT_DIRECTORIES]
        return enabled
    
    def get_move_destinations(self):
        """Get destinations as a list of 9 items (None where empty)"""
        destinations = []
        if hasattr(self, 'move_destination_input_fields'):
            for i, field in enumerate(self.move_destination_input_fields):
                text = field.text().strip()
                if text:
                    # Expand ~ to full path before storing
                    full_path = self._display_to_path(text)
                    destinations.append(full_path)
                else:
                    destinations.append(None)
        else:
            # Return default if fields not initialized
            destinations = [None] * 9
        return destinations
    
    def get_exclude_destinations(self):
        """Get exclude destinations as a list of dicts with 'path' and 'enabled' keys"""
        exclude_dirs = []
        if hasattr(self, 'exclude_destination_input_fields') and hasattr(self, 'exclude_destination_checkboxes'):
            for i, field in enumerate(self.exclude_destination_input_fields):
                text = field.text().strip()
                enabled = self.exclude_destination_checkboxes[i].isChecked() if i < len(self.exclude_destination_checkboxes) else False
                if text:
                    # Expand ~ to full path before storing
                    full_path = self._display_to_path(text)
                    exclude_dirs.append({'path': full_path, 'enabled': enabled})
                else:
                    exclude_dirs.append({'path': None, 'enabled': False})
        else:
            # Return default if fields not initialized
            exclude_dirs = [{'path': None, 'enabled': False}] * 9
        return exclude_dirs

    def get_image_creation_directory(self):
        """Get image creation directory as dict with 'path' and 'enabled' keys."""
        enabled = False
        if hasattr(self, "image_creation_directory_checkbox"):
            enabled = self.image_creation_directory_checkbox.isChecked()
        path = None
        if hasattr(self, "image_creation_directory_input_field"):
            text = self.image_creation_directory_input_field.text().strip()
            if text:
                path = self._display_to_path(text)
        return {"path": path, "enabled": enabled}

    def get_temporary_files_directory(self):
        """Get temporary work files directory path, or None when blank (use default)."""
        if hasattr(self, "temporary_files_directory_input_field"):
            text = self.temporary_files_directory_input_field.text().strip()
            if text:
                return self._display_to_path(text)
        return None

    def get_ignore_directories(self):
        """Get ignore directories as a list of dicts with 'path' and 'enabled' keys"""
        ignore_dirs = []
        if hasattr(self, 'ignore_directory_input_fields') and hasattr(self, 'ignore_directory_checkboxes'):
            for i, field in enumerate(self.ignore_directory_input_fields):
                text = field.text().strip()
                enabled = self.ignore_directory_checkboxes[i].isChecked() if i < len(self.ignore_directory_checkboxes) else False
                if text:
                    # Expand ~ to full path before storing
                    full_path = self._display_to_path(text)
                    ignore_dirs.append({'path': full_path, 'enabled': enabled})
                else:
                    ignore_dirs.append({'path': None, 'enabled': False})
        else:
            # Return default if fields not initialized
            ignore_dirs = [{'path': None, 'enabled': False}] * 3
        return ignore_dirs
    
    def get_favorite_directories(self):
        """Get favorite directories as a list of 9 items (None where empty)"""
        favorites = []
        if hasattr(self, 'favorite_destination_input_fields'):
            for i, field in enumerate(self.favorite_destination_input_fields):
                text = field.text().strip()
                if text:
                    # Expand ~ to full path before storing
                    full_path = self._display_to_path(text)
                    favorites.append(full_path)
                else:
                    favorites.append(None)
        else:
            # Return default if fields not initialized
            favorites = [None] * 9
        return favorites
    
    def get_image_extensions(self):
        """Get enabled image extensions as a list"""
        enabled = []
        if hasattr(self, 'extension_checkboxes'):
            for extension, checkbox in self.extension_checkboxes.items():
                if checkbox.isChecked():
                    enabled.append(extension)
        else:
            # Default if checkboxes not initialized
            enabled = self.DEFAULT_IMAGE_EXTENSIONS
        return enabled

    def _get_map_application(self):
        """Get selected map application preference"""
        if not hasattr(self, 'map_app_group'):
            return 'apple_maps'
        
        checked_button = self.map_app_group.checkedButton()
        if checked_button == self.google_maps_radio:
            return 'google_maps'
        elif checked_button == self.google_earth_radio:
            return 'google_earth'
        else:
            return 'apple_maps'  # Default
    
    def _get_similarity_metric(self):
        """Get selected similarity metric as config value"""
        if not hasattr(self, 'similarity_metric_combo'):
            return 'cosine'  # Default
        
        # Map display names to config values
        metric_map = {
            'Cosine': 'cosine',
            'Euclidean': 'euclidean',
            'Manhattan': 'manhattan'
        }
        
        current_text = self.similarity_metric_combo.currentText()
        return metric_map.get(current_text, 'cosine')  # Default to cosine if unknown

    def apply_theme(self):
        """Apply settings-dialog chrome (black + light text for dark/user presets)."""
        self._sync_theme_context()
        self.setStyleSheet(settings_dialog_stylesheet(self._settings_chrome()))
        if hasattr(self, "tab_widget") and self.tab_widget:
            self.tab_widget.refresh_theme_styles()

    def showEvent(self, event):
        """Handle show events to update button state"""
        super().showEvent(event)
        self._capture_theme_snapshot_at_open()
        combo_tid = (
            self.theme_preset_combo.currentData()
            if hasattr(self, "theme_preset_combo")
            else None
        )
        active_tid = getattr(get_active_theme(), "theme_id", "dark")
        if combo_tid in ("dark", "light", "user") and combo_tid != active_tid:
            self._apply_theme_tab_from_dialog()
        else:
            self.apply_theme()
        # Refresh settings from main window to show current state (in case cmd-I was used)
        if self.parent():
            self._sync_overlay_settings_from_window()
        # Set focus to tab bar on initial display
        if getattr(self, 'tab_widget', None):
            QTimer.singleShot(50, lambda: self.tab_widget.button_container.setFocus())
        # Check Option key state when dialog is shown
        self._update_reset_button_text()
        self._update_cache_source_directories_visibility()
        
        # Refresh cache directories if cache management tab is currently selected
        if getattr(self, 'tab_widget', None):
            current_index = self.tab_widget.currentIndex()
            is_cache_tab = current_index == self.tab_widget.indexOf(self.cache_management_tab)
            if is_cache_tab:
                # Refresh cache directories when dialog opens with cache tab selected
                if hasattr(self, 'cache_totals_label'):
                    QTimer.singleShot(100, self._update_cache_totals_label)
                if hasattr(self, 'cache_dirs_text'):
                    QTimer.singleShot(100, self.load_cache_directories_deferred)
        # Update cache totals label with current cache sizes
        if hasattr(self, 'cache_totals_label'):
            self._update_cache_totals_label()
        # Start timer to monitor modifier keys
        self.modifier_check_timer.start()
    
    def hideEvent(self, event):
        """Handle hide events to stop timer"""
        super().hideEvent(event)
        # Stop timer when dialog is hidden
        self.modifier_check_timer.stop()
    
    def eventFilter(self, obj, event):
        """Event filter to catch modifier key changes"""
        if obj == self and event.type() == QEvent.Type.KeyPress:
            # Check modifier state on any key press
            self._check_modifier_state()
        elif obj == self and event.type() == QEvent.Type.KeyRelease:
            # Check modifier state on any key release
            self._check_modifier_state()
        elif obj == self and event.type() == QEvent.Type.FocusIn:
            # Check modifier state when dialog gains focus
            self._check_modifier_state()
        return super().eventFilter(obj, event)
    
    def _check_modifier_state(self):
        """Check Option and Shift key state and update button"""
        # Only check if dialog is visible
        if not self.isVisible():
            return
        
        modifiers = QApplication.keyboardModifiers()
        option_pressed = bool(modifiers & Qt.AltModifier)
        shift_pressed = bool(modifiers & Qt.ShiftModifier)
        
        if option_pressed != self.option_key_pressed or shift_pressed != self.shift_key_pressed:
            self.option_key_pressed = option_pressed
            self.shift_key_pressed = shift_pressed
            self._update_reset_button_text()
    
    def keyPressEvent(self, event):
        """Handle key events"""
        # Close on Escape
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            # Let Qt handle all other keyboard events (Tab, arrows, etc.)
            # Modifier state is checked by timer
            super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event):
        """Handle key release events"""
        # Modifier state is checked by timer
        super().keyReleaseEvent(event)
    
    def _update_reset_button_text(self):
        """Update reset button text based on Option and Shift key state"""
        # Ensure button exists
        if not hasattr(self, 'reset_button') or not self.reset_button:
            return
        
        # Always check current modifier state to handle focus changes
        modifiers = QApplication.keyboardModifiers()
        option_pressed = bool(modifiers & Qt.AltModifier)
        shift_pressed = bool(modifiers & Qt.ShiftModifier)
        self.option_key_pressed = option_pressed
        self.shift_key_pressed = shift_pressed
        
        # Disconnect old handler
        try:
            self.reset_button.clicked.disconnect()
        except TypeError:
            pass  # No connections to disconnect
        
        if option_pressed and shift_pressed:
            # Option+Shift: Load system defaults
            self.reset_button.setText("System Defaults")
            self.reset_button.setToolTip(
                "Reset settings on the current tab to built-in system\n"
                "defaults."
            )
            self.reset_button.clicked.connect(self.load_system_defaults)
        elif option_pressed:
            # Option only: Save as defaults
            self.reset_button.setText("Save as Defaults")
            self.reset_button.setToolTip(
                "Save the current tab's settings as your personal\n"
                "defaults."
            )
            self.reset_button.clicked.connect(self.save_as_defaults)
        else:
            # No modifiers: Reset to defaults (saved or system)
            self.reset_button.setText("Reset to Defaults")
            self.reset_button.setToolTip(
                "Reset settings on the current tab to your saved\n"
                "defaults.\n"
                f"Hold Option ({OPTION_SYMBOL}) for Save as Defaults;\n"
                f"Option+Shift ({SHIFT_SYMBOL}{OPTION_SYMBOL}) for System\n"
                "Defaults."
            )
            self.reset_button.clicked.connect(self.reset_tab_to_defaults)
    
    def resizeEvent(self, event):
        """Debounce-save dialog size when the user resizes."""
        super().resizeEvent(event)
        if not getattr(self, "_settings_dialog_initializing", False):
            self._geometry_save_timer.start()

    def closeEvent(self, event):
        self._persist_settings_dialog_geometry()
        super().closeEvent(event)

    def on_tab_changed(self, index):
        """Handle tab changes to ensure proper sizing"""
        if not getattr(self, "_settings_dialog_initializing", False):
            lora_idx = self.tab_widget.indexOf(self.lora_settings_tab)
            prev_idx = getattr(self, "_settings_tab_prev_index", -1)
            if index == lora_idx:
                self._ensure_lora_tab_ready()
            if (
                prev_idx == lora_idx
                and index != lora_idx
                and hasattr(self, "_lora_checkboxes")
            ):
                if self._flush_lora_tab_to_disk():
                    mw = self.parent()
                    if mw is not None and hasattr(mw, "refresh_open_imagegen_lora_combos"):
                        mw.refresh_open_imagegen_lora_combos()
            self._settings_tab_prev_index = index

        # Lazy-load Faces tab on first visit (face_recognition import is slow)
        is_faces_tab = index == self.tab_widget.indexOf(self.faces_tab)
        is_cache_tab = index == self.tab_widget.indexOf(self.cache_management_tab)
        is_lora_tab = (
            getattr(self, "_show_lora_settings_tab", False)
            and index == self.tab_widget.indexOf(self.lora_settings_tab)
        )
        if getattr(self, "_lora_add_button", None):
            self._lora_add_button.setVisible(is_lora_tab)
        # Hide reset button and option note on cache tab and faces tab (before early return)
        hide_reset_row = is_cache_tab or is_faces_tab
        if getattr(self, 'reset_button', None):
            self.reset_button.setVisible(not hide_reset_row)
        if getattr(self, 'option_note', None):
            self.option_note.setVisible(not hide_reset_row)
        if not hide_reset_row:
            self._update_reset_button_text()

        if is_faces_tab and not getattr(self, '_faces_tab_setup_done', False):
            self._ensure_faces_tab_loaded()
            return  # _ensure_faces_tab_loaded handles resize when done

        # Faces tab already loaded and auto-extract requested (e.g. from context menu)
        if is_faces_tab and getattr(self, '_auto_extract_faces', False):
            self._auto_extract_faces = False
            QTimer.singleShot(0, self._faces_examine_current_image)

        # Use a timer to delay the resize to allow the tab content to load; then persist fitted size
        if not getattr(self, "_settings_dialog_initializing", False):
            QTimer.singleShot(50, self._adjust_size_and_persist_geometry)
        
        # Update cache totals label and source directories when cache management tab is shown
        if is_cache_tab:
            self._update_cache_source_directories_visibility()
            if hasattr(self, 'cache_totals_label'):
                QTimer.singleShot(100, self._update_cache_totals_label)
            # Update source directories list
            if hasattr(self, 'cache_dirs_text'):
                QTimer.singleShot(100, self.load_cache_directories_deferred)
    

    def refresh_cache_statistics(self):
        """Refresh cache statistics display"""
        try:
            if self.parent() and hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                stats = self.parent().cache_manager.get_cache_statistics()
                
                # Update directory list (debug mode only)
                if hasattr(self, 'cache_dirs_text'):
                    dirs_text = "\n".join(stats['cache_directories'])
                    if not dirs_text:
                        dirs_text = "No cache directories found"
                    self.cache_dirs_text.setText(dirs_text)
                
                # Update statistics display (only if stats are enabled)
                if hasattr(self, 'cache_stats_label'):
                    # Format statistics for display
                    stats_text = f"""Total Cached Items: {stats['total_cached_items']:,}
Thumbnail Cache: {stats['thumbnail_cache_items']:,} items
Metadata Cache: {stats['metadata_cache_items']:,} items
Full Image Cache: {stats['fullimage_cache_items']:,} items
Disk Usage: {stats['disk_usage_mb']:.1f} MB

Hit Rates:
  Thumbnails: {stats['hit_rates']['thumbnail']}
  Metadata: {stats['hit_rates']['metadata']}
  Full Images: {stats['hit_rates']['fullimage']}

Total Requests:
  Thumbnails: {stats['total_requests']['thumbnail']:,}
  Metadata: {stats['total_requests']['metadata']:,}
  Full Images: {stats['total_requests']['fullimage']:,}"""
                    
                    self.cache_stats_label.setText(stats_text)
                
            else:
                if hasattr(self, 'cache_stats_label'):
                    self.cache_stats_label.setText("Cache manager not available")
                if hasattr(self, 'cache_dirs_text'):
                    self.cache_dirs_text.setText("Cache manager not available")
                
        except Exception as e:
            if hasattr(self, 'cache_stats_label'):
                self.cache_stats_label.setText("Error loading cache statistics")
            if hasattr(self, 'cache_dirs_text'):
                self.cache_dirs_text.setText("Error loading cache directories")

    def clear_all_caches(self):
        """Clear all caches and force rebuild"""
        # Show confirmation dialog
        reply = show_styled_question(
            self,
            "Clear All Caches",
            "This will clear all thumbnail, metadata, and full image caches.\n\n"
            "The application will rebuild caches as needed, which may temporarily slow down performance.\n\n"
            "Are you sure you want to continue?",
            default_no=True
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Clear caches in parent window if available
                if self.parent():
                    # Clear main cache manager
                    if hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                        self.parent().cache_manager.clear_cache("all")
                # Clear face cache (not in cache_manager)
                try:
                    from config import get_config
                    config = get_config()
                    face_cache_dir = config.image_recognition_cache_dir / "face_cache"
                    for p in (face_cache_dir / "data").glob("*.json") if (face_cache_dir / "data").exists() else []:
                        try:
                            p.unlink()
                        except Exception:
                            pass
                    idx = face_cache_dir / "index.json"
                    if idx.exists():
                        idx.unlink()
                    from faces.face_scan_runner import clear_scanned_dir_cache
                    clear_scanned_dir_cache()
                except Exception:
                    pass
                    
                # Emit signal to notify parent
                self.cache_cleared.emit()
                
                # Show success message
                show_styled_information(
                    self,
                    "Cache Cleared",
                    "All caches have been cleared successfully.\n\n"
                    "The application will rebuild caches as needed."
                )
                
                # Refresh cache statistics (only if stats are enabled)
                if hasattr(self, 'cache_stats_label'):
                    self.refresh_cache_statistics()
                elif hasattr(self, 'cache_dirs_text'):
                    # Just refresh directories when stats are disabled
                    try:
                        if self.parent() and hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                            stats = self.parent().cache_manager.get_cache_statistics()
                            dirs_text = "\n".join(stats['cache_directories'])
                            if not dirs_text:
                                dirs_text = "No cache directories found"
                            self.cache_dirs_text.setText(dirs_text)
                        else:
                            self.cache_dirs_text.setText("Cache manager not available")
                    except Exception as e:
                        print(f"Error refreshing cache directories: {e}")
                        self.cache_dirs_text.setText("Error loading cache directories")
                
                # Update cache totals label to reflect new sizes
                if hasattr(self, 'cache_totals_label'):
                    self._update_cache_totals_label()
                
            except Exception as e:
                # Show error message
                show_styled_critical(
                    self,
                    "Error Clearing Cache",
                    f"An error occurred while clearing the cache:\n\n{str(e)}"
                ) 

    def clear_thumbnail_cache(self):
        """Clear only the thumbnail cache and force rebuild"""
        # Show confirmation dialog
        reply = show_styled_question(
            self,
            "Clear Thumbnail Cache",
            "This will clear only the thumbnail cache.\n\n"
            "The application will rebuild thumbnails as needed, which may temporarily slow down performance.\n\n"
            "Are you sure you want to continue?",
            default_no=False
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Clear thumbnail cache in parent window if available
                if self.parent():
                    # Clear main cache manager
                    if hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                        self.parent().cache_manager.clear_cache("thumbnails")
                    
                # Emit signal to notify parent
                self.cache_cleared.emit()
                
                # Show success message
                # show_styled_information(
                #     self,
                #     "Thumbnail Cache Cleared",
                #     "The thumbnail cache has been cleared successfully.\n\n"
                #     "The application will rebuild thumbnails as needed."
                # )
                
                # Refresh cache statistics (only if stats are enabled)
                if hasattr(self, 'cache_stats_label'):
                    self.refresh_cache_statistics()
                elif hasattr(self, 'cache_dirs_text'):
                    # Just refresh directories when stats are disabled
                    try:
                        if self.parent() and hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager:
                            stats = self.parent().cache_manager.get_cache_statistics()
                            dirs_text = "\n".join(stats['cache_directories'])
                            if not dirs_text:
                                dirs_text = "No cache directories found"
                            self.cache_dirs_text.setText(dirs_text)
                        else:
                            self.cache_dirs_text.setText("Cache manager not available")
                    except Exception as e:
                        print(f"Error refreshing cache directories: {e}")
                        self.cache_dirs_text.setText("Error loading cache directories")
                
                # Update cache totals label to reflect new sizes
                if hasattr(self, 'cache_totals_label'):
                    self._update_cache_totals_label()
                
            except Exception as e:
                # Show error message
                show_styled_critical(
                    self,
                    "Error Clearing Thumbnail Cache",
                    f"An error occurred while clearing the thumbnail cache:\n\n{str(e)}"
                ) 

    
    def clear_image_recognition_cache(self):
        """Clear image recognition (CNN/CLIP) feature cache"""
        # Show confirmation dialog
        reply = show_styled_question(
            self,
            "Clear Image Recognition Cache",
            "This will clear all cached CNN and CLIP feature data.\n\n"
            "The application will recalculate features as needed, which may temporarily slow down similarity searches.\n\n"
            "Are you sure you want to continue?",
            default_no=True
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Clear the persistent cache using the feature cache manager
                from cache.feature_cache_manager import FeatureCacheManager
                cache_manager = FeatureCacheManager()
                cache_manager.clear_all()
                
                # Also clear in-memory caches if parent window has similarity sorter
                if self.parent() and hasattr(self.parent(), 'cnn_image_similarity_sorter'):
                    sorter = self.parent().cnn_image_similarity_sorter
                    if hasattr(sorter, '_feature_cache'):
                        sorter._feature_cache.clear()
                    if hasattr(sorter, '_clip_feature_cache'):
                        sorter._clip_feature_cache.clear()
                    # Also clear the persistent cache reference if it exists
                    if hasattr(sorter, 'feature_cache') and sorter.feature_cache:
                        sorter.feature_cache.clear_all()
                
                # Restart background worker so it gets fresh state and will repopulate disk
                # (worker keeps stale in-memory cache otherwise, never re-extracts)
                if self.parent() and hasattr(self.parent(), 'background_clip_controller'):
                    controller = self.parent().background_clip_controller
                    if controller.enabled:
                        controller.stop_process()
                        controller.start_process()  # Restart immediately to repopulate
                # Clear importer tracking so new cache files will be imported
                if self.parent() and hasattr(self.parent(), 'background_cache_importer'):
                    self.parent().background_cache_importer.clear_imported_tracking()
                
                # Update cache totals label to reflect new sizes
                if hasattr(self, 'cache_totals_label'):
                    self._update_cache_totals_label()
                
                # Show success message
                show_styled_information(
                    self,
                    "Image Recognition Cache Cleared",
                    "Image recognition cache has been cleared successfully."
                )
                
            except Exception as e:
                # Show error message
                show_styled_critical(
                    self,
                    "Error Clearing Image Recognition Cache",
                    f"An error occurred while clearing the image recognition cache:\n\n{str(e)}"
                )

    def clear_face_cache(self):
        """Clear face cache (encodings used for face search) and face sample thumbnails."""
        reply = show_styled_question(
            self,
            "Clear Face Cache",
            "This will delete cached face encodings and face sample thumbnails under the face cache directory.\n\n"
            "After clearing, you may need to run Cache Faces again (or re-run searches).\n\n"
            "Are you sure you want to continue?",
            default_no=True,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from config import get_config
            config = get_config()
            face_cache_dir = config.image_recognition_cache_dir / "face_cache"
            index_path = face_cache_dir / "index.json"
            data_dir = face_cache_dir / "data"

            # Remove face encodings (index + data/*.json).
            if data_dir.exists():
                for p in data_dir.glob("*.json"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
            if index_path.exists():
                try:
                    index_path.unlink()
                except Exception:
                    pass

            # Clear in-memory directory scan cache so cmd-= will re-cache (not skip) after clear
            try:
                from faces.face_scan_runner import clear_scanned_dir_cache
                clear_scanned_dir_cache()
            except Exception:
                pass

            # Clear face sample thumbnails (Settings Faces tab 96x96 crops).
            sample_thumbs_removed = 0
            try:
                from faces.face_sample_cache import clear_all as clear_sample_thumbs
                sample_thumbs_removed = clear_sample_thumbs()
            except Exception:
                pass

            # Refresh UI totals
            if hasattr(self, "cache_totals_label"):
                self._update_cache_totals_label()

            msg = "Face cache has been cleared successfully."
            if sample_thumbs_removed > 0:
                msg += f"\n\nRemoved {sample_thumbs_removed} face sample thumbnail(s)."
            show_styled_information(
                self,
                "Face Cache Cleared",
                msg
            )
        except Exception as e:
            show_styled_critical(
                self,
                "Error Clearing Face Cache",
                f"An error occurred while clearing face cache:\n\n{str(e)}"
            )

    def _calculate_cache_sizes(self) -> dict:
        """Calculate total disk space used by thumbnails, CNN, and CLIP caches"""
        sizes = {
            'thumbnails': 0,
            'cnn': 0,
            'clip': 0,
            'total': 0
        }
        
        try:
            parent_window = self.parent()
            if not parent_window:
                return sizes
            
            # Calculate thumbnail cache size
            if hasattr(parent_window, 'cache_manager') and parent_window.cache_manager:
                cache_manager = parent_window.cache_manager
                thumbnail_cache_dir = cache_manager.thumbnail_cache_dir
                if os.path.exists(thumbnail_cache_dir):
                    try:
                        for filename in os.listdir(thumbnail_cache_dir):
                            if filename.endswith('.jpg'):
                                thumb_path = os.path.join(thumbnail_cache_dir, filename)
                                try:
                                    sizes['thumbnails'] += os.path.getsize(thumb_path)
                                except (OSError, IOError):
                                    pass
                    except Exception:
                        pass
            
            # Calculate CNN and CLIP cache sizes - scan ALL models, not just currently loaded
            try:
                from config import get_config
                config = get_config()
                cache_dir = config.image_recognition_cache_dir
                
                if cache_dir.exists():
                    # Find all CNN cache directories and files
                    for subdir in cache_dir.iterdir():
                        if subdir.is_dir():
                            if subdir.name.startswith('cnn_features_'):
                                # Count all .npz files in this CNN model directory
                                for cache_file in subdir.rglob('*.npz'):
                                    try:
                                        if cache_file.is_file():
                                            sizes['cnn'] += cache_file.stat().st_size
                                    except Exception:
                                        pass
                            elif subdir.name.startswith('clip_features_'):
                                # Count all .npz files in this CLIP model directory
                                for cache_file in subdir.rglob('*.npz'):
                                    try:
                                        if cache_file.is_file():
                                            sizes['clip'] += cache_file.stat().st_size
                                    except Exception:
                                        pass
                    
                    # Add all index file sizes
                    for index_file in cache_dir.glob('cnn_index_*.json'):
                        try:
                            sizes['cnn'] += index_file.stat().st_size
                        except Exception:
                            pass
                    for index_file in cache_dir.glob('clip_index_*.json'):
                        try:
                            sizes['clip'] += index_file.stat().st_size
                        except Exception:
                            pass
            except Exception as e:
                print(f"Error calculating cache sizes: {e}")
            
            sizes['total'] = sizes['thumbnails'] + sizes['cnn'] + sizes['clip']
        except Exception as e:
            print(f"Error calculating cache sizes: {e}")
        
        return sizes
    
    def _update_cache_totals_label(self):
        """Update the cache totals label text with current cache sizes"""
        try:
            sizes = self._calculate_cache_sizes()
            if sizes['total'] > 0:
                thumb_str = format_file_size(sizes['thumbnails'])
                cnn_str = format_file_size(sizes['cnn'])
                clip_str = format_file_size(sizes['clip'])
                total_str = format_file_size(sizes['total'])
                self.cache_totals_label.setText(f"Total {total_str}: {thumb_str} Thumbs, {cnn_str} Similarity, {clip_str} Search")
            else:
                self.cache_totals_label.setText("Total: No cache data")
        except Exception as e:
            print(f"Error updating cache totals label: {e}")
            self.cache_totals_label.setText("Total: Error loading cache sizes")
    
    def refresh_cache_tab(self):
        """Refresh all sections of the cache tab"""
        # Update cache totals label
        if hasattr(self, 'cache_totals_label'):
            self._update_cache_totals_label()
        
        # Update source directories list
        if hasattr(self, 'cache_dirs_text'):
            self.load_cache_directories_deferred()
        
        # Update cache statistics if enabled
        if hasattr(self, 'cache_stats_label'):
            self.refresh_cache_statistics()
    

    def scrub_caches(self):
        """Scrub caches to remove entries for images that no longer exist"""
        # Create progress dialog
        progress_dialog = QProgressDialog("Scrubbing caches...", None, 0, 100, self)
        progress_dialog.setWindowTitle("Scrub Caches")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setCancelButton(None)  # No cancel button - must complete
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()
        QApplication.processEvents()
        
        try:
            removed_cnn = 0
            removed_clip = 0
            removed_face = 0
            removed_thumbnails = 0
            
            # Get parent window and cache managers
            parent_window = self.parent()
            if not parent_window:
                progress_dialog.close()
                return
            
            # Step 1: Scrub CNN and CLIP feature caches - scan ALL models, not just currently loaded
            progress_dialog.setLabelText("Checking CNN and CLIP feature caches (all models)...")
            progress_dialog.setValue(10)
            QApplication.processEvents()
            
            try:
                from config import get_config
                config = get_config()
                cache_dir = config.image_recognition_cache_dir
                
                if cache_dir.exists():
                    # Find all CNN and CLIP index files
                    cnn_index_files = list(cache_dir.glob('cnn_index_*.json'))
                    clip_index_files = list(cache_dir.glob('clip_index_*.json'))
                    total_index_files = len(cnn_index_files) + len(clip_index_files)
                    
                    if total_index_files > 0:
                        progress_dialog.setMaximum(80)  # Reserve 20% for flushing and updating
                        progress_dialog.setValue(15)
                        QApplication.processEvents()
                        
                        # Process all CNN index files
                        for idx, cnn_index_file in enumerate(cnn_index_files):
                            progress = 15 + int(30 * idx / max(1, len(cnn_index_files)))
                            progress_dialog.setValue(progress)
                            progress_dialog.setLabelText(f"Checking CNN cache ({idx+1}/{len(cnn_index_files)})...")
                            QApplication.processEvents()
                            
                            try:
                                import json
                                import tempfile
                                import shutil
                                import fcntl
                                
                                # Read index file with lock to prevent conflicts
                                lock_file = cnn_index_file.with_suffix('.lock')
                                lock_file.touch(exist_ok=True)
                                
                                cnn_index = {}
                                with open(lock_file, 'r+') as lock_fd:
                                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                                    try:
                                        if cnn_index_file.exists():
                                            with open(cnn_index_file, 'r', encoding='utf-8') as f:
                                                cnn_index = json.load(f)
                                    finally:
                                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                                
                                if not isinstance(cnn_index, dict):
                                    print(f"Warning: CNN index {cnn_index_file} is not a valid dictionary, skipping")
                                    continue
                                
                                # Check each path - use consistent normalization
                                paths_to_remove = []
                                original_count = len(cnn_index)
                                
                                for path in list(cnn_index.keys()):  # Use list() to avoid modification during iteration
                                    try:
                                        # Normalize path the same way cache keys are normalized
                                        # Cache keys use Path(path).resolve(), so we should check the same way
                                        normalized_path = str(Path(path).resolve())
                                        
                                        # Check if file exists
                                        if not os.path.exists(normalized_path):
                                            paths_to_remove.append(path)
                                        else:
                                            # Also verify the path matches (handle case sensitivity on macOS)
                                            # If the normalized path differs from the original, it might be a symlink issue
                                            # But we'll trust the normalized path since that's what cache keys use
                                            pass
                                    except (OSError, ValueError) as e:
                                        # Path is invalid or can't be resolved - mark for removal
                                        print(f"Warning: Invalid path in CNN index: {path} ({e})")
                                        paths_to_remove.append(path)
                                
                                # Remove invalid entries
                                if paths_to_remove:
                                    removed_cnn += len(paths_to_remove)
                                    for path in paths_to_remove:
                                        cnn_index.pop(path, None)
                                
                                # Always write the index back (even if empty) to ensure consistency
                                # Use file locking to prevent conflicts with background processes
                                with open(lock_file, 'r+') as lock_fd:
                                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                                    try:
                                        # Write updated index atomically
                                        from prowser_temp_files import prowser_mkdtemp
                                        temp_dir = prowser_mkdtemp(prefix="cnn_index_scrub_")
                                        temp_file = Path(temp_dir) / "index.json"
                                        try:
                                            with open(temp_file, 'w', encoding='utf-8') as f:
                                                json.dump(cnn_index, f, indent=2)
                                            temp_file.replace(cnn_index_file)
                                            if paths_to_remove:
                                                print(f"Scrubbed CNN index {cnn_index_file}: removed {len(paths_to_remove)}/{original_count} entries, {len(cnn_index)} remaining")
                                        finally:
                                            shutil.rmtree(temp_dir, ignore_errors=True)
                                    finally:
                                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                            except Exception as e:
                                print(f"Error processing CNN index {cnn_index_file}: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        # Process all CLIP index files
                        for idx, clip_index_file in enumerate(clip_index_files):
                            progress = 45 + int(30 * idx / max(1, len(clip_index_files)))
                            progress_dialog.setValue(progress)
                            progress_dialog.setLabelText(f"Checking CLIP cache ({idx+1}/{len(clip_index_files)})...")
                            QApplication.processEvents()
                            
                            try:
                                import json
                                import tempfile
                                import shutil
                                import fcntl
                                
                                # Read index file with lock to prevent conflicts
                                lock_file = clip_index_file.with_suffix('.lock')
                                lock_file.touch(exist_ok=True)
                                
                                clip_index = {}
                                with open(lock_file, 'r+') as lock_fd:
                                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                                    try:
                                        if clip_index_file.exists():
                                            with open(clip_index_file, 'r', encoding='utf-8') as f:
                                                clip_index = json.load(f)
                                    finally:
                                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                                
                                if not isinstance(clip_index, dict):
                                    print(f"Warning: CLIP index {clip_index_file} is not a valid dictionary, skipping")
                                    continue
                                
                                # Check each path - use consistent normalization
                                paths_to_remove = []
                                original_count = len(clip_index)
                                
                                for path in list(clip_index.keys()):  # Use list() to avoid modification during iteration
                                    try:
                                        # Normalize path the same way cache keys are normalized
                                        # Cache keys use Path(path).resolve(), so we should check the same way
                                        normalized_path = str(Path(path).resolve())
                                        
                                        # Check if file exists
                                        if not os.path.exists(normalized_path):
                                            paths_to_remove.append(path)
                                        else:
                                            # Also verify the path matches (handle case sensitivity on macOS)
                                            # If the normalized path differs from the original, it might be a symlink issue
                                            # But we'll trust the normalized path since that's what cache keys use
                                            pass
                                    except (OSError, ValueError) as e:
                                        # Path is invalid or can't be resolved - mark for removal
                                        print(f"Warning: Invalid path in CLIP index: {path} ({e})")
                                        paths_to_remove.append(path)
                                
                                # Remove invalid entries
                                if paths_to_remove:
                                    removed_clip += len(paths_to_remove)
                                    for path in paths_to_remove:
                                        clip_index.pop(path, None)
                                
                                # Always write the index back (even if empty) to ensure consistency
                                # Use file locking to prevent conflicts with background processes
                                with open(lock_file, 'r+') as lock_fd:
                                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                                    try:
                                        # Write updated index atomically
                                        from prowser_temp_files import prowser_mkdtemp
                                        temp_dir = prowser_mkdtemp(prefix="clip_index_scrub_")
                                        temp_file = Path(temp_dir) / "index.json"
                                        try:
                                            with open(temp_file, 'w', encoding='utf-8') as f:
                                                json.dump(clip_index, f, indent=2)
                                            temp_file.replace(clip_index_file)
                                            if paths_to_remove:
                                                print(f"Scrubbed CLIP index {clip_index_file}: removed {len(paths_to_remove)}/{original_count} entries, {len(clip_index)} remaining")
                                        finally:
                                            shutil.rmtree(temp_dir, ignore_errors=True)
                                    finally:
                                        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                            except Exception as e:
                                print(f"Error processing CLIP index {clip_index_file}: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        # Also remove invalid entries from in-memory cache if feature_cache is loaded
                        if (hasattr(parent_window, 'cnn_image_similarity_sorter') and 
                            parent_window.cnn_image_similarity_sorter and
                            hasattr(parent_window.cnn_image_similarity_sorter, 'feature_cache') and
                            parent_window.cnn_image_similarity_sorter.feature_cache):
                            feature_cache = parent_window.cnn_image_similarity_sorter.feature_cache
                            with QMutexLocker(feature_cache.cache_mutex):
                                # Remove invalid entries from in-memory caches
                                # Note: cache_key is already normalized (uses Path.resolve()), so we can check directly
                                cnn_keys_to_remove = []
                                for cache_key in list(feature_cache.cnn_cache.keys()):
                                    try:
                                        # Cache keys are already normalized paths, so check directly
                                        # But verify the path still resolves correctly
                                        normalized_check = str(Path(cache_key).resolve())
                                        if normalized_check != cache_key:
                                            # Path normalization changed - this shouldn't happen but handle it
                                            print(f"Warning: CNN cache key normalization mismatch: {cache_key} -> {normalized_check}")
                                        if not os.path.exists(cache_key):
                                            cnn_keys_to_remove.append(cache_key)
                                    except Exception as e:
                                        print(f"Warning: Error checking CNN cache key {cache_key}: {e}")
                                        cnn_keys_to_remove.append(cache_key)
                                
                                if cnn_keys_to_remove:
                                    for cache_key in cnn_keys_to_remove:
                                        if cache_key in feature_cache.cnn_cache:
                                            del feature_cache.cnn_cache[cache_key]
                                            dir_hash = feature_cache._get_directory_hash(cache_key)
                                            feature_cache._cnn_dirty_dirs.add(dir_hash)
                                            feature_cache._cnn_dirty = True
                                
                                clip_keys_to_remove = []
                                for cache_key in list(feature_cache.clip_cache.keys()):
                                    try:
                                        # Cache keys are already normalized paths, so check directly
                                        # But verify the path still resolves correctly
                                        normalized_check = str(Path(cache_key).resolve())
                                        if normalized_check != cache_key:
                                            # Path normalization changed - this shouldn't happen but handle it
                                            print(f"Warning: CLIP cache key normalization mismatch: {cache_key} -> {normalized_check}")
                                        if not os.path.exists(cache_key):
                                            clip_keys_to_remove.append(cache_key)
                                    except Exception as e:
                                        print(f"Warning: Error checking CLIP cache key {cache_key}: {e}")
                                        clip_keys_to_remove.append(cache_key)
                                
                                if clip_keys_to_remove:
                                    for cache_key in clip_keys_to_remove:
                                        if cache_key in feature_cache.clip_cache:
                                            del feature_cache.clip_cache[cache_key]
                                            dir_hash = feature_cache._get_directory_hash(cache_key)
                                            feature_cache._clip_dirty_dirs.add(dir_hash)
                                            feature_cache._clip_dirty = True
                    
                    # Scrub face cache (independent of CNN/CLIP)
                    try:
                        from faces.face_cache import scrub_stale_entries
                        removed_face = scrub_stale_entries()
                        if removed_face > 0:
                            print(f"Scrubbed face cache: removed {removed_face} entries")
                    except Exception as e:
                        print(f"Error scrubbing face cache: {e}")
                        import traceback
                        traceback.print_exc()
            except Exception as e:
                print(f"Error scrubbing CNN/CLIP caches: {e}")
                import traceback
                traceback.print_exc()
            
            # Step 2: Scrub thumbnail and metadata caches
            progress_dialog.setLabelText("Checking thumbnail and metadata caches...")
            progress_dialog.setValue(80)
            QApplication.processEvents()
            
            if hasattr(parent_window, 'cache_manager') and parent_window.cache_manager:
                cache_manager = parent_window.cache_manager
                thumbnail_cache_dir = cache_manager.thumbnail_cache_dir
                
                # Import MIN_THUMBNAIL_SIZE
                from thumbnails.thumbnail_constants import MIN_THUMBNAIL_SIZE
                
                # Iterate through metadata cache to find invalid entries
                progress_dialog.setLabelText("Checking metadata cache entries...")
                progress_dialog.setValue(82)
                QApplication.processEvents()
                
                metadata_keys_to_remove = []
                thumbnails_to_remove = []
                valid_thumbnails = set()  # Track thumbnails we want to keep
                
                # Load ALL metadata from disk and merge with in-memory (in-memory takes precedence)
                # Scrub must use full metadata - in-memory cache alone misses most entries
                from cache.image_cache import ImageMetadata
                all_metadata_cache = {}
                metadata_cache_file = cache_manager.metadata_cache_file
                if os.path.exists(metadata_cache_file):
                    try:
                        with open(metadata_cache_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            for ck, metadata_dict in data.items():
                                try:
                                    all_metadata_cache[ck] = ImageMetadata(**metadata_dict)
                                except Exception:
                                    continue
                    except Exception as e:
                        print(f"Error loading metadata cache for scrub: {e}")
                with QMutexLocker(cache_manager.cache_mutex):
                    all_metadata_cache.update(cache_manager.metadata_cache)
                metadata_entries = list(all_metadata_cache.items())
                
                total_metadata = len(metadata_entries)
                if total_metadata > 0:
                    progress_dialog.setMaximum(95)  # Reserve 5% for flushing
                    checked = 0
                    
                    # Get list of thumbnail files once (if directory exists)
                    thumbnail_files = []
                    if os.path.exists(thumbnail_cache_dir):
                        try:
                            thumbnail_files = [f for f in os.listdir(thumbnail_cache_dir) if f.endswith('.jpg')]
                        except Exception as e:
                            print(f"Error listing thumbnail cache directory: {e}")
                    
                    for cache_key, metadata in metadata_entries:
                        checked += 1
                        if checked % 100 == 0:
                            progress = 82 + int(10 * checked / total_metadata)
                            progress_dialog.setValue(progress)
                            progress_dialog.setLabelText(f"Checking metadata cache entries... ({checked}/{total_metadata})")
                            QApplication.processEvents()
                        
                        # Reconstruct file path from metadata
                        # cache_key is a hash, not a path, so we need to use metadata
                        if not hasattr(metadata, 'source_directory') or not hasattr(metadata, 'filename'):
                            # Invalid metadata format, mark for removal
                            metadata_keys_to_remove.append(cache_key)
                            continue
                        
                        if not metadata.source_directory or metadata.source_directory == "Unknown":
                            # No valid source directory, mark for removal
                            metadata_keys_to_remove.append(cache_key)
                            continue
                        
                        # Reconstruct the full file path
                        image_path = os.path.join(metadata.source_directory, metadata.filename)
                        
                        # Check if original file exists
                        if not os.path.exists(image_path):
                            metadata_keys_to_remove.append(cache_key)
                            
                            # Find associated thumbnail files and mark for removal
                            # cache_key is already the base_cache_key (hash) used for thumbnails
                            base_cache_key = cache_key
                            
                            # Look for thumbnail files matching this cache key
                            for filename in thumbnail_files:
                                # Check if this thumbnail belongs to this cache key
                                # Thumbnail format: {base_cache_key}_{size}.jpg
                                if filename.startswith(base_cache_key + '_') or filename == base_cache_key + '.jpg':
                                    thumb_path = os.path.join(thumbnail_cache_dir, filename)
                                    if thumb_path not in thumbnails_to_remove:
                                        thumbnails_to_remove.append(thumb_path)
                        else:
                            # File exists - check if thumbnails are correct size
                            # cache_key is already the base_cache_key (hash) used for thumbnails
                            base_cache_key = cache_key
                            
                            for filename in thumbnail_files:
                                if filename.startswith(base_cache_key + '_'):
                                    # Extract size from filename: {base_cache_key}_{size}.jpg
                                    try:
                                        size_part = filename.replace('.jpg', '').split('_')[-1]
                                        thumbnail_size = int(size_part)
                                        thumb_path = os.path.join(thumbnail_cache_dir, filename)
                                        
                                        if thumbnail_size == MIN_THUMBNAIL_SIZE:
                                            # This is a valid thumbnail - mark it as valid
                                            valid_thumbnails.add(filename)
                                        else:
                                            # Wrong size - mark for removal
                                            if thumb_path not in thumbnails_to_remove:
                                                thumbnails_to_remove.append(thumb_path)
                                    except (ValueError, IndexError):
                                        # Can't parse size, skip
                                        pass
                    
                    # Remove invalid metadata entries
                    if metadata_keys_to_remove:
                        progress_dialog.setLabelText(f"Removing {len(metadata_keys_to_remove)} invalid metadata entries...")
                        progress_dialog.setValue(90)
                        QApplication.processEvents()
                        
                        with QMutexLocker(cache_manager.cache_mutex):
                            for cache_key in metadata_keys_to_remove:
                                if cache_key in cache_manager.metadata_cache:
                                    del cache_manager.metadata_cache[cache_key]
                    
                    # Also scan all thumbnail files for orphaned ones and wrong sizes
                    # Only check thumbnails that weren't already processed in the metadata loop
                    progress_dialog.setLabelText("Checking for orphaned and wrong-size thumbnails...")
                    progress_dialog.setValue(91)
                    QApplication.processEvents()
                    
                    # Track which base_cache_keys have valid metadata AND existing files
                    # Use all_metadata_cache (disk+memory) minus removed entries - not just in-memory
                    valid_base_cache_keys = set()
                    metadata_keys_removed_set = set(metadata_keys_to_remove)
                    for cache_key, metadata in all_metadata_cache.items():
                        if cache_key in metadata_keys_removed_set:
                            continue
                        # Reconstruct file path from metadata
                        if (hasattr(metadata, 'source_directory') and 
                            hasattr(metadata, 'filename') and
                            metadata.source_directory and 
                            metadata.source_directory != "Unknown"):
                            image_path = os.path.join(metadata.source_directory, metadata.filename)
                            if os.path.exists(image_path):
                                valid_base_cache_keys.add(cache_key)
                    
                    # Check all thumbnail files that we haven't already marked as valid or for removal
                    for filename in thumbnail_files:
                        # Skip thumbnails we've already marked as valid
                        if filename in valid_thumbnails:
                            continue
                        
                        # Skip thumbnails already marked for removal
                        thumb_path = os.path.join(thumbnail_cache_dir, filename)
                        if thumb_path in thumbnails_to_remove:
                            continue
                            
                        if filename.endswith('.jpg'):
                            # Extract base_cache_key and size from filename
                            try:
                                name_without_ext = filename.replace('.jpg', '')
                                parts = name_without_ext.split('_')
                                if len(parts) >= 2:
                                    thumbnail_size = int(parts[-1])
                                    base_cache_key = '_'.join(parts[:-1])
                                    
                                    # Remove if wrong size
                                    if thumbnail_size != MIN_THUMBNAIL_SIZE:
                                        if thumb_path not in thumbnails_to_remove:
                                            thumbnails_to_remove.append(thumb_path)
                                    # Remove if orphaned (no valid metadata for existing file)
                                    elif base_cache_key not in valid_base_cache_keys:
                                        if thumb_path not in thumbnails_to_remove:
                                            thumbnails_to_remove.append(thumb_path)
                            except (ValueError, IndexError):
                                # Can't parse filename - might be old format, remove it
                                if thumb_path not in thumbnails_to_remove:
                                    thumbnails_to_remove.append(thumb_path)
                    
                    # Remove orphaned and wrong-size thumbnail files
                    if thumbnails_to_remove:
                        progress_dialog.setLabelText(f"Removing {len(thumbnails_to_remove)} invalid thumbnail files...")
                        progress_dialog.setValue(92)
                        QApplication.processEvents()
                        
                        for thumb_path in thumbnails_to_remove:
                            try:
                                if os.path.exists(thumb_path):
                                    os.unlink(thumb_path)
                                    removed_thumbnails += 1
                            except Exception as e:
                                print(f"Error removing thumbnail {thumb_path}: {e}")
            
            # Step 3: Flush caches to disk
            progress_dialog.setLabelText("Writing caches to disk...")
            progress_dialog.setValue(95)
            QApplication.processEvents()
            
            # Flush feature caches
            if hasattr(parent_window, 'cnn_image_similarity_sorter') and parent_window.cnn_image_similarity_sorter:
                sorter = parent_window.cnn_image_similarity_sorter
                if hasattr(sorter, 'feature_cache') and sorter.feature_cache:
                    sorter.feature_cache.flush_caches(async_flush=False)
            
            # Flush metadata cache
            if hasattr(parent_window, 'cache_manager') and parent_window.cache_manager:
                cache_manager = parent_window.cache_manager
                cache_manager.save_metadata_cache(force=True)
            
            # Step 4: Update source directories
            progress_dialog.setLabelText("Updating cache information...")
            progress_dialog.setValue(100)
            QApplication.processEvents()
            
            # Update source directories display
            if hasattr(self, 'cache_dirs_text'):
                try:
                    if parent_window and hasattr(parent_window, 'cache_manager') and parent_window.cache_manager:
                        stats = parent_window.cache_manager.get_cache_statistics()
                        dirs_text = "\n".join(stats['cache_directories'])
                        if not dirs_text:
                            dirs_text = "No cache directories found"
                        self.cache_dirs_text.setText(dirs_text)
                    else:
                        self.cache_dirs_text.setText("Cache manager not available")
                except Exception as e:
                    print(f"Error updating cache directories: {e}")
                    self.cache_dirs_text.setText("Error loading cache directories")
            
            progress_dialog.close()
            
            # Update cache totals label with new cache sizes
            self._update_cache_totals_label()
            
            # Show completion message with before/after sizes
            total_removed = removed_cnn + removed_clip + removed_face + removed_thumbnails
            new_sizes = self._calculate_cache_sizes()
            
            if total_removed > 0:
                message = f"Cache scrubbing complete.\n\n"
                message += f"Removed entries:\n"
                if removed_cnn > 0:
                    message += f"  - CNN features: {removed_cnn}\n"
                if removed_clip > 0:
                    message += f"  - CLIP features: {removed_clip}\n"
                if removed_face > 0:
                    message += f"  - Face encodings: {removed_face}\n"
                if removed_thumbnails > 0:
                    message += f"  - Thumbnails: {removed_thumbnails}\n"
                message += f"\nCurrent cache sizes:\n"
                message += f"  - Thumbnails: {format_file_size(new_sizes['thumbnails'])}\n"
                message += f"  - CNN: {format_file_size(new_sizes['cnn'])}\n"
                message += f"  - CLIP: {format_file_size(new_sizes['clip'])}\n"
                message += f"  - Total: {format_file_size(new_sizes['total'])}\n"
                show_styled_information(
                    self,
                    "Cache Scrubbing Complete",
                    message
                )
            else:
                message = "Cache scrubbing complete. No invalid entries found.\n\n"
                message += f"Current cache sizes:\n"
                message += f"  - Thumbnails: {format_file_size(new_sizes['thumbnails'])}\n"
                message += f"  - CNN: {format_file_size(new_sizes['cnn'])}\n"
                message += f"  - CLIP: {format_file_size(new_sizes['clip'])}\n"
                message += f"  - Total: {format_file_size(new_sizes['total'])}\n"
                show_styled_information(
                    self,
                    "Cache Scrubbing Complete",
                    message
                )
                
        except Exception as e:
            progress_dialog.close()
            import traceback
            traceback.print_exc()
            show_styled_critical(
                self,
                "Error Scrubbing Caches",
                f"An error occurred while scrubbing caches:\n\n{str(e)}"
            )

    def apply_filter_now(self):
        """Apply filter immediately for debugging"""
        if self.parent():
            # Get filter pattern
            filter_pattern = self.filter_pattern_input.text().strip()
            
            # Validate pattern
            if not self.validate_filter_pattern(filter_pattern):
                return  # Don't apply invalid pattern
            
            # Normalize pattern for storage (remove trailing asterisk)
            normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
            
            # Apply filter directly to parent window (use pattern with asterisk for matching)
            self.parent().filter_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(normalized_pattern)
            # Update status bar immediately to reflect filter change
            if hasattr(self.parent(), 'status_bar_manager'):
                self.parent().status_bar_manager._update_filter_section(self.parent())
            
            # Save filter_pattern setting - use config from parent if available
            if hasattr(self.parent(), 'config'):
                self.parent().config.update_setting('filter_pattern', normalized_pattern)
            
            # Stop thumbnail generation when filter is applied
            if (hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager and 
                self.parent().cache_manager.background_loader):
                self.parent().cache_manager.background_loader.stop()
            
            # Force refresh of the directory with new filter and limit
            def refresh_and_restart():
                if hasattr(self.parent(), 'refresh_directory_intelligently'):
                    # Use intelligent refresh that preserves valid thumbnails
                    self.parent().refresh_directory_intelligently()
                elif hasattr(self.parent(), '_efficient_refresh_directory'):
                    self.parent()._efficient_refresh_directory()
                else:
                    # Fallback to regular refresh if efficient method not available
                    self.parent().refresh_directory()
                # Restart thumbnail generation after refresh completes
                if (hasattr(self.parent(), 'cache_manager') and self.parent().cache_manager and 
                    self.parent().cache_manager.background_loader):
                    self.parent().cache_manager.background_loader.start()
                if hasattr(self.parent(), 'start_background_thumbnail_loading_if_needed'):
                    self.parent().start_background_thumbnail_loading_if_needed()
            QTimer.singleShot(100, refresh_and_restart)
            
            # Update match count after refresh (use timer to ensure directory is loaded)
            QTimer.singleShot(300, lambda: self.update_match_count(filter_pattern))
            
            # Show message
            if filter_pattern:
                message = f"Filter applied: '{filter_pattern}'"
            else:
                message = "Filter cleared"
                
            self.parent().status_notification.show_message(message)
    
 

if __name__ == "__main__":
    """Test the settings dialog independently with updated mocks based on new internals"""
    import sys
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv)
    
    # Apply global dark theme stylesheet for consistent UI styling (same as prowser.py)
    from thumbnails.thumbnail_constants import get_dark_theme_stylesheet
    app.setStyleSheet(get_dark_theme_stylesheet())

    class MockParentWindow(QWidget):
        def __init__(self):
            super().__init__()
            # Updated attributes consistent with what SettingsDialog and apply_filter_now require
            self.debug_mode = True
            self.confirm_delete = False
            self.is_actual_size = True
            self.wrap_around = True
            self.raise_status_bar_on_cursor_near_bottom = True
            self.space_key_mode = 'exit'
            self.filter_pattern = 'image*'
            self.current_directory = '/mock/images'
            self.thumbnail_filename_visible = False
            self.show_extensions = False
            self.ignore_exif_rotation = False
            self.drag_drop_auto_date_change = False
            self.status_notification = self.MockStatusNotification()
            self.config = self.MockConfig()
            self.displayed_images = ['/mock/images/file1.jpg', '/mock/images/file2.jpg']
            self.refresh_invocations = []

        class MockStatusNotification:
            def show_message(self, message):
                pass

        class MockConfig:
            def update_setting(self, key, value):
                pass

        # Methods for settings dialog compatibility (assigned after instance creation)
        def setup_methods(self):
            def refresh_directory_intelligently():
                self.refresh_invocations.append("intelligent")
            def _efficient_refresh_directory():
                self.refresh_invocations.append("efficient")
            def refresh_directory():
                self.refresh_invocations.append("regular")
            self.refresh_directory_intelligently = refresh_directory_intelligently
            self._efficient_refresh_directory = _efficient_refresh_directory
            self.refresh_directory = refresh_directory

    # Instantiate mock parent and assign methods
    mock_parent = MockParentWindow()
    mock_parent.setup_methods()

    try:
        dialog = SettingsDialog(mock_parent)
    except Exception as e:
        # Print the error and exit if dialog creation fails
        print("Error creating SettingsDialog:", e)
        sys.exit(1)

    def on_settings_changed(settings):
        pass

    def on_cache_cleared():
        pass

    def on_dialog_finished():
        pass
        app.quit()

    dialog.settings_changed.connect(on_settings_changed)
    dialog.cache_cleared.connect(on_cache_cleared)
    dialog.finished.connect(on_dialog_finished)

    dialog.show()

    from PySide6.QtCore import QTimer

    def simulate_apply_filter():
        dialog.apply_filter_now()

    QTimer.singleShot(750, simulate_apply_filter)

    sys.exit(app.exec())
