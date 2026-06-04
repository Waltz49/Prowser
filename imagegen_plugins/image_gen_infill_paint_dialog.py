#!/usr/bin/env python3
"""Infill-by-painting dialog: paint mask over active image, submit to MFLUX infill."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_INFILL,
    save_active_plugin_id_for_function,
)
from imagegen_plugins.image_gen_dialog import (
    ImageGenDialog,
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    validate_copies_require_random_seed,
)
from imagegen_plugins.image_gen_model_availability import confirm_model_download_if_needed
from imagegen_plugins.image_gen_persistence import (
    load_infill_paint_dialog_geometry_hex,
    save_dialog_settings,
    save_infill_paint_dialog_geometry_hex,
)
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.infill_paint_canvas import InfillPaintCanvas
from imagegen_plugins.image_gen_source_nav import (
    ImageGenSourceNavRow,
    install_source_nav_keyboard_shortcuts,
    resolve_image_gen_main_window,
)
from imagegen_plugins.pixelmator_export import persist_paint_infill_exports
from theme_service import get_active_theme
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
)

INFILL_PAINT_DIALOG_TITLE = "Infill by Painting"
_SUBMIT_NOTICE_TEXT = "Infill job submitted"
_SUBMIT_NOTICE_VISIBLE_MS = 5000
_SUBMIT_NOTICE_FADE_MS = 1000
_SUBMIT_NOTICE_GAP_MM = 2.0
_INFILL_PAINT_PROMPT_LINES = 3


def active_image_path_for_infill(main_window) -> Optional[str]:
    """Active image for infill paint: browse current or single thumbnail selection."""
    if main_window is None:
        return None
    image_path = None
    if main_window.current_view_mode == "browse":
        if hasattr(main_window, "get_current_image_path"):
            image_path = main_window.get_current_image_path()
    elif main_window.current_view_mode == "thumbnail":
        if hasattr(main_window, "selection_manager") and main_window.selection_manager:
            selected_files = main_window.selection_manager.get_selected_files()
            if selected_files and len(selected_files) == 1:
                image_path = selected_files[0]
    if not image_path or not os.path.isfile(image_path):
        return None
    return image_path


class InfillPaintSettingsDialog(ImageGenDialog):
    """Infill model/steps settings; embedded in paint dialog or shown standalone."""

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        source_path: str,
        parent=None,
        *,
        embedded: bool = False,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
    ):
        self._embedded = embedded
        self._source_path = os.path.abspath(source_path)
        super().__init__(
            plugins,
            FUNCTION_INFILL,
            parent,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=initial_values,
            window_title="Infill Settings",
        )
        self.finished.disconnect(self._save_geometry)
        if embedded:
            self.setWindowFlags(Qt.Widget)
            self.setMinimumSize(0, 0)

    def _save_geometry(self) -> None:
        pass

    def showEvent(self, event):
        if self._embedded:
            QWidget.showEvent(self, event)
            return
        QDialog.showEvent(self, event)
        QTimer.singleShot(0, lambda: _center_styled_dialog_on_screen(self, self.parent()))
        QTimer.singleShot(0, self._raise_and_activate)

    def closeEvent(self, event):
        QDialog.closeEvent(self, event)

    def _build_ui(self) -> None:
        super()._build_ui()
        buttons = self.findChild(QDialogButtonBox)
        if buttons is not None:
            if self._embedded:
                buttons.hide()
                layout = self.layout()
                if layout is not None:
                    layout.removeWidget(buttons)
                buttons.setParent(None)
                buttons.deleteLater()
            else:
                ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
                if ok_btn is not None:
                    ok_btn.setText("Done")

    def _needs_prompt_side_column(self) -> bool:
        return False

    def _widget_for_spec(self, spec: FieldSpec):
        widget, extra = super()._widget_for_spec(spec)
        if spec.kind == "text" and spec.key == "prompt":
            from imagegen_plugins.image_gen_form_layout import (
                image_gen_prompt_height_for_lines,
            )

            widget.setMinimumHeight(
                image_gen_prompt_height_for_lines(
                    _INFILL_PAINT_PROMPT_LINES, widget.fontMetrics()
                )
            )
        return widget, extra

    def _show_import_button(self) -> bool:
        return bool(self._source_path)

    def _active_image_path_for_import(self) -> Optional[str]:
        return self._source_path

    def _on_generate(self) -> None:
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        if not validate_copies_require_random_seed(self, values):
            return
        save_dialog_settings(FUNCTION_INFILL, values)
        save_active_plugin_id_for_function(FUNCTION_INFILL, self.plugin.plugin_id)
        self._result_values = values
        self.accept()


class ImageGenInfillPaintDialog(QDialog):
    """Paint infill mask over the active image; submit without closing."""

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        source_path: str,
        controller,
        main_window,
        parent=None,
        *,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent or main_window)
        self._plugins = list(plugins)
        self._controller = controller
        self._main_window = main_window
        self.source_path = os.path.abspath(source_path)
        self._canvas: Optional[InfillPaintCanvas] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._values: Dict[str, Any] = {}
        self._initial_mask_path: str = ""
        self._submit_notice: Optional[QLabel] = None
        self._submit_notice_opacity: Optional[QGraphicsOpacityEffect] = None
        self._submit_notice_timer: Optional[QTimer] = None
        self._submit_notice_fade: Optional[QPropertyAnimation] = None
        self._infill_btn: Optional[QPushButton] = None
        self._settings: Optional[InfillPaintSettingsDialog] = None
        self._initial_plugin_id = initial_plugin_id
        self._initial_prompt = initial_prompt
        self._initial_values = initial_values

        if initial_values:
            mask_path = str(initial_values.get("pixelmator_mask_path") or "")
            if mask_path and os.path.isfile(mask_path):
                self._initial_mask_path = mask_path

        apply_image_gen_dialog_shell(
            self,
            window_title=INFILL_PAINT_DIALOG_TITLE,
            min_width=800,
            min_height=600,
        )
        self._build_ui()
        if self._initial_mask_path and self._canvas is not None:
            if not self._canvas.load_mask_from_path(self._initial_mask_path):
                show_styled_warning(
                    self,
                    "Infill",
                    "Could not restore the saved mask; paint a new mask if needed.",
                )

        self._geometry_restore_attempted = False
        self._geometry_was_restored = False
        self.finished.connect(self._save_geometry)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = ImageGenPreviewSplitter(self)

        canvas_host = QFrame()
        canvas_host.setFrameShape(QFrame.Shape.NoFrame)
        canvas_host_layout = QVBoxLayout(canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = InfillPaintCanvas(self.source_path, canvas_host)
        self._canvas.setMinimumHeight(360)
        self._source_nav = ImageGenSourceNavRow(
            resolve_image_gen_main_window(self),
            self._on_source_image_changed,
            canvas_host,
            initial_source_path=self.source_path,
        )
        self._source_nav.set_center_widget(self._canvas)
        canvas_host_layout.addWidget(self._source_nav)
        install_source_nav_keyboard_shortcuts(self, self._source_nav)
        splitter.add_preview_pane(canvas_host)

        self._settings = InfillPaintSettingsDialog(
            self._plugins,
            self.source_path,
            self,
            embedded=True,
            initial_plugin_id=self._initial_plugin_id,
            initial_prompt=self._initial_prompt,
            initial_values=self._initial_values,
        )
        splitter.add_controls_pane(self._settings)
        layout.addWidget(splitter, 1)

        clear_btn = QPushButton("Clear")
        close_btn = QPushButton("Close")
        self._infill_btn = QPushButton("Infill")
        clear_btn.clicked.connect(self._on_clear)
        close_btn.clicked.connect(self.reject)
        self._infill_btn.clicked.connect(self._on_infill)
        self._infill_btn.setDefault(True)
        self._infill_btn.setAutoDefault(True)

        self._submit_notice = QLabel(_SUBMIT_NOTICE_TEXT, self)
        self._submit_notice.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._submit_notice.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._submit_notice_opacity = QGraphicsOpacityEffect(self._submit_notice)
        self._submit_notice.setGraphicsEffect(self._submit_notice_opacity)
        self._style_submit_notice()
        self._submit_notice.hide()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(clear_btn)
        button_row.addWidget(close_btn)
        button_row.addWidget(self._infill_btn)
        layout.addLayout(button_row)

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        if self._canvas is not None:
            self._canvas.set_source_path(self.source_path)
        if self._settings is not None:
            self._settings._source_path = self.source_path

    def _on_clear(self) -> None:
        if self._canvas is not None:
            self._canvas.clear_mask()

    def _collect_run_values(self) -> Dict[str, Any]:
        if self._settings is None:
            return {}
        return finalize_run_values(
            self._settings.plugin.pipeline_id, self._settings.collect_values()
        )

    def _on_infill(self) -> None:
        if self._canvas is None or not self._canvas.has_paint():
            show_styled_warning(
                self,
                "Infill",
                "Paint a mask over the region to infill before running.",
            )
            return

        values = self._collect_run_values()
        if not validate_copies_require_random_seed(self, values):
            return

        try:
            export_meta = persist_paint_infill_exports(
                self.source_path,
                self._canvas.mask_image(),
            )
        except (OSError, RuntimeError, ValueError) as e:
            show_styled_warning(
                self,
                "Infill",
                f"Could not prepare base and mask: {e}",
            )
            return

        values.update(export_meta)
        save_dialog_settings(FUNCTION_INFILL, values)

        if self._settings is None:
            return
        if not confirm_model_download_if_needed(
            self._settings.plugin, self._main_window
        ):
            return

        from imagegen_plugins.image_gen_active_model import set_active_plugin_for_function

        set_active_plugin_for_function(
            self._main_window, FUNCTION_INFILL, self._settings.plugin
        )
        if self._controller.start_generation(self._settings.plugin, values):
            self._show_submit_notice()

    def _style_submit_notice(self) -> None:
        if self._submit_notice is None:
            return
        theme = get_active_theme()
        self._submit_notice.setStyleSheet(
            f"""
            QLabel {{
                color: {theme.dialog_text_color_hex};
                background-color: {theme.button_bg_default_hex};
                border: 1px solid {theme.border_default_hex};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            """
        )

    def _submit_notice_gap_px(self) -> int:
        return max(4, int(round(_SUBMIT_NOTICE_GAP_MM / 25.4 * self.logicalDpiY())))

    def _position_submit_notice(self) -> None:
        if self._submit_notice is None or self._infill_btn is None:
            return
        self._submit_notice.adjustSize()
        notice_w = self._submit_notice.sizeHint().width()
        notice_h = self._submit_notice.sizeHint().height()
        btn_origin = self._infill_btn.mapTo(self, QPoint(0, 0))
        x = btn_origin.x() + self._infill_btn.width() - notice_w
        y = btn_origin.y() - self._submit_notice_gap_px() - notice_h
        self._submit_notice.setGeometry(x, y, notice_w, notice_h)
        self._submit_notice.raise_()

    def _show_submit_notice(self) -> None:
        if self._submit_notice is None or self._submit_notice_opacity is None:
            return
        if self._submit_notice_fade is not None:
            self._submit_notice_fade.stop()
            self._submit_notice_fade.deleteLater()
            self._submit_notice_fade = None
        if self._submit_notice_timer is not None:
            self._submit_notice_timer.stop()
            self._submit_notice_timer.deleteLater()
            self._submit_notice_timer = None
        self._submit_notice_opacity.setOpacity(1.0)
        self._position_submit_notice()
        self._submit_notice.show()
        self._submit_notice.raise_()
        self._submit_notice_timer = QTimer(self)
        self._submit_notice_timer.setSingleShot(True)
        self._submit_notice_timer.timeout.connect(self._fade_out_submit_notice)
        self._submit_notice_timer.start(_SUBMIT_NOTICE_VISIBLE_MS)

    def _fade_out_submit_notice(self) -> None:
        if self._submit_notice is None or self._submit_notice_opacity is None:
            return
        self._submit_notice_fade = QPropertyAnimation(
            self._submit_notice_opacity, b"opacity", self
        )
        self._submit_notice_fade.setDuration(_SUBMIT_NOTICE_FADE_MS)
        self._submit_notice_fade.setStartValue(1.0)
        self._submit_notice_fade.setEndValue(0.0)
        self._submit_notice_fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._submit_notice_fade.finished.connect(self._hide_submit_notice)
        self._submit_notice_fade.start()

    def _hide_submit_notice(self) -> None:
        if self._submit_notice is None or self._submit_notice_opacity is None:
            return
        self._submit_notice.hide()
        self._submit_notice_opacity.setOpacity(1.0)
        if self._submit_notice_fade is not None:
            self._submit_notice_fade.deleteLater()
            self._submit_notice_fade = None

    def _save_geometry(self) -> None:
        try:
            save_infill_paint_dialog_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def showEvent(self, event):
        if not self._geometry_restore_attempted:
            self._geometry_restore_attempted = True
            try:
                geom_hex = load_infill_paint_dialog_geometry_hex()
                if geom_hex:
                    self._geometry_was_restored = restore_dialog_geometry_hex(
                        self, geom_hex, self.parent()
                    )
            except Exception:
                pass
        super().showEvent(event)
        if not self._geometry_was_restored:
            QTimer.singleShot(0, self._apply_initial_geometry)
        QTimer.singleShot(0, self._raise_and_activate)

    def _apply_initial_geometry(self) -> None:
        app = QGuiApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            geom = screen.availableGeometry()
            w = max(self.minimumWidth(), int(geom.width() * 0.92))
            h = max(self.minimumHeight(), int(geom.height() * 0.92))
            self.resize(w, h)
        _center_styled_dialog_on_screen(self, self.parent())

    def _raise_and_activate(self) -> None:
        self.raise_()
        self.activateWindow()
        if self._canvas is not None:
            self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event):
        if self._settings is not None:
            try:
                save_dialog_settings(
                    FUNCTION_INFILL, self._settings.collect_values()
                )
                save_active_plugin_id_for_function(
                    FUNCTION_INFILL, self._settings.plugin.plugin_id
                )
            except Exception:
                pass
        self._save_geometry()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (
            self._submit_notice is not None
            and self._submit_notice.isVisible()
        ):
            self._position_submit_notice()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if self._canvas is not None:
            if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
                self._canvas.keyPressEvent(event)
                event.accept()
                return
            if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
                self._canvas.keyPressEvent(event)
                if event.isAccepted():
                    return
        super().keyPressEvent(event)
