#!/usr/bin/env python3
"""Edit dialog: source image preview + edit prompt and model controls."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_dialog import (
    ImageGenDimensionAspectMixin,
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    apply_image_gen_preview_client_background,
    image_gen_preview_workarea_fill,
    apply_import_extras_from_image_path,
    append_image_gen_import_size_button,
    load_import_prompt_from_path,
    configure_image_gen_side_checkbox,
    create_image_gen_side_button_column,
    finalize_image_gen_side_button_column,
    insert_image_gen_side_column_widget_before_stretch,
    mount_pass_image_to_ai_checkbox,
    pass_image_to_ai_checked,
    repopulate_image_gen_prompt_import_row,
    repopulate_image_gen_side_buttons,
    wrap_image_gen_side_checkbox,
    validate_copies_require_random_seed,
    wrap_image_gen_controls_with_side_buttons,
)
from imagegen_plugins.image_gen_edit_custom_size import (
    migrate_edit_size_saved_values,
    mount_edit_custom_size_section,
)
from imagegen_plugins.image_gen_form_layout import (
    ImageGenFieldsPanel,
    IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT,
    mount_image_gen_fields_in_scroll,
)
from imagegen_plugins.image_gen_parameter_panel import (
    ImageGenParameterPanel,
    default_widget_build_options,
)
from imagegen_plugins.image_gen_source_nav import (
    ImageGenSourceNavRow,
    install_source_nav_keyboard_shortcuts,
    open_image_in_browse,
    refresh_source_nav_keyboard_shortcuts,
    resolve_image_gen_main_window,
)
from imagegen_plugins.image_gen_model_selector import (
    apply_mflux_lora_collection_guard,
    build_model_selector_row,
    mount_image_gen_lora_field,
    refresh_dialog_mflux_lora_combo,
    sync_image_gen_generate_enabled,
    sync_image_gen_lora_field,
    resolve_initial_plugin,
    switch_plugin_persisted_settings_preserving_prompt,
    sync_model_comment_label,
)
from imagegen_plugins.image_gen_persistence import (
    load_imagegen_dialog_geometry_hex,
    load_plugin_dialog_settings,
    save_imagegen_dialog_geometry_hex,
    save_plugin_dialog_settings,
)
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from imagegen_plugins.flux_prompt_system_mount import (
    flux_prompt_system_override_for,
    remount_flux_prompt_system_splitter,
)
from search.reference_graph import valid_exif_reference_paths_for_image
from imagegen_plugins.image_gen_function_switcher import (
    create_image_gen_action_buttons,
    create_image_gen_dialog_footer,
    install_image_gen_escape_to_close,
    install_image_gen_footer_keyboard_shortcuts,
    refresh_image_gen_footer_keyboard_shortcuts,
)
from imagegen_plugins.imagegen_control_tooltips import (
    apply_edit_import_all_button_tooltip,
    apply_edit_import_text_button_tooltip,
    apply_field_control_tooltips,
    apply_model_combo_tooltip,
)
from theme.theme_service import get_active_theme
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
    validate_image_file,
)

EDIT_IMAGE_DIALOG_TITLE = "Edit an image with AI"
MAX_EDIT_SOURCE_IMAGES = 4
_EDIT_SOURCE_MIME = "application/x-imagegen-edit-source-path"
_EDIT_SOURCE_REMOVE_BOX_PX = 32
_EDIT_SOURCE_REMOVE_BORDER_PX = 2
_EDIT_SOURCE_REMOVE_INSET_PX = 3


def _local_paths_from_mime(mime: QMimeData) -> list[str]:
    if not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if url.isLocalFile():
            paths.append(os.path.abspath(url.toLocalFile()))
    return paths


def _is_external_file_drag(mime: QMimeData) -> bool:
    return bool(_local_paths_from_mime(mime))


def _is_internal_edit_source_drag(mime: QMimeData) -> bool:
    return mime.hasFormat(_EDIT_SOURCE_MIME)


def _merge_external_edit_source_paths(
    existing: list[str],
    incoming: list[str],
    *,
    insert_index: Optional[int] = None,
    max_total: int = MAX_EDIT_SOURCE_IMAGES,
) -> tuple[list[str], list[str]]:
    """Merge dropped file paths into the edit source list. Returns (paths, warnings)."""
    warnings: list[str] = []
    existing_abs = [os.path.abspath(p) for p in existing if p]
    existing_set = set(existing_abs)

    valid_new: list[str] = []
    invalid_names: list[str] = []
    duplicate_names: list[str] = []

    for path in incoming:
        if not path:
            continue
        abs_path = os.path.abspath(path)
        base = os.path.basename(abs_path)
        if not os.path.isfile(abs_path):
            continue
        if not validate_image_file(abs_path):
            invalid_names.append(base)
            continue
        if abs_path in existing_set or abs_path in valid_new:
            duplicate_names.append(base)
            continue
        valid_new.append(abs_path)

    slots = max(0, max_total - len(existing_abs))
    added = valid_new[:slots]
    skipped_capacity = valid_new[slots:]

    if not added and not invalid_names and not duplicate_names and not skipped_capacity:
        if incoming:
            warnings.append("No supported image files were dropped.")
        return existing_abs, warnings

    if not slots and valid_new:
        warnings.append(
            f"Already at the maximum of {max_total} source images. "
            "Remove an image before adding more."
        )

    new_paths = list(existing_abs)
    if added:
        if insert_index is None:
            insert_index = len(new_paths)
        insert_index = max(0, min(insert_index, len(new_paths)))
        for path in added:
            new_paths.insert(insert_index, path)
            insert_index += 1
        new_paths = new_paths[:max_total]

    # Only show 'added' message if there are other warnings (i.e., there were problems)
    has_problems = bool(skipped_capacity or invalid_names or duplicate_names)
    if added and has_problems:
        warnings.append(
            f"Added {len(added)} image{'s' if len(added) != 1 else ''}."
        )
    if skipped_capacity:
        warnings.append(
            f"{len(skipped_capacity)} image{'s' if len(skipped_capacity) != 1 else ''} "
            f"were not added (maximum is {max_total})."
        )
    if invalid_names:
        shown = ", ".join(invalid_names[:5])
        extra = len(invalid_names) - 5
        if extra > 0:
            shown = f"{shown}, and {extra} more"
        warnings.append(f"Skipped unsupported file type: {shown}.")
    if duplicate_names:
        shown = ", ".join(duplicate_names[:5])
        extra = len(duplicate_names) - 5
        if extra > 0:
            shown = f"{shown}, and {extra} more"
        warnings.append(f"Already in the source list: {shown}.")

    return new_paths, warnings


def _merge_imported_edit_source_paths(
    existing: list[str],
    imported: list[str],
    *,
    max_total: int = MAX_EDIT_SOURCE_IMAGES,
) -> list[str]:
    """Apply EXIF import paths while preserving sources not in the imported set."""
    imported_abs = [
        os.path.abspath(p) for p in imported if p and os.path.isfile(p)
    ]
    imported_set = set(imported_abs)
    merged = list(imported_abs)
    merged_set = set(merged)
    for path in existing:
        if not path:
            continue
        abs_path = os.path.abspath(path)
        if abs_path in imported_set or abs_path in merged_set:
            continue
        if not os.path.isfile(abs_path):
            continue
        if len(merged) >= max_total:
            break
        merged.append(abs_path)
        merged_set.add(abs_path)
    return merged[:max_total]


def active_image_paths_for_edit(main_window) -> list[str]:
    """1–3 source paths for Klein edit (browse: current; thumbnail: selection)."""
    if main_window is None:
        return []
    paths: list[str] = []
    if main_window.current_view_mode == "browse":
        if hasattr(main_window, "get_current_image_path"):
            image_path = main_window.get_current_image_path()
            if image_path and os.path.isfile(image_path):
                paths.append(os.path.abspath(image_path))
    elif main_window.current_view_mode == "thumbnail":
        if hasattr(main_window, "selection_manager") and main_window.selection_manager:
            selected = main_window.selection_manager.get_selected_files()
            multi = bool(getattr(main_window, "selected_files", None))
            if multi and len(selected) > 1:
                for image_path in selected:
                    if image_path and os.path.isfile(image_path):
                        paths.append(os.path.abspath(image_path))
                    if len(paths) >= MAX_EDIT_SOURCE_IMAGES:
                        break
            elif selected:
                image_path = selected[0]
                if image_path and os.path.isfile(image_path):
                    paths.append(os.path.abspath(image_path))
    return paths


def active_image_path_for_edit(main_window) -> Optional[str]:
    paths = active_image_paths_for_edit(main_window)
    return paths[0] if paths else None


class _SourceImagePreview(QLabel):
    """Read-only preview of the image being edited."""

    _HINT_SIZE = QSize(320, 280)
    _MIN_HINT_SIZE = QSize(160, 120)

    def __init__(
        self,
        source_path: str,
        parent=None,
        *,
        on_external_drop=None,
        on_double_click: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self._source_path = os.path.abspath(source_path)
        self._on_external_drop = on_external_drop
        self._on_double_click = on_double_click
        self._pixmap = QPixmap(self._source_path)
        self._scaled_pixmap: Optional[QPixmap] = None
        self._load_error = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.setFrameShape(QFrame.Shape.NoFrame)
        if on_external_drop is not None:
            self.setAcceptDrops(True)
            tip = "Drag image files here to add source images (up to 4 total).\n\n"
            if on_double_click is not None:
                tip += "Double-click to open in browse mode.\n\n"
            self.setToolTip(tip)
        elif on_double_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Double-click to open in browse mode")
        apply_image_gen_preview_client_background(self)
        self._refresh_scaled_pixmap()

    def sizeHint(self) -> QSize:
        return self._HINT_SIZE

    def minimumSizeHint(self) -> QSize:
        return self._MIN_HINT_SIZE

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scaled_pixmap()

    def set_source_path(self, source_path: str) -> None:
        self._source_path = os.path.abspath(source_path)
        self._pixmap = QPixmap(self._source_path)
        self._refresh_scaled_pixmap()

    def _refresh_scaled_pixmap(self) -> None:
        if self._pixmap.isNull():
            self._scaled_pixmap = None
            self._load_error = True
            self.clear()
            self.update()
            return
        self._load_error = False
        self.clear()
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            self._scaled_pixmap = None
            self.update()
            return
        self._scaled_pixmap = self._pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.update()

    def _image_display_rect(self) -> QRect:
        pix = self._scaled_pixmap
        if pix is None or pix.isNull():
            return QRect()
        pw, ph = pix.width(), pix.height()
        if pw < 1 or ph < 1:
            return QRect()
        x = (self.width() - pw) // 2
        y = (self.height() - ph) // 2
        return QRect(x, y, pw, ph)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), image_gen_preview_workarea_fill())
        if self._scaled_pixmap is not None and not self._scaled_pixmap.isNull():
            x = (self.width() - self._scaled_pixmap.width()) // 2
            y = (self.height() - self._scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, self._scaled_pixmap)
            return
        if self._load_error:
            painter.setPen(QColor(get_active_theme().dialog_text_color_hex))
            painter.drawText(
                self.rect(),
                int(Qt.AlignmentFlag.AlignCenter),
                "Could not load image",
            )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._on_external_drop is not None and _is_external_file_drag(
            event.mimeData()
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._on_external_drop is not None and _is_external_file_drag(
            event.mimeData()
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if self._on_external_drop is not None and _is_external_file_drag(
            event.mimeData()
        ):
            self._on_external_drop(_local_paths_from_mime(event.mimeData()), None)
            event.acceptProposedAction()
            return
        event.ignore()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._on_double_click is not None
        ):
            self._on_double_click(self._source_path)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ClickableSourceThumb(_SourceImagePreview):
    """Thumbnail that selects the primary edit source on click."""

    def __init__(
        self,
        source_path: str,
        on_activate,
        parent=None,
        *,
        draggable: bool = False,
        on_open_in_browse: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(source_path, parent)
        self._on_activate = on_activate
        self._on_open_in_browse = on_open_in_browse
        self._draggable = draggable
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_started = False
        self._hover_remove = False
        self._default_thumb_cursor = (
            Qt.CursorShape.OpenHandCursor
            if draggable
            else Qt.CursorShape.PointingHandCursor
        )
        self.setMouseTracking(True)
        self.setCursor(self._default_thumb_cursor)
        if draggable:
            self.setAcceptDrops(True)
            self.setToolTip(
                "Click to set as primary source. Drag to reorder. "
                "Drop image files to add sources (up to 4 total). "
                "Double-click to open in browse mode."
            )
        elif on_open_in_browse is not None:
            self.setToolTip(
                "Click to set as primary source. "
                "Double-click to open in browse mode."
            )

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover_remove = True
        self._update_remove_cursor(event.position().toPoint())
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_remove = False
        self.setCursor(self._default_thumb_cursor)
        self.update()
        super().leaveEvent(event)

    def _update_remove_cursor(self, pos: QPoint) -> None:
        remove_rect = self._remove_button_rect()
        if (
            self._hover_remove
            and remove_rect is not None
            and remove_rect.contains(pos)
        ):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(self._default_thumb_cursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._hover_remove:
            return
        remove_rect = self._remove_button_rect()
        if remove_rect is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        border = _EDIT_SOURCE_REMOVE_BORDER_PX
        painter.fillRect(remove_rect, QColor(255, 255, 255))
        inner = remove_rect.adjusted(border, border, -border, -border)
        painter.fillRect(inner, QColor(0, 0, 0))
        pad = 3
        x_rect = inner.adjusted(pad, pad, -pad, -pad)
        painter.setPen(QPen(QColor(220, 40, 40), 2))
        painter.drawLine(x_rect.topLeft(), x_rect.bottomRight())
        painter.drawLine(x_rect.topRight(), x_rect.bottomLeft())

    def _remove_button_rect(self) -> Optional[QRect]:
        preview = self._multi_preview()
        if preview is None or len(preview.source_paths()) <= 1:
            return None
        img = self._image_display_rect()
        if img.isEmpty():
            return None
        box = _EDIT_SOURCE_REMOVE_BOX_PX
        inset = _EDIT_SOURCE_REMOVE_INSET_PX
        x = img.right() - inset - box + 1
        y = img.top() + inset
        return QRect(x, y, box, box)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            remove_rect = self._remove_button_rect()
            if (
                self._hover_remove
                and remove_rect is not None
                and remove_rect.contains(event.pos())
            ):
                preview = self._multi_preview()
                if preview is not None:
                    preview.request_remove_path(self._source_path)
                event.accept()
                return
            self._drag_start_pos = event.pos()
            self._drag_started = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._draggable
            and self._drag_start_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self._drag_started
        ):
            distance = (event.pos() - self._drag_start_pos).manhattanLength()
            threshold = max(QApplication.startDragDistance() * 2, 16)
            if distance >= threshold:
                self._drag_started = True
                self._start_drag()
                return
        self._update_remove_cursor(event.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
            and not self._drag_started
        ):
            self._on_activate(self._source_path)
            event.accept()
        self._drag_start_pos = None
        self._drag_started = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._on_open_in_browse is not None
        ):
            self._on_open_in_browse(self._source_path)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _start_drag(self) -> None:
        if not self._draggable:
            return
        preview = self._multi_preview()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(
            _EDIT_SOURCE_MIME,
            self._source_path.encode("utf-8"),
        )
        drag.setMimeData(mime)
        pixmap = self._scaled_pixmap or self._pixmap
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(
                pixmap.scaled(
                    96,
                    96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        if preview is not None:
            preview._drag_source_path = self._source_path
        try:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            if preview is not None:
                preview._drag_source_path = None
            try:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            except RuntimeError:
                pass
            self._drag_start_pos = None
            self._drag_started = False

    def _multi_preview(self) -> Optional["_MultiSourceImagePreview"]:
        parent = self.parent()
        if isinstance(parent, _MultiSourceImagePreview):
            return parent
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        preview = self._multi_preview()
        if preview is not None and self._draggable:
            preview._accept_drag(event)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        preview = self._multi_preview()
        if preview is not None and self._draggable:
            pos = preview.mapFromGlobal(self.mapToGlobal(event.pos()))
            preview._update_drop_index(pos, event)
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        preview = self._multi_preview()
        if preview is not None and self._draggable:
            preview._clear_drop_index()
            super().dragLeaveEvent(event)
            return
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        preview = self._multi_preview()
        if preview is not None and self._draggable:
            pos = preview.mapFromGlobal(self.mapToGlobal(event.pos()))
            preview._perform_drop(pos, event)
            return
        super().dropEvent(event)


class _MultiSourceImagePreview(QWidget):
    """Flowing row of source thumbnails (no prev/next navigation)."""

    _HINT_SIZE = QSize(320, 280)
    _MIN_HINT_SIZE = QSize(160, 120)

    def __init__(
        self,
        source_paths: list[str],
        on_activate,
        on_reorder=None,
        on_remove=None,
        on_add_paths=None,
        parent=None,
        *,
        on_open_in_browse: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self._on_activate = on_activate
        self._on_reorder = on_reorder
        self._on_remove = on_remove
        self._on_add_paths = on_add_paths
        self._on_open_in_browse = on_open_in_browse
        self._source_paths = list(source_paths)
        self._thumbs: list[_ClickableSourceThumb] = []
        self._drop_insert_index: Optional[int] = None
        self._drag_source_path: Optional[str] = None
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.setAcceptDrops(True)
        self.setToolTip(
            "Drag thumbnails to reorder. Drop image files to add sources (up to 4 total)."
        )
        apply_image_gen_preview_client_background(self)
        self._rebuild_thumbs()

    def sizeHint(self) -> QSize:
        return self._HINT_SIZE

    def minimumSizeHint(self) -> QSize:
        return self._MIN_HINT_SIZE

    def source_paths(self) -> list[str]:
        return list(self._source_paths)

    def request_remove_path(self, path: str) -> None:
        if len(self._source_paths) <= 1:
            return
        paths = [p for p in self._source_paths if p != path]
        if len(paths) == len(self._source_paths) or not paths:
            return
        if self._on_remove is not None:
            self._on_remove(paths)

    def set_source_paths(self, source_paths: list[str]) -> None:
        self._source_paths = [
            os.path.abspath(p) for p in source_paths if p and os.path.isfile(p)
        ]
        self._rebuild_thumbs()

    def _rebuild_thumbs(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._thumbs.clear()
        for path in self._source_paths:
            thumb = _ClickableSourceThumb(
                path,
                self._on_activate,
                self,
                draggable=True,
                on_open_in_browse=self._on_open_in_browse,
            )
            thumb.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._layout.addWidget(thumb, 1)
            self._thumbs.append(thumb)

    def _apply_thumb_order(self) -> None:
        path_to_thumb = {thumb._source_path: thumb for thumb in self._thumbs}
        self._thumbs = [
            path_to_thumb[path]
            for path in self._source_paths
            if path in path_to_thumb
        ]
        while self._layout.count():
            self._layout.takeAt(0)
        for thumb in self._thumbs:
            self._layout.addWidget(thumb, 1)

    def _insert_index_at(self, pos: QPoint) -> int:
        for index, thumb in enumerate(self._thumbs):
            rect = thumb.geometry()
            if pos.x() < rect.center().x():
                return index
        return len(self._thumbs)

    def _indicator_x_for_index(self, insert_index: int) -> Optional[int]:
        if not self._thumbs:
            return None
        if insert_index <= 0:
            return self._thumbs[0].geometry().left()
        if insert_index >= len(self._thumbs):
            return self._thumbs[-1].geometry().right()
        left = self._thumbs[insert_index - 1].geometry().right()
        right = self._thumbs[insert_index].geometry().left()
        return (left + right) // 2

    def _set_drop_insert_index(self, insert_index: Optional[int]) -> None:
        if self._drop_insert_index == insert_index:
            return
        self._drop_insert_index = insert_index
        self.update()

    def _reorder_path(self, source_path: str, insert_index: int) -> None:
        paths = list(self._source_paths)
        try:
            from_index = paths.index(source_path)
        except ValueError:
            return
        if from_index < insert_index:
            insert_index -= 1
        if insert_index == from_index or not (0 <= insert_index <= len(paths)):
            return
        path = paths.pop(from_index)
        paths.insert(insert_index, path)
        self._source_paths = paths
        self._apply_thumb_order()
        if self._on_reorder is not None:
            self._on_reorder(paths)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_insert_index is None:
            return
        x = self._indicator_x_for_index(self._drop_insert_index)
        if x is None:
            return
        painter = QPainter(self)
        pen = QPen(self.palette().color(self.foregroundRole()), 2)
        painter.setPen(pen)
        painter.drawLine(x, 4, x, self.height() - 4)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._accept_drag(event)

    def _accept_drag(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if _is_internal_edit_source_drag(mime) or (
            self._on_add_paths is not None and _is_external_file_drag(mime)
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._update_drop_index(event.pos(), event)

    def _update_drop_index(self, pos: QPoint, event: QDragMoveEvent) -> None:
        mime = event.mimeData()
        if _is_internal_edit_source_drag(mime) or (
            self._on_add_paths is not None and _is_external_file_drag(mime)
        ):
            self._set_drop_insert_index(self._insert_index_at(pos))
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_index()
        super().dragLeaveEvent(event)

    def _clear_drop_index(self) -> None:
        self._set_drop_insert_index(None)

    def dropEvent(self, event: QDropEvent) -> None:
        self._perform_drop(event.pos(), event)

    def _perform_drop(self, pos: QPoint, event: QDropEvent) -> None:
        mime = event.mimeData()
        insert_index = self._insert_index_at(pos)
        self._clear_drop_index()
        if _is_internal_edit_source_drag(mime):
            source_path = bytes(mime.data(_EDIT_SOURCE_MIME)).decode("utf-8")
            self._reorder_path(source_path, insert_index)
            event.acceptProposedAction()
            return
        if self._on_add_paths is not None and _is_external_file_drag(mime):
            self._on_add_paths(_local_paths_from_mime(mime), insert_index)
            event.acceptProposedAction()
            return
        event.ignore()


class ImageGenEditDialog(ImageGenDimensionAspectMixin, QDialog):
    """Source preview + dynamically built edit configuration fields."""

    state_changed = Signal()

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        function: str,
        source_path: str,
        parent=None,
        *,
        source_paths: Optional[List[str]] = None,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
        window_title: str = EDIT_IMAGE_DIALOG_TITLE,
        auto_import_available: bool = False,
        panel_mode: bool = False,
    ):
        super().__init__(parent)
        self._panel_mode = panel_mode
        self._image_gen_persistent_panel = True
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        if source_paths:
            self._source_paths = [
                os.path.abspath(p) for p in source_paths if p and os.path.isfile(p)
            ]
        else:
            self._source_paths = (
                [os.path.abspath(source_path)] if source_path else []
            )
        if not self._source_paths:
            raise ValueError("At least one source image path is required")
        self.source_path = self._source_paths[0]
        self._multi_source = len(self._source_paths) > 1
        self._widgets: Dict[str, Any] = {}
        self._specs: List[FieldSpec] = []
        self._param_panel: Optional[ImageGenParameterPanel] = None
        self._fields_panel: Optional[ImageGenFieldsPanel] = None
        self._source_preview: Optional[_SourceImagePreview] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._multi_source_preview: Optional[_MultiSourceImagePreview] = None
        self._preview_host: Optional[QFrame] = None
        self._preview_layout: Optional[QVBoxLayout] = None
        self._flux_prompt_ai: Optional[ImageGenFluxPromptAi] = None
        self._flux_system_prompt_pane = None
        self._pass_image_to_ai_cb: Optional[QCheckBox] = None
        self._side_btn_host: Optional[QWidget] = None
        self._side_btn_col: Optional[QVBoxLayout] = None
        self._auto_import_available = auto_import_available
        self._custom_size_outer = None
        self._init_dim_aspect_state()

        initial = resolve_initial_plugin(
            self._plugins,
            function=function,
            initial_plugin_id=initial_plugin_id,
        )
        self.plugin = initial
        if initial is not None:
            self._load_plugin_state(
                saved_override=initial_values if initial_values else None
            )
        else:
            self._values = {}
            self._specs = []

        if self._panel_mode:
            self.setWindowFlags(Qt.Widget)
            self.setMinimumSize(0, 0)
        else:
            apply_image_gen_dialog_shell(
                self, window_title=window_title, min_width=880, min_height=520
            )
        self._build_ui()
        if initial_prompt:
            self.set_prompt_text(initial_prompt)

        if not self._panel_mode:
            self._geometry_restore_attempted = False
            self._geometry_was_restored = False
            self.finished.connect(self._save_geometry)
        self._connect_panel_dirty_tracking()

    def reject(self) -> None:
        from imagegen_plugins.image_gen_panel_shell import panel_mode_reject
        from imagegen_plugins.imagegen_flux_prompt_ai import cancel_dialog_flux_prompt_refine

        if panel_mode_reject(self):
            return
        cancel_dialog_flux_prompt_refine(self)
        super().reject()

    def _load_plugin_state(self, *, saved_override: Optional[Dict[str, Any]] = None) -> None:
        saved = saved_override
        if saved is None:
            saved = load_plugin_dialog_settings(
                self._function, self.plugin.plugin_id
            )
        self._values = migrate_edit_size_saved_values(
            self.plugin.merged_values(saved)
        )
        self._specs = self.plugin.field_specs(saved)

    def _save_geometry(self) -> None:
        try:
            save_imagegen_dialog_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def show(self):
        from utils import restore_dialog_geometry_before_first_show

        restore_dialog_geometry_before_first_show(
            self, load_imagegen_dialog_geometry_hex(), self.parent()
        )
        super().show()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._geometry_was_restored:
            QTimer.singleShot(0, lambda: _center_styled_dialog_on_screen(self, self.parent()))
        QTimer.singleShot(0, self._raise_and_activate)
        if self._auto_import_available:
            QTimer.singleShot(0, self._on_import_all)

    def _raise_and_activate(self) -> None:
        from utils import raise_dialog_without_space_hop

        raise_dialog_without_space_hop(self)

    def closeEvent(self, event):
        if not self._panel_mode:
            from imagegen_plugins.imagegen_flux_prompt_ai import (
                cancel_dialog_flux_prompt_refine,
            )

            cancel_dialog_flux_prompt_refine(self)
        try:
            save_plugin_dialog_settings(
                self._function, self.plugin.plugin_id, self.collect_values()
            )
        except Exception:
            pass
        self._save_geometry()
        super().closeEvent(event)

    def _refresh_use_custom_size_label(self) -> None:
        refresh = getattr(self, "_refresh_use_custom_size_label", None)
        if callable(refresh):
            refresh()

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        # Single-image nav replaces the sole source; keep _source_paths aligned for generate.
        if not self._multi_source:
            self._source_paths = [self.source_path]
        if self._source_preview is not None:
            self._source_preview.set_source_path(self.source_path)
        if self._source_nav is not None:
            self._source_nav.set_active_source_path(self.source_path)
        self._refresh_use_custom_size_label()
        if self._panel_mode:
            self.state_changed.emit()

    def _on_multi_source_thumb_selected(self, path: str) -> None:
        self.source_path = os.path.abspath(path)

    def _open_source_in_browse(self, path: str) -> None:
        main_window = resolve_image_gen_main_window(self)
        if main_window is not None:
            open_image_in_browse(main_window, path)

    def _on_source_paths_reordered(self, paths: list[str]) -> None:
        self._source_paths = list(paths)
        if self._source_paths:
            self.source_path = self._source_paths[0]
        self._refresh_use_custom_size_label()

    def _on_external_paths_dropped(
        self,
        paths: list[str],
        insert_index: Optional[int] = None,
    ) -> None:
        new_paths, warnings = _merge_external_edit_source_paths(
            self._source_paths,
            paths,
            insert_index=insert_index,
        )
        if new_paths != self._source_paths:
            self._set_edit_source_paths(new_paths)
        if warnings:
            show_styled_warning(
                self,
                "Drop Images",
                "\n\n".join(warnings),
            )

    def _on_source_path_removed(self, paths: list[str]) -> None:
        self._set_edit_source_paths(paths)

    def _set_edit_source_paths(self, paths: list[str]) -> None:
        paths = [
            os.path.abspath(p)
            for p in paths
            if p and os.path.isfile(p)
        ][:MAX_EDIT_SOURCE_IMAGES]
        if not paths:
            return
        was_multi = self._multi_source
        self._source_paths = paths
        self.source_path = paths[0]
        self._multi_source = len(paths) > 1
        if self._multi_source == was_multi:
            if self._multi_source and self._multi_source_preview is not None:
                self._multi_source_preview.set_source_paths(paths)
            elif self._source_preview is not None:
                self._source_preview.set_source_path(self.source_path)
            self._refresh_use_custom_size_label()
            if self._panel_mode:
                self.state_changed.emit()
            return
        self._rebuild_source_preview()
        self._refresh_use_custom_size_label()
        if self._panel_mode:
            self.state_changed.emit()

    def _rebuild_source_preview(self) -> None:
        if self._preview_layout is None or self._preview_host is None:
            return
        layout = self._preview_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._source_preview = None
        self._source_nav = None
        self._multi_source_preview = None

        if self._multi_source:
            self._multi_source_preview = _MultiSourceImagePreview(
                self._source_paths,
                self._on_multi_source_thumb_selected,
                self._on_source_paths_reordered,
                self._on_source_path_removed,
                self._on_external_paths_dropped,
                self._preview_host,
                on_open_in_browse=self._open_source_in_browse,
            )
            layout.addWidget(self._multi_source_preview, 1)
            install_source_nav_keyboard_shortcuts(self, None)
        else:
            self._source_preview = _SourceImagePreview(
                self.source_path,
                self._preview_host,
                on_external_drop=self._on_external_paths_dropped,
                on_double_click=self._open_source_in_browse,
            )
            self._source_nav = ImageGenSourceNavRow(
                resolve_image_gen_main_window(self),
                self._on_source_image_changed,
                self._preview_host,
                initial_source_path=self.source_path,
            )
            self._source_nav.set_center_widget(self._source_preview)
            layout.addWidget(self._source_nav)
            install_source_nav_keyboard_shortcuts(self, self._source_nav)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                configure_image_gen_embedded_panel_layout,
            )

            configure_image_gen_embedded_panel_layout(layout, self)
        splitter = ImageGenPreviewSplitter(self)

        preview_host = QFrame()
        preview_host.setFrameShape(QFrame.Shape.NoFrame)
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_host = preview_host
        self._preview_layout = preview_layout
        if self._multi_source:
            self._multi_source_preview = _MultiSourceImagePreview(
                self._source_paths,
                self._on_multi_source_thumb_selected,
                self._on_source_paths_reordered,
                self._on_source_path_removed,
                self._on_external_paths_dropped,
                preview_host,
                on_open_in_browse=self._open_source_in_browse,
            )
            preview_layout.addWidget(self._multi_source_preview, 1)
        else:
            self._source_preview = _SourceImagePreview(
                self.source_path,
                preview_host,
                on_external_drop=self._on_external_paths_dropped,
                on_double_click=self._open_source_in_browse,
            )
            self._source_nav = ImageGenSourceNavRow(
                resolve_image_gen_main_window(self),
                self._on_source_image_changed,
                preview_host,
                initial_source_path=self.source_path,
            )
            self._source_nav.set_center_widget(self._source_preview)
            preview_layout.addWidget(self._source_nav)
        splitter.add_preview_pane(preview_host)

        scroll = QScrollArea()
        self._fields_panel = ImageGenFieldsPanel(self, compact=self._panel_mode)
        self._side_btn_host, self._side_btn_col = create_image_gen_side_button_column(
            self
        )
        (
            model_row,
            self._model_combo,
            self._model_comment_label,
            self._plugins_by_id,
        ) = build_model_selector_row(
            self._plugins,
            selected_plugin_id=(
                self.plugin.plugin_id if self.plugin is not None else None
            ),
            parent=self._fields_panel.widget,
        )
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        apply_model_combo_tooltip(self._model_combo)
        self._fields_panel.add_labeled_field("Model", model_row, to_outer=True)
        sync_image_gen_generate_enabled(self, panel=self)
        self._lora_group, self._lora_combo = mount_image_gen_lora_field(
            self._fields_panel,
            parent=self._fields_panel.widget,
        )

        self._populate_field_rows()
        mount_image_gen_fields_in_scroll(scroll, self._fields_panel)
        controls = wrap_image_gen_controls_with_side_buttons(
            scroll, self._side_btn_host
        )
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                wrap_image_gen_controls_with_unified_intro,
            )

            controls = wrap_image_gen_controls_with_unified_intro(
                controls, self._function
            )
        splitter.add_controls_pane(controls)
        layout.addWidget(splitter, 1)
        if self._source_nav is not None:
            install_source_nav_keyboard_shortcuts(self, self._source_nav)

        if not self._panel_mode:
            actions = create_image_gen_action_buttons(
                on_generate=self._on_generate,
                on_close=self.reject,
            )
            install_image_gen_escape_to_close(self)
            install_image_gen_footer_keyboard_shortcuts(self)
            layout.addWidget(
                create_image_gen_dialog_footer(self, self._function, actions)
            )

    def _connect_panel_dirty_tracking(self) -> None:
        if not self._panel_mode:
            return
        from imagegen_plugins.image_gen_panel_dirty import connect_panel_field_widgets

        connect_panel_field_widgets(self, self.state_changed.emit)

    def _clear_field_rows(self) -> None:
        if self._param_panel is not None:
            self._param_panel.clear(keep_outer=IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT)
            self._widgets.clear()

    def _populate_field_rows(self) -> None:
        if self._fields_panel is None or self.plugin is None:
            return
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        if self._param_panel is None:
            self._param_panel = ImageGenParameterPanel(
                self._fields_panel,
                build_options=default_widget_build_options(
                    non_prompt_text_min_height=48,
                    float_label_precise=True,
                ),
            )
        self._param_panel.repopulate(
            self.plugin,
            self._values,
            keep_outer=IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT,
            effective_max_side=effective_max_for_plugin(self.plugin),
        )
        self._widgets = self._param_panel.widgets
        self._specs = self._param_panel.specs
        sync_image_gen_lora_field(self)
        mount_edit_custom_size_section(
            self,
            self._fields_panel,
            self._values,
            self._widgets,
            self._param_panel.specs,
            effective_max_side=effective_max_for_plugin(self.plugin),
            pipeline_id=self.plugin.pipeline_id,
            build_options=self._param_panel._build_options,
        )
        self._specs = self._param_panel.specs
        self._connect_dim_aspect_lock()
        self._restore_aspect_lock_from_values()
        self._apply_effective_max_to_dim_sliders()
        remount_flux_prompt_system_splitter(self)
        self._repopulate_side_buttons()

        if self._source_nav is not None:
            refresh_source_nav_keyboard_shortcuts(self)
        refresh_image_gen_footer_keyboard_shortcuts(self)
        self._connect_panel_dirty_tracking()

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA pulldown for the active edit model (4B vs 9B, etc.)."""
        sync_image_gen_lora_field(self)

    def _on_model_combo_changed(self, _index: int = 0) -> None:
        plugin_id = self._model_combo.currentData()
        new_plugin = self._plugins_by_id.get(plugin_id)
        if new_plugin is None:
            return
        if self.plugin is not None and new_plugin.plugin_id == self.plugin.plugin_id:
            return
        preserved_prompt = self.get_prompt_text()
        outgoing_plugin_id = (
            self.plugin.plugin_id if self.plugin is not None else None
        )
        incoming = switch_plugin_persisted_settings_preserving_prompt(
            self._function,
            outgoing_plugin_id,
            self.collect_values(),
            new_plugin.plugin_id,
            preserved_prompt=preserved_prompt,
        )
        self.plugin = new_plugin
        self._load_plugin_state(saved_override=incoming)
        sync_model_comment_label(self._model_comment_label, new_plugin)
        self._populate_field_rows()
        self.set_prompt_text(preserved_prompt)
        refresh_dialog_mflux_lora_combo(self)
        sync_image_gen_generate_enabled(self, panel=self)

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _import_prompt_text_from_source(self) -> bool:
        """Load prompt text from EXIF; return True on success."""
        if not self.source_path:
            show_styled_warning(self, "Import Text", "No image selected.")
            return False
        prompt_text = load_import_prompt_from_path(
            self, self.source_path, warning_title="Import Text"
        )
        if prompt_text is None:
            return False
        self.set_prompt_text(prompt_text)
        return True

    def _on_import_text(self) -> None:
        self._import_prompt_text_from_source()

    def _image_path_for_import_size(self) -> Optional[str]:
        if not self.source_path:
            show_styled_warning(self, "Import Size", "No image selected.")
            return None
        return self.source_path

    def _on_import_all(self) -> None:
        if not self.source_path:
            show_styled_warning(self, "Import Rest", "No image selected.")
            return
        apply_import_extras_from_image_path(self, self.source_path)
        ref_paths = valid_exif_reference_paths_for_image(
            self.source_path, max_count=MAX_EDIT_SOURCE_IMAGES
        )
        merged_paths = _merge_imported_edit_source_paths(
            self._source_paths, ref_paths
        )
        self._set_edit_source_paths(merged_paths)

    _on_import_available = _on_import_all

    def get_prompt_text(self) -> str:
        entry = self._widgets.get("prompt")
        if entry is None:
            return ""
        widget, _, spec = entry
        if spec.kind == "text":
            return widget.toPlainText()
        return ""

    def _prompt_edit_widget(self) -> Optional[QPlainTextEdit]:
        entry = self._widgets.get("prompt")
        if entry is None:
            return None
        widget, _, spec = entry
        if spec.kind == "text" and isinstance(widget, QPlainTextEdit):
            return widget
        return None

    def set_prompt_text(self, text: str) -> None:
        entry = self._widgets.get("prompt")
        if entry is None:
            return
        widget, _, spec = entry
        if spec.kind == "text":
            widget.setPlainText(text)

    def _mount_pass_image_to_ai_checkbox(self) -> None:
        mount_pass_image_to_ai_checkbox(self)

    def _use_custom_size_checked(self) -> bool:
        entry = self._widgets.get("use_custom_size")
        if entry is None:
            return False
        widget, _, spec = entry
        if spec.kind == "bool":
            return widget.isChecked()
        return False

    def _repopulate_side_buttons(self) -> None:
        repopulate_image_gen_prompt_import_row(
            self, self._build_prompt_action_buttons()
        )
        repopulate_image_gen_side_buttons(self, None)

    def _build_prompt_action_buttons(self) -> List[QPushButton]:
        buttons: List[QPushButton] = []
        import_text_btn = QPushButton("Import Prompt")
        import_text_btn.clicked.connect(self._on_import_text)
        apply_edit_import_text_button_tooltip(import_text_btn)
        buttons.append(import_text_btn)
        append_image_gen_import_size_button(self, buttons)
        import_all_btn = QPushButton("Import Rest")
        import_all_btn.clicked.connect(self._on_import_all)
        apply_edit_import_all_button_tooltip(import_all_btn, include_prompt=False)
        buttons.append(import_all_btn)
        return buttons

    def _populate_prompt_side_buttons(self, btn_col: QVBoxLayout) -> None:
        for button in self._build_prompt_action_buttons():
            btn_col.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        finalize_image_gen_side_button_column(btn_col)

    def _ensure_flux_prompt_ai(self) -> ImageGenFluxPromptAi:
        if self._flux_prompt_ai is None:
            self._flux_prompt_ai = ImageGenFluxPromptAi(
                self,
                task_kind=self._function,
                get_prompt_text=self.get_prompt_text,
                set_prompt_text=self.set_prompt_text,
                get_pass_image=lambda: pass_image_to_ai_checked(self),
                get_image_path=lambda: self.source_path,
                get_prompt_edit=self._prompt_edit_widget,
                get_system_prompt_override=lambda: flux_prompt_system_override_for(
                    self
                ),
            )
        return self._flux_prompt_ai

    def collect_values(self) -> Dict[str, Any]:
        if self._param_panel is None:
            out = dict(self._values)
        else:
            out = self._param_panel.collect_values(self._values)
        self._stash_aspect_lock_in_values(out)
        out["source_image_path"] = self.source_path
        out["source_image_paths"] = list(self._source_paths)
        return out

    def _prepare_run_values(
        self, *, force_flux_ai_job: bool = False
    ) -> Optional[Dict[str, Any]]:
        if self.plugin is None:
            return None
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        from imagegen_plugins.flux_prompt_job import (
            allow_empty_prompt_for_flux_ai_job,
            apply_flux_prompt_job_to_prepare_run_values,
        )

        prompt_spec = next((s for s in self._specs if s.key == "prompt"), None)
        if prompt_spec is not None and prompt_spec.required:
            prompt = (values.get("prompt") or "").strip()
            if not prompt and not allow_empty_prompt_for_flux_ai_job(
                self, force=force_flux_ai_job
            ):
                label = prompt_spec.label or "Edit prompt"
                show_styled_warning(
                    self,
                    f"{label} required",
                    f"Enter {label.lower()} before generating.",
                )
                return None
        if not validate_copies_require_random_seed(self, values):
            return None
        from imagegen_plugins.lora_trigger_prompt_guard import (
            validate_lora_trigger_before_generate,
        )

        values = validate_lora_trigger_before_generate(self, values)
        if values is None:
            return None
        if not apply_flux_prompt_job_to_prepare_run_values(
            self, values, force=force_flux_ai_job
        ):
            show_styled_warning(
                self,
                "AI prompt job",
                "Could not attach AI prompt data to the job.",
            )
            return None
        return values

    def run_generate(self) -> bool:
        if self.plugin is None:
            return False
        values = self._prepare_run_values()
        if values is None:
            return False
        save_plugin_dialog_settings(
            self._function, self.plugin.plugin_id, values
        )
        from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

        return start_imagegen_without_closing(
            self, self._function, self.plugin, values
        )

    def snapshot_state(self):
        from imagegen_plugins.image_gen_session_state import FunctionSessionState

        return FunctionSessionState(
            values=self.collect_values(),
            plugin_id=self.plugin.plugin_id if self.plugin is not None else "",
            source_path=self.source_path,
            source_paths=list(self._source_paths),
        )

    def restore_state(self, state, *, initial_prompt: Optional[str] = None) -> None:
        if state is not None:
            if state.source_paths:
                self._set_edit_source_paths(state.source_paths)
            elif state.source_path:
                self._set_edit_source_paths([state.source_path])
            plugin = self._plugins_by_id.get(state.plugin_id)
            if plugin is not None and (
                self.plugin is None or plugin.plugin_id != self.plugin.plugin_id
            ):
                idx = self._model_combo.findData(plugin.plugin_id)
                if idx >= 0:
                    self._model_combo.blockSignals(True)
                    self._model_combo.setCurrentIndex(idx)
                    self._model_combo.blockSignals(False)
                    self.plugin = plugin
            if self.plugin is not None:
                self._load_plugin_state(saved_override=state.values)
                self._populate_field_rows()
            sync_image_gen_generate_enabled(self, panel=self)
        elif initial_prompt:
            self.set_prompt_text(initial_prompt)

    def _on_generate(self) -> None:
        if self._panel_mode:
            self.run_generate()
            return
        self.run_generate()

    def accepted_values(self) -> Optional[Dict[str, Any]]:
        return getattr(self, "_result_values", None)

    def accepted_plugin(self) -> Optional[ImageGenModelPlugin]:
        return getattr(self, "_result_values", None) and self.plugin
