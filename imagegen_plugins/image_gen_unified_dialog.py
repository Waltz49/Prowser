#!/usr/bin/env python3
"""Single window hosting all image-generation function panels."""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from imagegen_plugins import plugins_for_function
from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)
from imagegen_plugins.image_gen_dialog import (
    DEFAULT_IMAGE_GEN_DIALOG_TITLE,
    ImageGenDialog,
    apply_image_gen_dialog_shell,
    apply_image_gen_preview_client_background,
)
from imagegen_plugins.image_gen_edit_dialog import (
    EDIT_IMAGE_DIALOG_TITLE,
    MAX_EDIT_SOURCE_IMAGES,
    ImageGenEditDialog,
    active_image_paths_for_edit,
)
from imagegen_plugins.image_gen_expand_dialog import (
    EXPAND_IMAGE_DIALOG_TITLE,
    ImageGenExpandDialog,
    active_image_path_for_expand,
)
from imagegen_plugins.image_gen_function_switcher import (
    create_image_gen_action_buttons,
    create_image_gen_close_on_generate_checkbox,
    create_image_gen_dialog_footer,
    install_image_gen_footer_keyboard_shortcuts,
    refresh_image_gen_footer_keyboard_shortcuts,
    refresh_image_gen_function_switcher_highlight,
    set_image_gen_cancel_visible,
)
from imagegen_plugins.image_gen_infill_dialog import (
    INFILL_IMAGE_DIALOG_TITLE,
    ImageGenInfillDialog,
)
from imagegen_plugins.image_gen_infill_paint_dialog import (
    INFILL_PAINT_DIALOG_TITLE,
    ImageGenInfillPaintDialog,
    active_image_path_for_infill,
)
from imagegen_plugins.image_gen_source_nav import (
    install_source_nav_keyboard_shortcuts,
    refresh_source_nav_keyboard_shortcuts,
)
from imagegen_plugins.image_gen_model_selector import (
    available_plugins,
    sync_image_gen_generate_enabled,
)
from imagegen_plugins.image_gen_panel_shell import IMAGE_GEN_UNIFIED_SHELL_MARGINS
from imagegen_plugins.image_gen_persistence import (
    load_close_dialog_on_generate,
    load_imagegen_dialog_geometry_hex,
    save_close_dialog_on_generate,
    save_dialog_sessions_batch,
    save_imagegen_dialog_geometry_hex,
    save_plugin_dialog_settings,
)
from imagegen_plugins.image_gen_session_state import FunctionSessionState
from imagegen_plugins.image_gen_submit_notice import (
    ImageGenSubmitNotice,
    submit_notice_text,
)
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_before_first_show,
    save_dialog_geometry_hex,
    show_styled_warning,
)

_FUNCTION_TITLES = {
    FUNCTION_CREATE: DEFAULT_IMAGE_GEN_DIALOG_TITLE,
    FUNCTION_EDIT: EDIT_IMAGE_DIALOG_TITLE,
    FUNCTION_EXPAND: EXPAND_IMAGE_DIALOG_TITLE,
    FUNCTION_INFILL: INFILL_IMAGE_DIALOG_TITLE,
    FUNCTION_INFILL_PAINT: INFILL_PAINT_DIALOG_TITLE,
}


def _persist_function_key(function: str) -> str:
    if function == FUNCTION_INFILL_PAINT:
        return FUNCTION_INFILL
    return function


class _UnifiedDismissFilter(QObject):
    """Intercept Escape anywhere in the shell tree before child QDialogs reject()."""

    def __init__(self, shell: "ImageGenUnifiedDialog") -> None:
        super().__init__(shell)
        self._shell = shell

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() != Qt.Key.Key_Escape:
            return False
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        self._shell._dismiss_discarding_current()
        event.accept()
        return True


