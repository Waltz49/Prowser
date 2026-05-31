#!/usr/bin/env python3
"""Edit dialog: source image preview + edit prompt and model controls."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
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
    QDialogButtonBox,
    QFormLayout,
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

from exif_utils import (
    decode_usercomment,
    get_usercomment_from_path,
    truncate_usercomment_before_prompt,
)
from imagegen_plugins.image_gen_dialog import (
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    apply_import_extras_from_image_path,
    build_seed_and_random_seed_row,
    configure_image_gen_form_layout,
    connect_import_button_with_option_modifier,
    field_specs_share_seed_row,
    validate_copies_require_random_seed,
)
from imagegen_plugins.image_gen_source_nav import (
    ImageGenSourceNavRow,
    install_source_nav_keyboard_shortcuts,
    refresh_source_nav_keyboard_shortcuts,
    resolve_image_gen_main_window,
)
from imagegen_plugins.image_gen_active_model import save_active_plugin_id_for_function
from imagegen_plugins.image_gen_model_selector import (
    build_model_selector_row,
    resolve_initial_plugin,
    sync_model_comment_label,
)
from imagegen_plugins.image_gen_persistence import (
    load_dialog_settings,
    load_imagegen_dialog_geometry_hex,
    save_dialog_settings,
    save_imagegen_dialog_geometry_hex,
)
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.imagegen_control_tooltips import (
    apply_dialog_button_tooltips,
    apply_edit_import_button_tooltip,
    apply_field_control_tooltips,
    apply_model_combo_tooltip,
)
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
)

EDIT_IMAGE_DIALOG_TITLE = "Edit Image"
MAX_EDIT_SOURCE_IMAGES = 4
_EDIT_SOURCE_MIME = "application/x-imagegen-edit-source-path"


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

    def __init__(self, source_path: str, parent=None):
        super().__init__(parent)
        self._source_path = os.path.abspath(source_path)
        self._pixmap = QPixmap(self._source_path)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.setFrameShape(QFrame.Shape.StyledPanel)
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
            self.setText("Could not load image")
            return
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return
        scaled = self._pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class _ClickableSourceThumb(_SourceImagePreview):
    """Thumbnail that activates the image in the main browser on click."""

    def __init__(
        self,
        source_path: str,
        on_activate,
        parent=None,
        *,
        draggable: bool = False,
    ):
        super().__init__(source_path, parent)
        self._on_activate = on_activate
        self._draggable = draggable
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_started = False
        cursor = (
            Qt.CursorShape.OpenHandCursor
            if draggable
            else Qt.CursorShape.PointingHandCursor
        )
        self.setCursor(cursor)
        if draggable:
            self.setAcceptDrops(True)
            self.setToolTip("Click to view in browser. Drag to reorder.")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
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
        pixmap = self.pixmap()
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
        parent=None,
    ):
        super().__init__(parent)
        self._on_activate = on_activate
        self._on_reorder = on_reorder
        self._source_paths = list(source_paths)
        self._thumbs: list[_ClickableSourceThumb] = []
        self._drop_insert_index: Optional[int] = None
        self._drag_source_path: Optional[str] = None
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.setAcceptDrops(True)
        self._rebuild_thumbs()

    def sizeHint(self) -> QSize:
        return self._HINT_SIZE

    def minimumSizeHint(self) -> QSize:
        return self._MIN_HINT_SIZE

    def source_paths(self) -> list[str]:
        return list(self._source_paths)

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
        if event.mimeData().hasFormat(_EDIT_SOURCE_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._update_drop_index(event.pos(), event)

    def _update_drop_index(self, pos: QPoint, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasFormat(_EDIT_SOURCE_MIME):
            event.ignore()
            return
        self._set_drop_insert_index(self._insert_index_at(pos))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_index()
        super().dragLeaveEvent(event)

    def _clear_drop_index(self) -> None:
        self._set_drop_insert_index(None)

    def dropEvent(self, event: QDropEvent) -> None:
        self._perform_drop(event.pos(), event)

    def _perform_drop(self, pos: QPoint, event: QDropEvent) -> None:
        if not event.mimeData().hasFormat(_EDIT_SOURCE_MIME):
            event.ignore()
            return
        source_path = bytes(
            event.mimeData().data(_EDIT_SOURCE_MIME)
        ).decode("utf-8")
        insert_index = self._insert_index_at(pos)
        self._clear_drop_index()
        self._reorder_path(source_path, insert_index)
        event.acceptProposedAction()


def _activate_source_in_main_window(main_window, path: str) -> None:
    if main_window is None or not path:
        return
    main_window.set_current_image_by_path(path)
    displayed = main_window.get_displayed_images() or []
    if path not in displayed:
        return
    idx = displayed.index(path)
    main_window.view_mode_manager.open_browse_view(idx)


class ImageGenEditDialog(QDialog):
    """Source preview + dynamically built edit configuration fields."""

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
    ):
        super().__init__(parent)
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
        self._fields_form: Optional[QFormLayout] = None
        self._source_preview: Optional[_SourceImagePreview] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._use_last_generated_cb: Optional[QCheckBox] = None

        initial = resolve_initial_plugin(
            self._plugins,
            function=function,
            initial_plugin_id=initial_plugin_id,
        )
        if initial is None:
            raise ValueError(f"No available plugins for function {function!r}")
        self.plugin = initial
        self._load_plugin_state(
            saved_override=initial_values if initial_values else None
        )

        apply_image_gen_dialog_shell(
            self, window_title=window_title, min_width=880, min_height=520
        )
        self._build_ui()
        if initial_prompt:
            self.set_prompt_text(initial_prompt)

        self._geometry_restore_attempted = False
        self._geometry_was_restored = False
        self.finished.connect(self._save_geometry)

    def _load_plugin_state(self, *, saved_override: Optional[Dict[str, Any]] = None) -> None:
        saved = saved_override
        if saved is None:
            saved = load_dialog_settings(
                self._function, fallback_plugin_id=self.plugin.plugin_id
            )
        self._values = self.plugin.merged_values(saved)
        self._specs = self.plugin.field_specs(saved)

    def _save_geometry(self) -> None:
        try:
            save_imagegen_dialog_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def showEvent(self, event):
        if not self._geometry_restore_attempted:
            self._geometry_restore_attempted = True
            try:
                geom_hex = load_imagegen_dialog_geometry_hex()
                if geom_hex:
                    self._geometry_was_restored = restore_dialog_geometry_hex(
                        self, geom_hex, self.parent()
                    )
            except Exception:
                pass
        super().showEvent(event)
        if not self._geometry_was_restored:
            QTimer.singleShot(0, lambda: _center_styled_dialog_on_screen(self, self.parent()))
        QTimer.singleShot(0, self._raise_and_activate)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_J:
            event_mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if event_mods == Qt.KeyboardModifier.NoModifier or event_mods == 0:
                main_window = resolve_image_gen_main_window(self)
                mgr = (
                    getattr(main_window, "status_bar_manager", None)
                    if main_window
                    else None
                )
                if mgr is not None and mgr.show_imagegen_task_menu_from_keyboard():
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _raise_and_activate(self) -> None:
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        try:
            save_dialog_settings(self._function, self.collect_values())
        except Exception:
            pass
        self._save_geometry()
        super().closeEvent(event)

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        if self._source_preview is not None:
            self._source_preview.set_source_path(self.source_path)

    def _on_source_paths_reordered(self, paths: list[str]) -> None:
        self._source_paths = list(paths)
        if self._source_paths:
            self.source_path = self._source_paths[0]

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = ImageGenPreviewSplitter(self)

        preview_host = QFrame()
        preview_host.setFrameShape(QFrame.Shape.NoFrame)
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        main_window = resolve_image_gen_main_window(self)
        if self._multi_source:

            def _on_thumb_activate(path: str) -> None:
                _activate_source_in_main_window(main_window, path)

            preview_widget = _MultiSourceImagePreview(
                self._source_paths,
                _on_thumb_activate,
                self._on_source_paths_reordered,
                preview_host,
            )
            preview_layout.addWidget(preview_widget, 1)
        else:
            self._source_preview = _SourceImagePreview(self.source_path, preview_host)
            self._source_nav = ImageGenSourceNavRow(
                main_window,
                self._on_source_image_changed,
                preview_host,
                initial_source_path=self.source_path,
            )
            self._source_nav.set_center_widget(self._source_preview)
            preview_layout.addWidget(self._source_nav)
        splitter.add_preview_pane(preview_host)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fields_inner = QWidget()
        self._fields_form = QFormLayout(fields_inner)
        configure_image_gen_form_layout(self._fields_form)
        self._fields_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        (
            model_row,
            self._model_combo,
            self._model_comment_label,
            self._plugins_by_id,
        ) = build_model_selector_row(
            self._plugins,
            selected_plugin_id=self.plugin.plugin_id,
            parent=self,
        )
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        apply_model_combo_tooltip(self._model_combo)
        self._fields_form.addRow("Model:", model_row)

        self._populate_field_rows()
        scroll.setWidget(fields_inner)
        splitter.add_controls_pane(scroll)
        layout.addWidget(splitter, 1)
        if self._source_nav is not None:
            install_source_nav_keyboard_shortcuts(self, self._source_nav)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        apply_dialog_button_tooltips(buttons)
        buttons.accepted.connect(self._on_generate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _clear_field_rows(self) -> None:
        if self._fields_form is None:
            return
        while self._fields_form.rowCount() > 1:
            self._fields_form.removeRow(1)
        self._widgets.clear()
        self._use_last_generated_cb = None

    def _populate_field_rows(self) -> None:
        if self._fields_form is None:
            return
        self._clear_field_rows()

        spec_keys = {s.key for s in self._specs}
        combine_guidance_lora = (
            "guidance_scale" in spec_keys and "mflux_lora" in spec_keys
        )
        combine_seed_random = field_specs_share_seed_row(spec_keys)

        for spec in self._specs:
            if combine_guidance_lora and spec.key == "mflux_lora":
                continue
            if combine_seed_random and spec.key == "random_seed":
                continue

            widget, extra = self._widget_for_spec(spec)
            self._widgets[spec.key] = (widget, extra, spec)

            if combine_guidance_lora and spec.key == "guidance_scale":
                lora_spec = next(s for s in self._specs if s.key == "mflux_lora")
                lora_widget, lora_extra = self._widget_for_spec(lora_spec)
                self._widgets[lora_spec.key] = (lora_widget, lora_extra, lora_spec)
                row_w = QWidget()
                row = QHBoxLayout(row_w)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(widget, 1)
                row.addWidget(QLabel("LoRA:"), 0)
                row.addWidget(lora_widget, 0)
                self._fields_form.addRow(spec.label, row_w)
                continue

            if spec.kind == "text" and spec.key == "prompt":
                row_w = QWidget()
                row = QHBoxLayout(row_w)
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(widget, 1)
                import_btn = QPushButton("Import")
                connect_import_button_with_option_modifier(
                    import_btn, self._on_import_prompt
                )
                apply_edit_import_button_tooltip(import_btn)
                row.addWidget(import_btn, 0, Qt.AlignmentFlag.AlignTop)
                self._fields_form.addRow(spec.label, row_w)
            elif combine_seed_random and spec.key == "seed":
                random_spec = next(s for s in self._specs if s.key == "random_seed")
                random_widget, random_extra = self._widget_for_spec(random_spec)
                self._widgets[random_spec.key] = (
                    random_widget,
                    random_extra,
                    random_spec,
                )
                self._fields_form.addRow(
                    spec.label,
                    build_seed_and_random_seed_row(widget, random_widget),
                )
            elif spec.kind == "seed":
                row = QHBoxLayout()
                row.addWidget(widget)
                self._fields_form.addRow(spec.label, self._wrap(row))
            elif spec.key == "copies":
                row_w = QWidget()
                col = QVBoxLayout(row_w)
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(4)
                col.addWidget(widget)
                check_row = QHBoxLayout()
                check_row.setContentsMargins(0, 0, 0, 0)
                check_row.addStretch(1)
                self._use_last_generated_cb = QCheckBox("Use last generated image")
                self._use_last_generated_cb.setChecked(
                    bool(self._values.get("use_last_generated_image", False))
                )
                self._use_last_generated_cb.setToolTip(
                    "When generating multiple copies, use each finished image "
                    "as the input for the next copy."
                )
                check_row.addWidget(self._use_last_generated_cb, 0)
                col.addLayout(check_row)
                self._fields_form.addRow(spec.label, row_w)
            else:
                self._fields_form.addRow(spec.label, widget)

        if self._source_nav is not None:
            refresh_source_nav_keyboard_shortcuts(self)

    def _on_model_combo_changed(self, _index: int = 0) -> None:
        plugin_id = self._model_combo.currentData()
        new_plugin = self._plugins_by_id.get(plugin_id)
        if (
            new_plugin is None
            or new_plugin.plugin_id == self.plugin.plugin_id
            or not new_plugin.is_available()
        ):
            return
        current = self.collect_values()
        prompt_entry = self._widgets.get("prompt")
        if prompt_entry is not None:
            widget, _, spec = prompt_entry
            if spec.kind == "text":
                current["prompt"] = widget.toPlainText()
        try:
            save_dialog_settings(self._function, current)
        except Exception:
            pass
        self.plugin = new_plugin
        self._load_plugin_state(saved_override=current)
        sync_model_comment_label(self._model_comment_label, new_plugin)
        self._populate_field_rows()
        save_active_plugin_id_for_function(self._function, new_plugin.plugin_id)

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _on_import_prompt(self, *, option_held: bool = False) -> None:
        if not self.source_path:
            show_styled_warning(self, "Import", "No image selected.")
            return
        raw_bytes = get_usercomment_from_path(self.source_path)
        if raw_bytes is None:
            show_styled_warning(
                self,
                "Import",
                "No EXIF user comment was found for this image.",
            )
            return
        full_text = decode_usercomment(raw_bytes)
        prompt_text = truncate_usercomment_before_prompt(full_text).strip()
        if not prompt_text:
            show_styled_warning(
                self,
                "Import",
                "The EXIF user comment is empty.",
            )
            return
        self.set_prompt_text(prompt_text)
        if option_held:
            apply_import_extras_from_image_path(self, self.source_path)

    def set_prompt_text(self, text: str) -> None:
        entry = self._widgets.get("prompt")
        if entry is None:
            return
        widget, _, spec = entry
        if spec.kind == "text":
            widget.setPlainText(text)

    def _widget_for_spec(self, spec: FieldSpec):
        if spec.kind == "text":
            edit = QPlainTextEdit()
            edit.setPlainText(str(spec.default or ""))
            edit.setMinimumHeight(120 if spec.key == "prompt" else 48)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            return edit, None

        if spec.kind == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(spec.default))
            apply_field_control_tooltips(spec, cb)
            return cb, None

        if spec.kind == "choice":
            combo = QComboBox()
            for c in spec.choices or ():
                if isinstance(c, (tuple, list)) and len(c) >= 2:
                    combo.addItem(str(c[0]), c[1])
                else:
                    combo.addItem(str(c), c)
            idx = combo.findData(spec.default)
            if idx < 0:
                idx = combo.findText(str(spec.default))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            return combo, None

        if spec.kind == "int_slider":
            slider = QSlider(Qt.Orientation.Horizontal)
            step = int(spec.step or 1)
            lo = int(spec.min_value or 0)
            hi = int(spec.max_value or 100)
            slider.setMinimum(lo)
            slider.setMaximum(hi)
            slider.setSingleStep(step)
            slider.setPageStep(max(step, (hi - lo) // 10))
            val = int(spec.default or lo)
            val = max(lo, min(hi, val))
            slider.setValue(val)
            spin = QSpinBox()
            spin.setMinimum(lo)
            spin.setMaximum(hi)
            spin.setSingleStep(step)
            spin.setValue(val)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            apply_field_control_tooltips(spec, slider, slider=slider, spin=spin)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(spin)
            return self._wrap(row), None

        if spec.kind == "float_slider":
            slider = QSlider(Qt.Orientation.Horizontal)
            step = float(spec.step or 0.1)
            lo = float(spec.min_value or 0.0)
            hi = float(spec.max_value or 10.0)
            scale = max(1, int(round(1.0 / step)))
            slider.setMinimum(int(lo * scale))
            slider.setMaximum(int(hi * scale))
            val = float(spec.default or lo)
            val = max(lo, min(hi, val))
            slider.setValue(int(val * scale))
            label = QLabel(f"{val:.2f}" if step < 0.1 else f"{val:.1f}")

            def update_label(v: int, lbl=label, sc=scale, st=step):
                lbl.setText(f"{v / sc:.2f}" if st < 0.1 else f"{v / sc:.1f}")

            slider.valueChanged.connect(update_label)
            apply_field_control_tooltips(spec, slider, slider=slider)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(label)
            return self._wrap(row), scale

        if spec.kind == "seed":
            spin = QSpinBox()
            spin.setMinimum(0)
            spin.setMaximum(2**31 - 1)
            spin.setValue(int(spec.default or 0))
            return spin, None

        label = QLabel(str(spec.default))
        return label, None

    def collect_values(self) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(self._values)
        for key, (widget, extra, spec) in self._widgets.items():
            if spec.kind == "text":
                out[key] = widget.toPlainText()
            elif spec.kind == "bool":
                out[key] = widget.isChecked()
            elif spec.kind == "choice":
                val = widget.currentData()
                if spec.key == "mflux_lora":
                    from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

                    val = coerce_lora_preset_id(val)
                out[key] = val
            elif spec.kind == "int_slider":
                inner = widget.layout()
                spin = inner.itemAt(1).widget()
                out[key] = spin.value()
            elif spec.kind == "float_slider":
                inner = widget.layout()
                slider = inner.itemAt(0).widget()
                scale = extra or 10
                out[key] = slider.value() / scale
            elif spec.kind == "seed":
                out[key] = widget.value()
            else:
                out[key] = getattr(widget, "text", lambda: "")()
        out["source_image_path"] = self.source_path
        out["source_image_paths"] = list(self._source_paths)
        if self._use_last_generated_cb is not None:
            out["use_last_generated_image"] = self._use_last_generated_cb.isChecked()
        return out

    def _on_generate(self) -> None:
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        prompt_spec = next((s for s in self._specs if s.key == "prompt"), None)
        if prompt_spec is not None and prompt_spec.required:
            prompt = (values.get("prompt") or "").strip()
            if not prompt:
                label = prompt_spec.label or "Edit prompt"
                show_styled_warning(
                    self,
                    f"{label} required",
                    f"Enter {label.lower()} before generating.",
                )
                return
        if not validate_copies_require_random_seed(self, values):
            return
        save_dialog_settings(self._function, values)
        save_active_plugin_id_for_function(self._function, self.plugin.plugin_id)
        self._result_values = values
        self.accept()

    def accepted_values(self) -> Optional[Dict[str, Any]]:
        return getattr(self, "_result_values", None)

    def accepted_plugin(self) -> Optional[ImageGenModelPlugin]:
        return getattr(self, "_result_values", None) and self.plugin
