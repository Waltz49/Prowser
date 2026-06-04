#!/usr/bin/env python3
"""Expand dialog: graphical placement canvas + dynamic model config."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from imagegen_plugins.expand_placement_canvas import ExpandPlacementCanvas
from imagegen_plugins.image_gen_dialog import (
    EXPAND_IMAGE_DIALOG_TITLE,
    ImageGenDimensionAspectMixin,
    ImageGenPreviewSplitter,
    apply_image_gen_dialog_shell,
    apply_import_extras_from_image_path,
    build_seed_and_random_seed_row,
    create_image_gen_side_button_column,
    field_specs_share_seed_row,
    finalize_image_gen_side_button_column,
    load_import_prompt_from_path,
    repopulate_image_gen_side_buttons,
    validate_copies_require_random_seed,
    wrap_image_gen_controls_with_side_buttons,
)
from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_SEED_SPIN_MAX_WIDTH,
    ImageGenFieldsPanel,
    mount_image_gen_fields_in_scroll,
    populate_image_gen_field_rows,
    wrap_image_gen_slider_row,
)
from imagegen_plugins.image_gen_active_model import save_active_plugin_id_for_function
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from lmstudio_caption import is_lmstudio_services_available
from imagegen_plugins.image_gen_model_selector import (
    build_model_selector_row,
    refresh_dialog_mflux_lora_combo,
    resolve_initial_plugin,
    values_after_plugin_switch,
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
    apply_dim_helper_tooltips,
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


class ImageGenExpandDialog(ImageGenDimensionAspectMixin, QDialog):
    """Graphical expand placement + dynamically built configuration fields."""

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
    ):
        super().__init__(parent)
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        self.source_path = os.path.abspath(source_path)
        self._widgets: Dict[str, Any] = {}
        self._specs: List[FieldSpec] = []
        self._canvas: Optional[ExpandPlacementCanvas] = None
        self._source_nav: Optional[ImageGenSourceNavRow] = None
        self._fields_panel: Optional[ImageGenFieldsPanel] = None
        self._init_dim_aspect_state()
        self._flux_prompt_ai: Optional[ImageGenFluxPromptAi] = None
        self._side_btn_host: Optional[QWidget] = None
        self._side_btn_col: Optional[QVBoxLayout] = None

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
        self._apply_initial_placement(initial_values)

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

    def _raise_and_activate(self) -> None:
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA pulldown after Settings → LoRA catalog changes."""
        entry = self._widgets.get("mflux_lora")
        if entry is None:
            return
        lora_widget, _, lora_spec = entry
        if lora_spec.kind != "choice":
            return
        from imagegen_plugins.mflux_lora_presets import (
            coerce_lora_preset_id,
            repopulate_mflux_lora_combo,
        )

        repopulate_mflux_lora_combo(
            lora_widget,
            plugin=self.plugin,
            current_preset_id=coerce_lora_preset_id(
                (self._values or {}).get("mflux_lora", "none")
            ),
        )

    def _on_source_image_changed(self, path: str) -> None:
        self.source_path = os.path.abspath(path)
        if self._canvas is not None:
            self._canvas.set_source_path(self.source_path)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
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
        self._fields_panel = ImageGenFieldsPanel(self)
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
            selected_plugin_id=self.plugin.plugin_id,
            parent=self._fields_panel.widget,
        )
        self._model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        apply_model_combo_tooltip(self._model_combo)
        self._fields_panel.add_labeled_field("Model", model_row, to_outer=True)

        self._populate_field_rows()
        mount_image_gen_fields_in_scroll(scroll, self._fields_panel)
        controls = wrap_image_gen_controls_with_side_buttons(
            scroll, self._side_btn_host
        )
        splitter.add_controls_pane(controls)
        layout.addWidget(splitter, 1)
        install_source_nav_keyboard_shortcuts(self, self._source_nav)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        apply_dialog_button_tooltips(buttons)
        buttons.accepted.connect(self._on_generate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._connect_canvas_dimension_fields()

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

    def _clear_field_rows(self) -> None:
        if self._fields_panel is None:
            return
        self._fields_panel.clear(keep=1)
        self._widgets.clear()

    def _populate_field_rows(self) -> None:
        if self._fields_panel is None:
            return
        self._clear_field_rows()

        spec_keys = {s.key for s in self._specs}
        populate_image_gen_field_rows(
            self._fields_panel,
            self._specs,
            self._widgets,
            self._widget_for_spec,
            combine_seed_random=field_specs_share_seed_row(spec_keys),
            build_seed_and_random_seed_row=build_seed_and_random_seed_row,
        )
        self._repopulate_side_buttons()
        if self._has_dim_fields():
            self._aspect_checkbox = QCheckBox("Aspect ratio lock")
            self._aspect_checkbox.toggled.connect(self._on_aspect_lock_toggled)
            apply_dim_helper_tooltips(aspect_checkbox=self._aspect_checkbox)
            self._fields_panel.add_labeled_field(
                None, self._aspect_checkbox, stretch_control=False
            )

        self._connect_canvas_dimension_fields()
        self._connect_dim_aspect_lock()
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
        current = values_after_plugin_switch(self.collect_values(), new_plugin)
        try:
            save_dialog_settings(self._function, current)
        except Exception:
            pass
        self.plugin = new_plugin
        self._load_plugin_state(saved_override=current)
        sync_model_comment_label(self._model_comment_label, new_plugin)
        self._populate_field_rows()
        refresh_dialog_mflux_lora_combo(self)
        save_active_plugin_id_for_function(self._function, new_plugin.plugin_id)

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

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _main_window(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "current_view_mode"):
            return parent
        return None

    def _needs_prompt_side_column(self) -> bool:
        return (
            self._show_import_button()
            or self._has_dim_fields()
            or bool(self.source_path)
            or is_lmstudio_services_available()
        )

    def _repopulate_side_buttons(self) -> None:
        if not self._needs_prompt_side_column():
            repopulate_image_gen_side_buttons(self, None)
            return
        repopulate_image_gen_side_buttons(self, self._build_prompt_action_buttons())

    def _build_prompt_action_buttons(self) -> Optional[List[QPushButton]]:
        if not self._needs_prompt_side_column():
            return None
        buttons: List[QPushButton] = []
        if self._show_import_button() or bool(self.source_path):
            import_text_btn = QPushButton("Import Prompt")
            import_text_btn.clicked.connect(self._on_import_prompt_text)
            apply_edit_import_text_button_tooltip(import_text_btn)
            buttons.append(import_text_btn)
            import_all_btn = QPushButton("Import Available")
            import_all_btn.clicked.connect(self._on_import_available)
            apply_edit_import_all_button_tooltip(import_all_btn)
            buttons.append(import_all_btn)
        if self._has_dim_fields():
            screen_btn = QPushButton("Screen size")
            screen_btn.clicked.connect(self._on_screen_size_dims)
            buttons.append(screen_btn)
            square_btn = QPushButton("Square")
            square_btn.clicked.connect(self._on_square_dims)
            buttons.append(square_btn)
            reverse_btn = QPushButton("Reverse")
            reverse_btn.clicked.connect(self._on_reverse_dims)
            buttons.append(reverse_btn)
            apply_dim_helper_tooltips(
                screen_btn=screen_btn,
                square_btn=square_btn,
                reverse_btn=reverse_btn,
                aspect_checkbox=None,
            )
        buttons.extend(self._ensure_flux_prompt_ai().make_action_buttons())
        return buttons or None

    def _populate_prompt_side_buttons(self, btn_col: QVBoxLayout) -> None:
        buttons = self._build_prompt_action_buttons()
        if not buttons:
            return
        for button in buttons:
            btn_col.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        finalize_image_gen_side_button_column(btn_col)

    def _show_import_button(self) -> bool:
        mw = self._main_window()
        if mw is None:
            return False
        return mw.current_view_mode in ("browse", "thumbnail")

    @staticmethod
    def _screen_pixel_size() -> tuple[int, int]:
        app = QGuiApplication.instance()
        if app is None:
            return 1024, 1024
        screen = app.primaryScreen()
        if screen is None:
            return 1024, 1024
        geom = screen.geometry()
        return int(geom.width()), int(geom.height())

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

    def _on_import_available(self) -> None:
        if not self._import_prompt_text_from_source():
            return
        if not self.source_path:
            return
        if self._has_dim_fields():
            self._apply_import_dims_from_image(self.source_path)
        apply_import_extras_from_image_path(self, self.source_path)

    def get_prompt_text(self) -> str:
        entry = self._widgets.get("prompt")
        if entry is None:
            return ""
        widget, _, spec = entry
        if spec.kind == "text":
            return widget.toPlainText()
        return ""

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
            )
        return self._flux_prompt_ai

    def _widget_for_spec(self, spec: FieldSpec):
        if spec.kind == "text":
            edit = QPlainTextEdit()
            edit.setPlainText(str(spec.default or ""))
            edit.setMinimumHeight(72 if spec.key == "prompt" else 48)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            return edit, None

        if spec.kind == "bool":
            label = spec.label
            if spec.key == "random_seed":
                label = "Randomize"
            cb = QCheckBox(label)
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
            spin.setMaximumWidth(72)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            apply_field_control_tooltips(spec, slider, slider=slider, spin=spin)
            return wrap_image_gen_slider_row(slider, spin), None

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
            label = QLabel(f"{val:.1f}")

            def update_label(v: int, lbl=label, sc=scale):
                lbl.setText(f"{v / sc:.1f}")

            slider.valueChanged.connect(update_label)
            apply_field_control_tooltips(spec, slider, slider=slider)
            return wrap_image_gen_slider_row(slider, label), scale

        if spec.kind == "seed":
            spin = QSpinBox()
            spin.setMinimum(0)
            spin.setMaximum(2**31 - 1)
            spin.setValue(int(spec.default or 0))
            spin.setMaximumWidth(IMAGE_GEN_SEED_SPIN_MAX_WIDTH)
            spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        if self._canvas is not None:
            px, py, pw, ph = self._canvas.canvas_placement()
            out["placement_x"] = px
            out["placement_y"] = py
            out["placement_w"] = pw
            out["placement_h"] = ph
        out["source_image_path"] = self.source_path
        self._stash_aspect_lock_in_values(out)
        return out

    def _on_generate(self) -> None:
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
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
