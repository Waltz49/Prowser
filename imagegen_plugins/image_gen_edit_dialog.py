#!/usr/bin/env python3
"""Edit dialog: source image preview + edit prompt and model controls."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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
from imagegen_plugins.image_gen_expand_dialog import active_image_path_for_expand
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

# Re-use expand's active-image resolution (browse or single thumbnail).
active_image_path_for_edit = active_image_path_for_expand


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


class ImageGenEditDialog(QDialog):
    """Source preview + dynamically built edit configuration fields."""

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        function: str,
        source_path: str,
        parent=None,
        *,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        window_title: str = EDIT_IMAGE_DIALOG_TITLE,
    ):
        super().__init__(parent)
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        self.source_path = os.path.abspath(source_path)
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
        self._load_plugin_state()

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

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        splitter = ImageGenPreviewSplitter(self)

        preview_host = QFrame()
        preview_host.setFrameShape(QFrame.Shape.NoFrame)
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._source_preview = _SourceImagePreview(self.source_path, preview_host)
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