class ImageGenUnifiedDialog(QDialog):
    """Shared shell with per-function client panels and session cache."""

    def __init__(self, main_window, controller, parent=None) -> None:
        super().__init__(parent or main_window)
        self._main_window = main_window
        self._controller = controller
        self._image_gen_persistent_panel = True
        self._function = FUNCTION_CREATE
        self._session: Dict[str, FunctionSessionState] = {}
        self._baselines: Dict[str, FunctionSessionState] = {}
        self._visited: Set[str] = set()
        self._panels: Dict[str, QWidget] = {}
        self._current_panel: Optional[QWidget] = None
        self._state_changed_panel: Optional[QWidget] = None
        self._dismissing = False
        self._dismiss_filter: Optional[_UnifiedDismissFilter] = None
        self._dismiss_filter_widgets: Set[int] = set()
        self._geometry_restore_attempted = False
        self._geometry_was_restored = False
        self._cancel_dirty_fast = False
        self._dirty_recheck_timer = QTimer(self)
        self._dirty_recheck_timer.setSingleShot(True)
        self._dirty_recheck_timer.timeout.connect(self._recheck_cancel_visibility)
        self._replace_job_id = ""
        self._replace_queue_signal_connected = False

        apply_image_gen_dialog_shell(
            self,
            window_title=_FUNCTION_TITLES[FUNCTION_CREATE],
            min_width=800,
            min_height=600,
        )

        root = QVBoxLayout(self)
        l, t, r, b = IMAGE_GEN_UNIFIED_SHELL_MARGINS
        root.setContentsMargins(l, t, r, b)
        root.setSpacing(6)
        self._content_host = QWidget()
        apply_image_gen_preview_client_background(self._content_host)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._content_host, 1)

        self._actions = create_image_gen_action_buttons(
            on_generate=self._on_generate,
            on_close=self._on_close,
            on_cancel=self._on_cancel,
            on_replace=self._on_replace,
        )
        from PySide6.QtWidgets import QPushButton

        self._replace_btn = self._actions.findChild(QPushButton, "imageGenReplaceButton")
        self._generate_btn = self._actions.findChild(QPushButton, "imageGenGenerateButton")
        self._submit_notice = ImageGenSubmitNotice(self, self._generate_btn)
        self._close_on_generate_cb = create_image_gen_close_on_generate_checkbox(
            on_changed=self._on_close_on_generate_changed,
        )
        self._close_on_generate_cb.blockSignals(True)
        self._close_on_generate_cb.setChecked(load_close_dialog_on_generate())
        self._close_on_generate_cb.blockSignals(False)
        self._footer = create_image_gen_dialog_footer(
            self,
            self._function,
            self._actions,
            center_widget=self._close_on_generate_cb,
        )
        root.addWidget(self._footer)

        self._dismiss_filter = _UnifiedDismissFilter(self)
        self._attach_dismiss_filter()
        install_source_nav_keyboard_shortcuts(self, None)
        install_image_gen_footer_keyboard_shortcuts(self)
        self.finished.connect(self._save_geometry)
        self.finished.connect(self._disconnect_replace_queue_signal)

    def set_queue_replace_context(self, job_id: Optional[str] = None) -> None:
        self._replace_job_id = (job_id or "").strip()
        if self._replace_job_id and not self._replace_queue_signal_connected:
            self._controller.queue_changed.connect(self._update_replace_visibility)
            self._replace_queue_signal_connected = True
        self._update_replace_visibility()

    def _clear_queue_replace_context(self) -> None:
        self._replace_job_id = ""
        self._update_replace_visibility()

    def _update_replace_visibility(self) -> None:
        if self._replace_btn is None:
            return
        visible = bool(self._replace_job_id) and self._controller.is_queued_job_replaceable(
            self._replace_job_id
        )
        self._replace_btn.setVisible(visible)
        self._replace_btn.setEnabled(visible)

    def _disconnect_replace_queue_signal(self) -> None:
        if not self._replace_queue_signal_connected:
            return
        try:
            self._controller.queue_changed.disconnect(self._update_replace_visibility)
        except (RuntimeError, TypeError):
            pass
        self._replace_queue_signal_connected = False

    def switch_to_function(
        self,
        function: str,
        *,
        initial_prompt: Optional[str] = None,
        auto_import_available: bool = False,
        seed_state: Optional[FunctionSessionState] = None,
    ) -> bool:
        """Show a function panel; return False if prerequisites are not met."""
        if function != self._function:
            self._clear_queue_replace_context()

        if function == self._function and self._current_panel is not None:
            if initial_prompt and self._current_panel is not None:
                restore = getattr(self._current_panel, "restore_state", None)
                if restore is not None and initial_prompt:
                    restore(None, initial_prompt=initial_prompt)
            return True

        if self._current_panel is not None:
            self._save_current_to_session()

        if seed_state is not None:
            self._session[function] = seed_state

        if not self._ensure_panel(function, initial_prompt=initial_prompt):
            return False

        panel = self._panels[function]
        state = self._session.get(function)
        restore = getattr(panel, "restore_state", None)
        if restore is not None:
            prompt = initial_prompt if state is None else None
            restore(state, initial_prompt=prompt)

        self._swap_panel(panel)
        self._function = function
        self._visited.add(function)
        self._baselines[function] = panel.snapshot_state()
        self._reset_cancel_dirty_fast_path()

        from imagegen_plugins.image_gen_menu import remember_imagegen_last_function

        remember_imagegen_last_function(self._main_window, function)

        self._update_chrome()
        if function == FUNCTION_CREATE and hasattr(panel, "_repopulate_side_buttons"):
            panel._repopulate_side_buttons()
        if auto_import_available and hasattr(panel, "_on_import_available"):
            QTimer.singleShot(0, panel._on_import_available)
        return True

    def _save_current_to_session(self) -> None:
        if self._current_panel is None:
            return
        snapshot = getattr(self._current_panel, "snapshot_state", None)
        if snapshot is None:
            return
        self._session[self._function] = snapshot()

    def _swap_panel(self, panel: QWidget) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.hide()
        self._content_layout.addWidget(panel, 1)
        panel.show()
        self._current_panel = panel
        if self._state_changed_panel is not panel:
            if self._state_changed_panel is not None:
                prior = getattr(self._state_changed_panel, "state_changed", None)
                if prior is not None:
                    try:
                        prior.disconnect(self._on_panel_state_changed)
                    except (RuntimeError, TypeError):
                        pass
            changed = getattr(panel, "state_changed", None)
            if changed is not None:
                changed.connect(self._on_panel_state_changed)
            self._state_changed_panel = panel
        nav = getattr(panel, "_source_nav", None)
        install_source_nav_keyboard_shortcuts(self, nav)
        refresh_source_nav_keyboard_shortcuts(self)
        refresh_source_nav_keyboard_shortcuts(panel)
        refresh_image_gen_footer_keyboard_shortcuts(self)
        refresh_image_gen_footer_keyboard_shortcuts(panel)
        self._attach_dismiss_filter()

    def _attach_dismiss_filter(self) -> None:
        if self._dismiss_filter is None:
            return
        for widget in (self, *self.findChildren(QWidget)):
            wid = id(widget)
            if wid in self._dismiss_filter_widgets:
                continue
            widget.installEventFilter(self._dismiss_filter)
            self._dismiss_filter_widgets.add(wid)

    def _on_panel_state_changed(self) -> None:
        # Defer full snapshot/compare so control repaints are not blocked on the
        # toggled/valueChanged stack (collect_values walks every field).
        if not self._cancel_dirty_fast:
            self._cancel_dirty_fast = True
            set_image_gen_cancel_visible(self._actions, True)
        sync_image_gen_generate_enabled(self, panel=self._current_panel)
        self._dirty_recheck_timer.start(200)

    def _reset_cancel_dirty_fast_path(self) -> None:
        self._cancel_dirty_fast = False
        self._dirty_recheck_timer.stop()

    def _recheck_cancel_visibility(self) -> None:
        dirty = self._is_dirty()
        self._cancel_dirty_fast = dirty
        set_image_gen_cancel_visible(self._actions, dirty)

    def _is_dirty(self) -> bool:
        if self._current_panel is None:
            return False
        baseline = self._baselines.get(self._function)
        snapshot = getattr(self._current_panel, "snapshot_state", None)
        if snapshot is None or baseline is None:
            return False
        return not snapshot().equals(baseline)

    def _update_cancel_visibility(self) -> None:
        set_image_gen_cancel_visible(self._actions, self._is_dirty())

    def _update_chrome(self) -> None:
        self.setWindowTitle(
            _FUNCTION_TITLES.get(self._function, DEFAULT_IMAGE_GEN_DIALOG_TITLE)
        )
        refresh_image_gen_function_switcher_highlight(
            self._footer, self, self._function
        )
        self._update_cancel_visibility()
        sync_image_gen_generate_enabled(self, panel=self._current_panel)

    def _ensure_panel(
        self,
        function: str,
        *,
        initial_prompt: Optional[str] = None,
    ) -> bool:
        if function in self._panels:
            return True
        if not self._validate_function(function):
            return False

        registered = plugins_for_function(function)
        if not available_plugins(registered):
            return False
        plugins = registered

        panel: QWidget
        if function == FUNCTION_CREATE:
            panel = ImageGenDialog(
                plugins,
                function,
                self._content_host,
                initial_prompt=initial_prompt,
                panel_mode=True,
            )
        elif function == FUNCTION_EDIT:
            source_paths = active_image_paths_for_edit(self._main_window)
            panel = ImageGenEditDialog(
                plugins,
                function,
                source_paths[0],
                self._content_host,
                source_paths=source_paths,
                initial_prompt=initial_prompt,
                panel_mode=True,
            )
        elif function == FUNCTION_EXPAND:
            source_path = active_image_path_for_expand(self._main_window)
            panel = ImageGenExpandDialog(
                plugins,
                function,
                source_path,
                self._content_host,
                initial_prompt=initial_prompt,
                panel_mode=True,
            )
        elif function == FUNCTION_INFILL_PAINT:
            source_path = active_image_path_for_infill(self._main_window)
            panel = ImageGenInfillPaintDialog(
                plugins,
                source_path,
                self._controller,
                self._main_window,
                self._content_host,
                initial_prompt=initial_prompt,
                panel_mode=True,
            )
        elif function == FUNCTION_INFILL:
            panel = ImageGenInfillDialog(
                plugins,
                function,
                self._content_host,
                initial_prompt=initial_prompt,
                panel_mode=True,
            )
        else:
            return False

        self._panels[function] = panel
        panel.hide()
        return True

    def _validate_function(self, function: str) -> bool:
        if function == FUNCTION_EDIT:
            if (
                self._main_window.current_view_mode == "thumbnail"
                and hasattr(self._main_window, "selection_manager")
                and self._main_window.selection_manager
                and len(self._main_window.selection_manager.get_selected_files())
                > MAX_EDIT_SOURCE_IMAGES
            ):
                show_styled_warning(
                    self._main_window,
                    "Edit",
                    f"Select at most {MAX_EDIT_SOURCE_IMAGES} images before using edit.",
                )
                return False
            if not active_image_paths_for_edit(self._main_window):
                show_styled_warning(
                    self._main_window,
                    "Edit",
                    "Select an image in browse view, or select up to "
                    f"{MAX_EDIT_SOURCE_IMAGES} thumbnails, before using edit.",
                )
                return False
        elif function == FUNCTION_EXPAND:
            if not active_image_path_for_expand(self._main_window):
                show_styled_warning(
                    self._main_window,
                    "Expand",
                    "Select an image in browse view, or select a single thumbnail, "
                    "before using expand.",
                )
                return False
        elif function == FUNCTION_INFILL_PAINT:
            if not active_image_path_for_infill(self._main_window):
                show_styled_warning(
                    self._main_window,
                    "Infill",
                    "Select an image in browse view, or select a single thumbnail, "
                    "before using infill by painting.",
                )
                return False
        return True

    def _on_close_on_generate_changed(self, checked: bool) -> None:
        try:
            save_close_dialog_on_generate(checked)
        except Exception:
            pass

    def _collect_validated_submit(self) -> Optional[Tuple[Any, Dict[str, Any]]]:
        if self._current_panel is None:
            return None
        plugin = getattr(self._current_panel, "plugin", None)
        prepare = getattr(self._current_panel, "_prepare_run_values", None)
        if plugin is None or prepare is None:
            return None
        values = prepare()
        if values is None:
            return None
        return plugin, values

    def _after_successful_submit(self) -> None:
        self._save_current_to_session()
        snapshot = getattr(self._current_panel, "snapshot_state", None)
        if snapshot is not None:
            self._baselines[self._function] = snapshot()
        self._reset_cancel_dirty_fast_path()
        self._update_cancel_visibility()
        if self._close_on_generate_cb.isChecked():
            self._close_after_successful_generate()
        else:
            self._submit_notice.show(submit_notice_text(self._function))

    def _on_generate(self) -> None:
        if self._current_panel is None:
            return
        run = getattr(self._current_panel, "run_generate", None)
        if run is None:
            return
        if run():
            self._after_successful_submit()

    def _on_replace(self) -> None:
        if not self._replace_job_id:
            return
        collected = self._collect_validated_submit()
        if collected is None:
            return
        plugin, values = collected
        from imagegen_plugins.image_gen_active_model import set_active_plugin_for_function
        from imagegen_plugins.image_gen_model_availability import (
            confirm_model_download_if_needed,
        )

        if not confirm_model_download_if_needed(plugin, self._main_window):
            return
        save_plugin_dialog_settings(self._function, plugin.plugin_id, values)
        set_active_plugin_for_function(self._main_window, self._function, plugin)
        if not self._controller.replace_queued_job(
            self._replace_job_id, plugin, values
        ):
            self._clear_queue_replace_context()
            show_styled_warning(
                self._main_window,
                "Replace job",
                "That queued job is no longer available (it may have started or been cancelled).",
            )
            return
        self._after_successful_submit()

    def _close_after_successful_generate(self) -> None:
        if self._dismissing:
            return
        self._dismissing = True
        self._persist_session_for_functions(self._visited)
        self.done(QDialog.DialogCode.Rejected)

    def _persist_session_for_functions(self, functions: Set[str]) -> None:
        batch = {}
        for function in functions:
            state = self._session.get(function)
            if state is None:
                continue
            key = _persist_function_key(function)
            batch[key] = (state.values, state.plugin_id)
        if not batch:
            return
        try:
            save_dialog_sessions_batch(batch)
        except Exception:
            pass

    def _on_close(self) -> None:
        if self._dismissing:
            return
        self._dismissing = True
        self._save_current_to_session()
        self._persist_session_for_functions(self._visited)
        self.done(QDialog.DialogCode.Rejected)

    def _dismiss_discarding_current(self) -> None:
        """Close immediately; persist other visited types, discard current if dirty."""
        if self._dismissing:
            return
        self._dismissing = True
        current = self._function
        was_dirty = self._is_dirty()
        if was_dirty:
            baseline = self._baselines.get(current)
            if baseline is not None:
                self._session[current] = baseline
        else:
            self._save_current_to_session()
        to_save = set(self._visited)
        if was_dirty:
            to_save.discard(current)
        self._persist_session_for_functions(to_save)
        self.done(QDialog.DialogCode.Rejected)

    def _on_cancel(self) -> None:
        self._dismiss_discarding_current()

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA fields on all cached function panels after Settings → LoRA edits."""
        for panel in self._panels.values():
            refresh = getattr(panel, "refresh_mflux_lora_combo", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass

    def refresh_generation_dim_limits(self) -> None:
        """Re-clamp width/height after app-wide max generation dimension changes."""
        for panel in self._panels.values():
            refresh = getattr(panel, "refresh_generation_dim_limits", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
            elif hasattr(panel, "_settings") and panel._settings is not None:
                sync = getattr(panel, "_sync_canvas_max_generation_dimension", None)
                if callable(sync):
                    try:
                        sync()
                    except Exception:
                        pass

    def _save_geometry(self) -> None:
        try:
            save_imagegen_dialog_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def show(self):
        self._dismissing = False
        restore_dialog_geometry_before_first_show(
            self, load_imagegen_dialog_geometry_hex(), self.parent()
        )
        super().show()
        self._attach_dismiss_filter()

    def showEvent(self, event):
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
        from utils import raise_dialog_without_space_hop

        raise_dialog_without_space_hop(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._submit_notice.reposition()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if (
            mods & Qt.KeyboardModifier.AltModifier
            and key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
        ):
            nav = getattr(self._current_panel, "_source_nav", None)
            if nav is not None:
                if key == Qt.Key.Key_Left:
                    nav.navigate_prev()
                else:
                    nav.navigate_next()
                event.accept()
                return
        if self._current_panel is not None and hasattr(
            self._current_panel, "keyPressEvent"
        ):
            if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight) or (
                key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier
            ):
                self._current_panel.keyPressEvent(event)
                if event.isAccepted():
                    return
        super().keyPressEvent(event)
