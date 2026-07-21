#!/usr/bin/env python3
"""Expand dialog: graphical placement canvas + dynamic model config."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_edit_custom_size import mount_custom_size_section
from imagegen_plugins.expand_placement_canvas import ExpandPlacementCanvas
from imagegen_plugins.image_gen_dialog import (
    EXPAND_IMAGE_DIALOG_TITLE,
    ImageGenDimensionAspectMixin,
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    apply_import_extras_from_image_path,
    create_image_gen_side_button_column,
    finalize_image_gen_side_button_column,
    load_import_prompt_from_path,
    pass_image_to_ai_checked,
    repopulate_image_gen_prompt_import_row,
    repopulate_image_gen_side_buttons,
    validate_copies_require_random_seed,
    wrap_image_gen_controls_with_side_buttons,
)
from imagegen_plugins.image_gen_function_switcher import (
    create_image_gen_action_buttons,
    create_image_gen_dialog_footer,
    install_image_gen_escape_to_close,
    install_image_gen_footer_keyboard_shortcuts,
    refresh_image_gen_footer_keyboard_shortcuts,
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
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from imagegen_plugins.flux_prompt_system_mount import (
    flux_prompt_system_override_for,
    schedule_deferred_flux_prompt_extras,
)
from imagegen_plugins.image_gen_model_selector import (
    apply_mflux_lora_collection_guard,
    collect_lora_field_values,
    build_model_selector_row,
    mount_image_gen_lora_field,
    refresh_dialog_mflux_lora_combo,
    resolve_initial_plugin,
    switch_plugin_persisted_settings_preserving_prompt,
    sync_image_gen_generate_enabled,
    sync_image_gen_lora_field,
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
from imagegen_plugins.imagegen_control_tooltips import (
    apply_edit_import_all_button_tooltip,
    apply_edit_import_text_button_tooltip,
    apply_field_control_tooltips,
    apply_model_combo_tooltip,
)
from imagegen_plugins.image_gen_source_nav import (
    ImageGenSourceNavRow,
    install_source_nav_keyboard_shortcuts,
    refresh_source_nav_keyboard_shortcuts,
    resolve_image_gen_main_window,
)
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
)


def active_image_path_for_expand(main_window) -> Optional[str]:
    """Active image for expand: browse current or single thumbnail selection."""
    from imagegen_plugins.image_gen_source_nav import (
        active_image_path_for_browse_or_thumbnail,
    )

    return active_image_path_for_browse_or_thumbnail(main_window)


class ImageGenExpandDialog(ImageGenDimensionAspectMixin, QDialog):
    """Graphical expand placement + dynamically built configuration fields."""

    state_changed = Signal()

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        function: str,
        source_path: str,
        parent=None,
        *,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
        window_title: str = EXPAND_IMAGE_DIALOG_TITLE,
        panel_mode: bool = False,
        installed: Optional[List[ImageGenModelPlugin]] = None,
        plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
        installed_flags: Optional[Dict[str, bool]] = None,
    ):
        super().__init__(parent)
        self._panel_mode = panel_mode
        self._image_gen_persistent_panel = True
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        self.source_path = os.path.abspath(source_path)
        self._widgets: Dict[str, Any] = {}
        self._specs: List[FieldSpec] = []
        self._param_panel: Optional[ImageGenParameterPanel] = None
        self._canvas: Optional[ExpandPlacementCanvas] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._fields_panel: Optional[ImageGenFieldsPanel] = None
        self._init_dim_aspect_state()
        self._flux_prompt_ai: Optional[ImageGenFluxPromptAi] = None
        self._flux_system_prompt_pane = None
        self._pass_image_to_ai_cb: Optional[QCheckBox] = None
        self._side_btn_host: Optional[QWidget] = None
        self._side_btn_col: Optional[QVBoxLayout] = None
        self._installed_list = installed
        self._prebuilt_plugins_by_id = plugins_by_id
        self._installed_flags: Dict[str, bool] = dict(installed_flags or {})
        self._defer_flux_prompt_extras = True

        initial = resolve_initial_plugin(
            self._plugins,
            function=function,
            initial_plugin_id=initial_plugin_id,
            installed=installed,
            plugins_by_id=plugins_by_id,
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
        if getattr(self, "_defer_flux_prompt_extras", False):
            schedule_deferred_flux_prompt_extras(self)
        if initial_prompt:
            self.set_prompt_text(initial_prompt)
        self._apply_initial_placement(initial_values)

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
        self._values = self.plugin.merged_values(saved)
        self._specs = self.plugin.field_specs(saved)

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
        if self._panel_mode:
            return
        if not self._geometry_was_restored:
            QTimer.singleShot(0, lambda: _center_styled_dialog_on_screen(self, self.parent()))
        QTimer.singleShot(0, self._raise_and_activate)

    def _raise_and_activate(self) -> None:
        from utils import raise_dialog_without_space_hop

        raise_dialog_without_space_hop(self)

    def closeEvent(self, event):
        if not self._panel_mode:
            from imagegen_plugins.imagegen_flux_prompt_ai import (
                cancel_dialog_flux_prompt_refine,
            )

            cancel_dialog_flux_prompt_refine(self)
        self._save_geometry()
        super().closeEvent(event)

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA pulldown after Settings → LoRA catalog changes."""
        sync_image_gen_lora_field(self)

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        if self._canvas is not None:
            self._canvas.set_source_path(self.source_path)
        if self._source_nav is not None:
            self._source_nav.set_active_source_path(self.source_path)
        if self._panel_mode:
            self.state_changed.emit()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                configure_image_gen_embedded_panel_layout,
            )

            configure_image_gen_embedded_panel_layout(layout, self)
        splitter = ImageGenPreviewSplitter(self)

        canvas_w = int(self._values.get("width", 1024))
        canvas_h = int(self._values.get("height", 1024))
        canvas_host = QFrame()
        canvas_host.setFrameShape(QFrame.Shape.NoFrame)
        canvas_host_layout = QVBoxLayout(canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = ExpandPlacementCanvas(
            self.source_path, canvas_w, canvas_h, canvas_host
        )
        self._canvas.setMinimumHeight(280)
        self._source_nav = ImageGenSourceNavRow(
            resolve_image_gen_main_window(self),
            self._on_source_image_changed,
            canvas_host,
            initial_source_path=self.source_path,
        )
        self._source_nav.set_center_widget(self._canvas)
        canvas_host_layout.addWidget(self._source_nav)
        splitter.add_preview_pane(canvas_host)

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
            installed=self._installed_list,
            plugins_by_id=self._prebuilt_plugins_by_id,
        )
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        apply_model_combo_tooltip(self._model_combo)
        self._fields_panel.add_labeled_field("Model", model_row, to_outer=True)
        sync_image_gen_generate_enabled(self, panel=self)
        self._lora_group, self._lora_field = mount_image_gen_lora_field(
            self._fields_panel,
            parent=self._fields_panel.widget,
        )
        self._lora_combo = self._lora_field.summary_combo

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

        self._connect_canvas_dimension_fields()
        if self._canvas is not None and self._panel_mode:
            self._canvas.placementChanged.connect(self.state_changed.emit)

    def _apply_initial_placement(
        self, initial_values: Optional[Dict[str, Any]]
    ) -> None:
        if self._canvas is None or not initial_values:
            return
        keys = ("placement_x", "placement_y", "placement_w", "placement_h")
        if not all(k in initial_values for k in keys):
            return
        try:
            px = int(initial_values["placement_x"])
            py = int(initial_values["placement_y"])
            pw = int(initial_values["placement_w"])
            ph = int(initial_values["placement_h"])
        except (TypeError, ValueError):
            return
        self._canvas.set_canvas_placement(px, py, pw, ph)

    def _populate_field_rows(self) -> None:
        if self._fields_panel is None or self.plugin is None:
            return
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        if self._param_panel is None:
            self._param_panel = ImageGenParameterPanel(
                self._fields_panel,
                build_options=default_widget_build_options(
                    non_prompt_text_min_height=48,
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
        if self._has_dim_fields():
            mount_custom_size_section(
                self,
                self._fields_panel,
                self._values,
                self._widgets,
                self._specs,
                effective_max_side=effective_max_for_plugin(self.plugin),
                pipeline_id=self.plugin.pipeline_id,
                build_options=self._param_panel._build_options,
                optional=False,
            )
        if not getattr(self, "_defer_flux_prompt_extras", False):
            from imagegen_plugins.flux_prompt_system_mount import (
                remount_flux_prompt_system_splitter,
            )

            remount_flux_prompt_system_splitter(self)
        self._repopulate_side_buttons()
        self._connect_canvas_dimension_fields()
        self._connect_dim_aspect_lock()
        self._restore_aspect_lock_from_values()
        self._apply_effective_max_to_dim_sliders()
        if self._canvas is not None:
            values = self.collect_values()
            self._canvas.set_canvas_size(
                int(values.get("width", 1024)),
                int(values.get("height", 1024)),
            )
        refresh_source_nav_keyboard_shortcuts(self)
        refresh_image_gen_footer_keyboard_shortcuts(self)
        self._connect_panel_dirty_tracking()

    def _connect_panel_dirty_tracking(self) -> None:
        if not self._panel_mode:
            return
        from imagegen_plugins.image_gen_panel_dirty import connect_panel_field_widgets

        connect_panel_field_widgets(self, self.state_changed.emit)

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

    def _connect_canvas_dimension_fields(self) -> None:
        for key in ("width", "height"):
            entry = self._widgets.get(key)
            if entry is None:
                continue
            widget, _, spec = entry
            if spec.kind != "int_slider":
                continue
            inner = widget.layout()
            spin = inner.itemAt(1).widget()
            spin.valueChanged.connect(self._on_canvas_dimension_changed)

    def _on_canvas_dimension_changed(self, _value: int) -> None:
        if self._canvas is None:
            return
        values = self.collect_values()
        self._canvas.set_canvas_size(
            int(values.get("width", 1024)),
            int(values.get("height", 1024)),
        )

    def _main_window(self):
        from imagegen_plugins.image_gen_source_nav import resolve_image_gen_main_window

        return resolve_image_gen_main_window(self)

    def _repopulate_side_buttons(self) -> None:
        repopulate_image_gen_prompt_import_row(
            self, self._build_prompt_action_buttons()
        )
        repopulate_image_gen_side_buttons(self, None)

    def _build_prompt_action_buttons(self) -> Optional[List[QPushButton]]:
        if not (self._show_import_button() or bool(self.source_path)):
            return None
        buttons: List[QPushButton] = []
        import_text_btn = QPushButton("Import Prompt")
        import_text_btn.clicked.connect(self._on_import_prompt_text)
        apply_edit_import_text_button_tooltip(import_text_btn)
        buttons.append(import_text_btn)
        import_all_btn = QPushButton("Import Rest")
        import_all_btn.clicked.connect(self._on_import_available)
        apply_edit_import_all_button_tooltip(import_all_btn)
        buttons.append(import_all_btn)
        return buttons or None

    def _show_import_button(self) -> bool:
        mw = self._main_window()
        if mw is None:
            return False
        return mw.current_view_mode in ("browse", "thumbnail")

    def _import_prompt_text_from_source(self) -> bool:
        """Load prompt text from EXIF; return True on success."""
        if not self.source_path:
            show_styled_warning(self, "Import Text", "No image selected.")
            return False
        prompt_text = load_import_prompt_from_path(self, self.source_path)
        if prompt_text is None:
            return False
        self.set_prompt_text(prompt_text)
        return True

    def _on_import_prompt_text(self) -> None:
        self._import_prompt_text_from_source()

    def _image_path_for_import_size(self) -> Optional[str]:
        if not self.source_path:
            show_styled_warning(self, "Import Size", "No image selected.")
            return None
        return self.source_path

    def _on_import_available(self) -> None:
        if not self._import_prompt_text_from_source():
            return
        if not self.source_path:
            return
        apply_import_extras_from_image_path(self, self.source_path)

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
        lora_field = getattr(self, "_lora_field", None)
        collect_lora_field_values(out, lora_field)
        if self._canvas is not None:
            px, py, pw, ph = self._canvas.canvas_placement()
            out["placement_x"] = px
            out["placement_y"] = py
            out["placement_w"] = pw
            out["placement_h"] = ph
        out["source_image_path"] = self.source_path
        self._stash_aspect_lock_in_values(out)
        return out

    def _prepare_run_values(
        self, *, force_flux_ai_job: bool = False
    ) -> Optional[Dict[str, Any]]:
        if self.plugin is None:
            return None
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        from imagegen_plugins.ai_prompt_exit import apply_image_ai_exit_to_prompt_values

        apply_image_ai_exit_to_prompt_values(values)
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
                label = prompt_spec.label or "Prompt"
                show_styled_warning(
                    self,
                    f"{label} required",
                    f"Enter {label.lower()} before generating.",
                )
                return None
        if not validate_copies_require_random_seed(self, values):
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
        from imagegen_plugins.ai_prompt_exit import imagegen_values_for_dialog_save

        save_plugin_dialog_settings(
            self._function,
            self.plugin.plugin_id,
            imagegen_values_for_dialog_save(values, self),
        )
        from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

        return start_imagegen_without_closing(
            self, self._function, self.plugin, values
        )

    def snapshot_state(self):
        from imagegen_plugins.image_gen_session_state import FunctionSessionState

        placement = None
        if self._canvas is not None:
            placement = self._canvas.canvas_placement()
        return FunctionSessionState(
            values=self.collect_values(),
            plugin_id=self.plugin.plugin_id if self.plugin is not None else "",
            source_path=self.source_path,
            placement=placement,
        )

    def restore_state(self, state, *, initial_prompt: Optional[str] = None) -> None:
        if state is not None:
            if state.source_path and state.source_path != self.source_path:
                self.source_path = os.path.abspath(state.source_path)
                if self._canvas is not None:
                    self._canvas.set_source_path(self.source_path)
                if self._source_nav is not None:
                    self._source_nav.set_active_source_path(self.source_path)
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
            if state.placement and self._canvas is not None:
                px, py, pw, ph = state.placement
                self._canvas.set_canvas_placement(px, py, pw, ph)
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
