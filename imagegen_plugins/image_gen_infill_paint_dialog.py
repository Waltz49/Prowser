#!/usr/bin/env python3
"""Infill-by-painting dialog: paint mask over active image, submit to MFLUX infill."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)
from imagegen_plugins.image_gen_dialog import (
    ImageGenDialog,
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    validate_copies_require_random_seed,
)
from imagegen_plugins.image_gen_function_switcher import (
    create_image_gen_action_buttons,
    create_image_gen_dialog_footer,
    install_image_gen_footer_keyboard_shortcuts,
)
from imagegen_plugins.image_gen_model_availability import confirm_model_download_if_needed
from imagegen_plugins.image_gen_persistence import (
    load_imagegen_dialog_geometry_hex,
    save_imagegen_dialog_geometry_hex,
    save_plugin_dialog_settings,
)
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_dim_limits import (
    APP_MAX_GENERATION_DIMENSION_DEFAULT,
    effective_max_for_plugin,
)
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.image_gen_session_state import (
    FunctionSessionState,
    mask_from_png_bytes,
    mask_to_png_bytes,
)
from imagegen_plugins.infill_paint_canvas import (
    InfillPaintCanvas,
    install_infill_paint_mask_keyboard_shortcuts,
    refresh_infill_paint_mask_keyboard_shortcuts,
)
from imagegen_plugins.image_gen_source_nav import (
    ImageGenSourceNavRow,
    install_source_nav_keyboard_shortcuts,
    resolve_image_gen_main_window,
)
from imagegen_plugins.pixelmator_export import persist_paint_infill_exports
from utils import (
    _center_styled_dialog_on_screen,
    save_dialog_geometry_hex,
    show_styled_warning,
)

INFILL_PAINT_DIALOG_TITLE = "Infill by painting"


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
            panel_mode=embedded,
        )
        if not embedded:
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

    def _show_import_button(self) -> bool:
        return bool(self._source_path)

    def _active_image_path_for_import(self) -> Optional[str]:
        return self._source_path

    def _image_path_for_import_size(self) -> Optional[str]:
        if not self._source_path:
            show_styled_warning(self, "Import Size", "No image selected.")
            return None
        return self._source_path

    def _on_generate(self) -> None:
        if self.plugin is None:
            return
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        if not validate_copies_require_random_seed(self, values):
            return
        save_plugin_dialog_settings(
            FUNCTION_INFILL, self.plugin.plugin_id, values
        )
        self._result_values = values
        self.accept()


class ImageGenInfillPaintDialog(QDialog):
    """Paint infill mask over the active image; submit without closing."""

    state_changed = Signal()

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
        panel_mode: bool = False,
    ):
        super().__init__(parent or main_window)
        self._panel_mode = panel_mode
        self._image_gen_persistent_panel = True
        self._function = FUNCTION_INFILL_PAINT
        self._plugins = list(plugins)
        self._controller = controller
        self._main_window = main_window
        self.source_path = os.path.abspath(source_path)
        self._canvas: Optional[InfillPaintCanvas] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._settings: Optional[InfillPaintSettingsDialog] = None
        self._initial_plugin_id = initial_plugin_id
        self._initial_prompt = initial_prompt
        self._initial_values = initial_values
        self._initial_mask_path = ""
        if initial_values:
            mask_path = str(initial_values.get("pixelmator_mask_path") or "")
            if mask_path and os.path.isfile(mask_path):
                self._initial_mask_path = mask_path

        if self._panel_mode:
            self.setWindowFlags(Qt.Widget)
            self.setMinimumSize(0, 0)
        else:
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
        if not self._panel_mode:
            self._geometry_restore_attempted = False
            self._geometry_was_restored = False
            self.finished.connect(self._save_geometry)

    def reject(self) -> None:
        from imagegen_plugins.image_gen_panel_shell import panel_mode_reject

        if panel_mode_reject(self):
            return
        super().reject()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                configure_image_gen_embedded_panel_layout,
            )

            configure_image_gen_embedded_panel_layout(layout, self)
        splitter = ImageGenPreviewSplitter(self)

        canvas_host = QFrame()
        canvas_host.setFrameShape(QFrame.Shape.NoFrame)
        canvas_host_layout = QVBoxLayout(canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = InfillPaintCanvas(
            self.source_path,
            canvas_host,
            max_side=self._canvas_max_generation_dimension(),
        )
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
        install_infill_paint_mask_keyboard_shortcuts(self, self._canvas)
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
        controls_pane = self._settings
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                wrap_image_gen_controls_with_unified_intro,
            )

            controls_pane = wrap_image_gen_controls_with_unified_intro(
                self._settings, self._function
            )
        splitter.add_controls_pane(controls_pane)
        layout.addWidget(splitter, 1)
        refresh_infill_paint_mask_keyboard_shortcuts(self)

        if not self._panel_mode:
            actions = create_image_gen_action_buttons(
                on_generate=self._on_infill,
                on_close=self.reject,
            )
            install_image_gen_footer_keyboard_shortcuts(self)
            layout.addWidget(
                create_image_gen_dialog_footer(self, self._function, actions)
            )
            refresh_infill_paint_mask_keyboard_shortcuts(self)
        else:
            self._canvas.maskChanged.connect(self.state_changed.emit)
            self._settings.state_changed.connect(self.state_changed.emit)
        if self._settings is not None:
            self._settings._model_combo.currentIndexChanged.connect(
                self._on_settings_model_changed
            )
        self._sync_canvas_max_generation_dimension()

    def _canvas_max_generation_dimension(self) -> int:
        if self._settings is not None and self._settings.plugin is not None:
            return effective_max_for_plugin(self._settings.plugin)
        if self._initial_plugin_id:
            for plugin in self._plugins:
                if plugin.plugin_id == self._initial_plugin_id:
                    return effective_max_for_plugin(plugin)
        return APP_MAX_GENERATION_DIMENSION_DEFAULT

    @property
    def plugin(self) -> Optional[ImageGenModelPlugin]:
        """Active model (lives on embedded settings panel; used by unified Generate enable)."""
        if self._settings is None:
            return None
        return self._settings.plugin

    def _sync_canvas_max_generation_dimension(self) -> None:
        if self._canvas is None:
            return
        self._canvas.set_max_generation_dimension(
            self._canvas_max_generation_dimension()
        )

    def _on_settings_model_changed(self, _index: int) -> None:
        self._sync_canvas_max_generation_dimension()
        if self._panel_mode:
            self.state_changed.emit()

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        if self._canvas is not None:
            self._canvas.set_source_path(self.source_path)
        if self._settings is not None:
            self._settings._source_path = self.source_path
        if self._source_nav is not None:
            self._source_nav.set_active_source_path(self.source_path)
        if self._panel_mode:
            self.state_changed.emit()

    def _collect_run_values(self) -> Dict[str, Any]:
        if self._settings is None or self._settings.plugin is None:
            return {}
        return finalize_run_values(
            self._settings.plugin.pipeline_id, self._settings.collect_values()
        )

    def run_generate(self) -> bool:
        if self._settings is not None and self._settings.plugin is None:
            return False
        if self._canvas is None or not self._canvas.has_paint():
            show_styled_warning(
                self,
                "Infill",
                "Paint a mask over the region to infill before running.",
            )
            return False

        values = self._collect_run_values()
        settings = self._settings
        if settings is None:
            return False
        if not validate_copies_require_random_seed(settings, values):
            return False

        try:
            export_meta = persist_paint_infill_exports(
                self.source_path,
                self._canvas.mask_image(),
                max_side=effective_max_for_plugin(self._settings.plugin),
            )
        except (OSError, RuntimeError, ValueError) as e:
            show_styled_warning(
                self,
                "Infill",
                f"Could not prepare base and mask: {e}",
            )
            return False

        values.update(export_meta)
        save_plugin_dialog_settings(
            FUNCTION_INFILL, self._settings.plugin.plugin_id, values
        )

        if self._settings is None:
            return False
        if not confirm_model_download_if_needed(
            self._settings.plugin, self._main_window
        ):
            return False

        from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

        return start_imagegen_without_closing(
            self, FUNCTION_INFILL, self._settings.plugin, values
        )

    def _on_infill(self) -> None:
        self.run_generate()

    def snapshot_state(self) -> FunctionSessionState:
        mask_bytes = None
        if self._canvas is not None:
            mask_bytes = mask_to_png_bytes(self._canvas.mask_image())
        plugin_id = ""
        values: Dict[str, Any] = {}
        if self._settings is not None:
            plugin_id = self._settings.plugin.plugin_id
            values = self._settings.collect_values()
        return FunctionSessionState(
            values=values,
            plugin_id=plugin_id,
            source_path=self.source_path,
            mask_png_bytes=mask_bytes,
        )

    def restore_state(
        self, state: Optional[FunctionSessionState], *, initial_prompt: Optional[str] = None
    ) -> None:
        if state is not None:
            if state.source_path and state.source_path != self.source_path:
                self._on_source_image_changed(state.source_path)
            if self._settings is not None and state.plugin_id:
                plugin = self._settings._plugins_by_id.get(state.plugin_id)
                if plugin is not None:
                    idx = self._settings._model_combo.findData(plugin.plugin_id)
                    if idx >= 0:
                        self._settings._model_combo.blockSignals(True)
                        self._settings._model_combo.setCurrentIndex(idx)
                        self._settings._model_combo.blockSignals(False)
                        self._settings.plugin = plugin
                self._settings._load_plugin_state(saved_override=state.values)
                self._settings._populate_field_rows()
            refresh_infill_paint_mask_keyboard_shortcuts(self)
            if state.mask_png_bytes and self._canvas is not None:
                mask = mask_from_png_bytes(state.mask_png_bytes)
                if mask is not None:
                    self._canvas.load_mask_image(mask)
        elif initial_prompt and self._settings is not None:
            self._settings.set_prompt_text(initial_prompt)

    def _save_geometry(self) -> None:
        try:
            save_imagegen_dialog_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def show(self):
        if self._panel_mode:
            super().show()
            return
        from utils import restore_dialog_geometry_before_first_show

        restore_dialog_geometry_before_first_show(
            self, load_imagegen_dialog_geometry_hex(), self.parent()
        )
        super().show()

    def showEvent(self, event):
        super().showEvent(event)
        refresh_infill_paint_mask_keyboard_shortcuts(self)
        if self._panel_mode:
            if self._canvas is not None:
                self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)
            return
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
        from utils import raise_dialog_without_space_hop

        raise_dialog_without_space_hop(self)
        if self._canvas is not None:
            self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event):
        if not self._panel_mode and self._settings is not None:
            try:
                save_plugin_dialog_settings(
                    FUNCTION_INFILL,
                    self._settings.plugin.plugin_id,
                    self._settings.collect_values(),
                )
            except Exception:
                pass
        if not self._panel_mode:
            self._save_geometry()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if not self._panel_mode and key == Qt.Key.Key_Escape and mods == Qt.KeyboardModifier.NoModifier:
            self.reject()
            event.accept()
            return
        if self._canvas is not None:
            if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
                self._canvas.keyPressEvent(event)
                event.accept()
                return
            if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
                self._canvas.keyPressEvent(event)
                if event.isAccepted():
                    return
        if self._panel_mode and key == Qt.Key.Key_Escape and mods == Qt.KeyboardModifier.NoModifier:
            from imagegen_plugins.image_gen_panel_shell import panel_mode_reject

            if panel_mode_reject(self):
                event.accept()
                return
        super().keyPressEvent(event)
