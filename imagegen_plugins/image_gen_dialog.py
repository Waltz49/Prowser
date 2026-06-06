#!/usr/bin/env python3
"""Dynamic image-generation dialog built from pipeline field specs."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from exif_utils import (
    decode_usercomment,
    get_usercomment_from_path,
    truncate_usercomment_before_prompt,
)
from imagegen_plugins.image_gen_naming import parse_exif_generation_metadata
from imagegen_plugins.image_gen_active_model import save_active_plugin_id_for_function
from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_SEED_SPIN_MAX_WIDTH,
    ImageGenFieldsPanel,
    image_gen_field_label_stylesheet,
    image_gen_prompt_height_for_lines,
    mount_image_gen_fields_in_scroll,
    populate_image_gen_field_rows,
    wrap_image_gen_slider_row,
)
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
from imagegen_plugins.image_gen_pipeline_modes import (
    align_dims_for_pipeline,
    finalize_run_values,
    get_pipeline,
)
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.imagegen_control_tooltips import (
    apply_dialog_button_tooltips,
    apply_dim_helper_tooltips,
    apply_edit_import_all_button_tooltip,
    apply_edit_import_text_button_tooltip,
    apply_field_control_tooltips,
    apply_model_combo_tooltip,
)
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from lmstudio_caption import is_lmstudio_services_available
from theme_service import get_active_theme
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
    styled_message_box,
)

_EXIF_USERCOMMENT_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}
)


_COPIES_RANDOM_SEED_MESSAGE = (
    "Copies greater than 1 require Random seed to be enabled "
    "so each image uses a different seed."
)


def prompt_enable_random_seed_for_copies(parent) -> bool:
    """Ask to enable random seed when copies > 1. Returns True to continue."""
    msg_box = styled_message_box(
        parent,
        QMessageBox.Warning,
        "Random seed required",
        _COPIES_RANDOM_SEED_MESSAGE,
        buttons=QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
        default_button=QMessageBox.StandardButton.Yes,
        button_label_overrides={
            QMessageBox.StandardButton.Yes: "Continue with Random",
        },
    )
    msg_box.exec()
    return msg_box.result_data["button"] == QMessageBox.StandardButton.Yes


def _sync_random_seed_widget(parent, value: bool) -> None:
    widgets = getattr(parent, "_widgets", None)
    if not widgets:
        return
    entry = widgets.get("random_seed")
    if entry is None:
        return
    widget, _, spec = entry
    if spec.kind == "bool":
        widget.setChecked(bool(value))


def validate_copies_require_random_seed(parent, values: Dict[str, Any]) -> bool:
    """Return False when copies > 1, random seed is off, and user cancels."""
    copies = int(values.get("copies", 1) or 1)
    if copies <= 1 or values.get("random_seed") or values.get("series_refinement"):
        return True
    if not prompt_enable_random_seed_for_copies(parent):
        return False
    values["random_seed"] = True
    _sync_random_seed_widget(parent, True)
    return True


def import_option_held() -> bool:
    """Option (macOS) / Alt — prefer :func:`connect_import_button_with_option_modifier`."""
    mods = QApplication.keyboardModifiers()
    return bool(mods & Qt.KeyboardModifier.AltModifier)


def connect_import_button_with_option_modifier(
    import_btn: QPushButton,
    on_import,
) -> None:
    """Wire Import; pass ``option_held=True`` when Option/Alt was down at mouse press.

    ``QPushButton.clicked`` on macOS often runs after modifiers are cleared; read them
    from the press event instead (same pattern as option+click copy in EXIF editor).
    """
    def mouse_press(event):
        if event.button() == Qt.MouseButton.LeftButton:
            on_import(
                option_held=bool(
                    event.modifiers() & Qt.KeyboardModifier.AltModifier
                )
            )
            event.accept()
            return
        QPushButton.mousePressEvent(import_btn, event)

    import_btn.mousePressEvent = mouse_press


def apply_import_extras_from_image_path(dialog: Any, image_path: str) -> None:
    """Import seed/steps/quantization/LoRA/guidance from EXIF when present."""
    if not image_path:
        return
    raw_bytes = get_usercomment_from_path(image_path)
    if not raw_bytes:
        return
    full_text = decode_usercomment(raw_bytes)
    apply_exif_generation_params_to_dialog(
        dialog, parse_exif_generation_metadata(full_text)
    )


def apply_exif_generation_params_to_dialog(
    dialog: Any,
    params: Dict[str, Any],
) -> None:
    """Apply parsed EXIF generation fields; only updates keys present in the dialog."""
    if not params:
        return
    spec_keys = {s.key for s in dialog._specs}
    widgets = dialog._widgets

    def _clamp_int_slider(key: str, value: int) -> None:
        entry = widgets.get(key)
        if entry is None or key not in spec_keys:
            return
        widget, _, spec = entry
        if spec.kind != "int_slider":
            return
        lo = int(spec.min_value or 0)
        hi = int(spec.max_value or value)
        inner = widget.layout()
        spin = inner.itemAt(1).widget()
        spin.setValue(max(lo, min(hi, int(value))))

    def _set_float_slider(key: str, value: float) -> None:
        entry = widgets.get(key)
        if entry is None or key not in spec_keys:
            return
        widget, extra, spec = entry
        if spec.kind != "float_slider":
            return
        lo = float(spec.min_value or 0.0)
        hi = float(spec.max_value or value)
        scale = extra or 10
        clamped = max(lo, min(hi, float(value)))
        inner = widget.layout()
        slider = inner.itemAt(0).widget()
        slider.setValue(int(clamped * scale))

    def _set_choice(key: str, value: Any) -> None:
        entry = widgets.get(key)
        if entry is None or key not in spec_keys:
            return
        widget, _, spec = entry
        if spec.kind != "choice":
            return
        idx = widget.findData(value)
        if idx < 0:
            idx = widget.findText(str(value))
        if idx >= 0:
            widget.setCurrentIndex(idx)

    def _set_bool(key: str, value: bool) -> None:
        entry = widgets.get(key)
        if entry is None or key not in spec_keys:
            return
        widget, _, spec = entry
        if spec.kind == "bool":
            widget.setChecked(bool(value))

    if "seed" in params and "seed" in spec_keys:
        entry = widgets.get("seed")
        if entry is not None:
            widget, _, spec = entry
            if spec.kind == "seed":
                lo = int(spec.min_value or 0) if spec.min_value is not None else 0
                hi = (
                    int(spec.max_value or 2**31 - 1)
                    if spec.max_value is not None
                    else 2**31 - 1
                )
                widget.setValue(max(lo, min(hi, int(params["seed"]))))
                _set_bool("random_seed", False)

    if "steps" in params:
        _clamp_int_slider("steps", int(params["steps"]))

    if "quantization" in params:
        _set_choice("mflux_quantize", int(params["quantization"]))

    if "guidance" in params:
        _set_float_slider("guidance_scale", float(params["guidance"]))

    if "lora" in params and "mflux_lora" in spec_keys:
        entry = widgets.get("mflux_lora")
        if entry is not None:
            combo, _, spec = entry
            if spec.kind == "choice":
                from imagegen_plugins.flux_lora_catalog import get_lora_entry

                target = str(params["lora"]).strip().lower()
                if target and target != "none":
                    for i in range(combo.count()):
                        if combo.itemText(i).strip().lower() == target:
                            combo.setCurrentIndex(i)
                            break
                    else:
                        for i in range(combo.count()):
                            preset_id = combo.itemData(i)
                            entry_obj = get_lora_entry(str(preset_id))
                            if (
                                entry_obj is not None
                                and entry_obj.display_name.strip().lower() == target
                            ):
                                combo.setCurrentIndex(i)
                                break
                            if str(preset_id).strip().lower() == target:
                                combo.setCurrentIndex(i)
                                break
                        else:
                            base_target = os.path.basename(target)
                            for i in range(combo.count()):
                                if combo.itemText(i).strip().lower() == base_target:
                                    combo.setCurrentIndex(i)
                                    break


def _image_pixel_size(image_path: str) -> Optional[tuple[int, int]]:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as img:
            return int(img.size[0]), int(img.size[1])
    except Exception:
        return None


def load_import_prompt_from_path(
    parent: QWidget,
    image_path: str,
    *,
    warning_title: str = "Import",
) -> Optional[str]:
    """EXIF user comment prompt for Import; warns and returns None if no user comment."""
    raw_bytes = get_usercomment_from_path(image_path)
    if raw_bytes is None:
        show_styled_warning(
            parent,
            warning_title,
            "No EXIF user comment was found for this image.",
        )
        return None

    text = decode_usercomment(raw_bytes)
    return truncate_usercomment_before_prompt(text).strip()


IMAGE_GEN_SIDE_BUTTON_WIDTH = 112


def _text_input_stylesheet() -> str:
    """Bordered arbitrary-text fields (prompt, negative prompt, etc.) in the image-gen dialog."""
    t = get_active_theme()
    return f"""
    #imageGenDialog QPlainTextEdit,
    #imageGenDialog QLineEdit {{
        background-color: {t.button_bg_default_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        font-size: 13px;
    }}
    #imageGenDialog QPlainTextEdit:focus,
    #imageGenDialog QLineEdit:focus {{
        border: 1px solid {t.current_image_border_color_hex};
        outline: none;
    }}
    #imageGenDialog QPlainTextEdit:hover,
    #imageGenDialog QLineEdit:hover {{
        border: 1px solid {t.button_border_hover_hex};
    }}
    #imageGenDialog QComboBox#imageGenModelCombo {{
        background-color: {t.button_bg_default_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        max-width: 4096px;
    }}
    #imageGenDialog QComboBox {{
        background-color: {t.button_bg_default_hex};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 24px;
    }}
    #imageGenDialog QComboBox:hover {{
        border: 1px solid {t.button_border_hover_hex};
    }}
    #imageGenDialog QComboBox:focus {{
        border: 1px solid {t.current_image_border_color_hex};
    }}
    #imageGenDialog QPushButton#imageGenCompactDimBtn {{
        padding-left: 0px;
        padding-right: 0px;
        min-width: 0px;
    }}
    #imageGenDialog QPushButton#imageGenSideActionBtn {{
        padding: 5px 6px;
        font-size: 12px;
        min-height: 24px;
        min-width: 0px;
        max-width: {IMAGE_GEN_SIDE_BUTTON_WIDTH}px;
    }}
    """ + image_gen_field_label_stylesheet()


DEFAULT_IMAGE_GEN_DIALOG_TITLE = "Image Generation"
EXPAND_IMAGE_DIALOG_TITLE = "Expand Image"
IMAGE_GEN_FORM_ROW_SPACING = 4
IMAGE_GEN_SIDE_BUTTON_SPACING = 6


def clear_image_gen_side_button_layout(col: QVBoxLayout) -> None:
    while col.count():
        item = col.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def configure_image_gen_side_button(button: QPushButton) -> None:
    """Narrow vertical-column action buttons beside the fields panel."""
    button.setObjectName("imageGenSideActionBtn")
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button.setFixedWidth(IMAGE_GEN_SIDE_BUTTON_WIDTH)


def create_image_gen_side_button_column(
    parent: QWidget,
) -> tuple[QWidget, QVBoxLayout]:
    host = QWidget(parent)
    host.setObjectName("imageGenSideButtonColumn")
    host.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
    )
    host.setFixedWidth(IMAGE_GEN_SIDE_BUTTON_WIDTH)
    col = QVBoxLayout(host)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(IMAGE_GEN_SIDE_BUTTON_SPACING)
    col.setAlignment(Qt.AlignmentFlag.AlignTop)
    return host, col


def repopulate_image_gen_side_buttons(
    owner: Any,
    buttons: Optional[List[QPushButton]],
) -> None:
    """Fill side buttons in the row below the prompt (right of sliders/checkboxes)."""
    host = getattr(owner, "_side_btn_host", None)
    col = getattr(owner, "_side_btn_col", None)
    panel = getattr(owner, "_fields_panel", None)
    if host is None or col is None:
        if not buttons:
            if panel is not None:
                panel.attach_side_button_column(None)
            return
        col = prepare_image_gen_side_button_column(owner, needed=True)
        host = getattr(owner, "_side_btn_host", None)
        if col is None or host is None:
            return
    clear_image_gen_side_button_layout(col)
    if not buttons:
        host.hide()
        if panel is not None:
            panel.attach_side_button_column(None)
        return
    for button in buttons:
        configure_image_gen_side_button(button)
        col.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    finalize_image_gen_side_button_column(col)
    if panel is not None:
        panel.attach_side_button_column(host)


def finalize_image_gen_side_button_column(col: QVBoxLayout) -> None:
    col.addStretch(1)


def reset_image_gen_side_button_column_owner(owner: Any) -> None:
    col = getattr(owner, "_side_btn_col", None)
    if col is not None:
        clear_image_gen_side_button_layout(col)
    if hasattr(owner, "_aspect_checkbox"):
        owner._aspect_checkbox = None
    if hasattr(owner, "_flux_prompt_ai"):
        owner._flux_prompt_ai = None


def prepare_image_gen_side_button_column(
    owner: Any,
    *,
    needed: bool,
) -> Optional[QVBoxLayout]:
    if not needed:
        host = getattr(owner, "_side_btn_host", None)
        if host is not None:
            host.hide()
        return None
    if getattr(owner, "_side_btn_host", None) is None:
        owner._side_btn_host, owner._side_btn_col = create_image_gen_side_button_column(
            owner
        )
    else:
        reset_image_gen_side_button_column_owner(owner)
        owner._side_btn_host.show()
    return owner._side_btn_col


def wrap_image_gen_controls_with_side_buttons(
    scroll: QScrollArea,
    side_btn_host: Optional[QWidget],
) -> QWidget:
    """Side buttons live inside the fields panel below the prompt; return scroll only."""
    del side_btn_host
    scroll.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    return scroll


def _snap_nearest_multiple(value: int, step: int = 8) -> int:
    step = max(1, int(step))
    return int(round(value / step)) * step


def pair_dims_with_aspect_lock(
    changed: str,
    value: int,
    ratio: float,
    *,
    w_bounds: tuple[int, int],
    h_bounds: tuple[int, int],
    step: int,
) -> tuple[int, int]:
    """Width/height pair that keeps aspect ratio and stays within per-axis bounds."""
    w_lo, w_hi = w_bounds
    h_lo, h_hi = h_bounds
    step = max(1, int(step))
    if ratio <= 0:
        ratio = 1.0

    if changed == "width":
        w, h = float(value), float(value) / ratio
    else:
        h, w = float(value), float(value) * ratio

    if w > w_hi:
        scale = w_hi / w
        w *= scale
        h *= scale
    if h > h_hi:
        scale = h_hi / h
        w *= scale
        h *= scale
    if w < w_lo:
        scale = w_lo / w
        w *= scale
        h *= scale
    if h < h_lo:
        scale = h_lo / h
        w *= scale
        h *= scale

    w = max(w_lo, min(w_hi, int(round(w))))
    h = max(h_lo, min(h_hi, int(round(h))))
    w = _snap_nearest_multiple(w, step)
    h = _snap_nearest_multiple(h, step)
    w = max(w_lo, min(w_hi, w))
    h = max(h_lo, min(h_hi, h))

    if changed == "width":
        h = max(h_lo, min(h_hi, _snap_nearest_multiple(int(round(w / ratio)), step)))
        if h > 0:
            w = max(w_lo, min(w_hi, _snap_nearest_multiple(int(round(h * ratio)), step)))
    else:
        w = max(w_lo, min(w_hi, _snap_nearest_multiple(int(round(h * ratio)), step)))
        if w > 0:
            h = max(h_lo, min(h_hi, _snap_nearest_multiple(int(round(w / ratio)), step)))

    return w, h


class ImageGenDimensionAspectMixin:
    """Width/height helpers + optional aspect-ratio lock for image-gen dialogs."""

    _aspect_checkbox: Optional[QCheckBox]
    _aspect_lock_updating: bool
    _aspect_ratio: float

    def _init_dim_aspect_state(self) -> None:
        self._aspect_checkbox = None
        self._aspect_lock_updating = False
        self._aspect_ratio = 1.0

    def _has_dim_fields(self) -> bool:
        keys = {s.key for s in self._specs}
        return "width" in keys and "height" in keys

    def _dim_align_step(self) -> int:
        for spec in self._specs:
            if spec.key == "width" and spec.kind == "int_slider":
                return max(1, int(spec.step or 8))
        return 8

    def _int_slider_bounds(self, key: str) -> tuple[int, int]:
        for spec in self._specs:
            if spec.key == key and spec.kind == "int_slider":
                return int(spec.min_value or 0), int(spec.max_value or 10000)
        return 256, 1440

    def _get_int_slider(self, key: str) -> Optional[int]:
        entry = self._widgets.get(key)
        if entry is None:
            return None
        widget, _, spec = entry
        if spec.kind != "int_slider":
            return None
        inner = widget.layout()
        spin = inner.itemAt(1).widget()
        return int(spin.value())

    def _set_int_slider(self, key: str, value: int) -> None:
        entry = self._widgets.get(key)
        if entry is None:
            return
        widget, _, spec = entry
        if spec.kind != "int_slider":
            return
        inner = widget.layout()
        slider = inner.itemAt(0).widget()
        spin = inner.itemAt(1).widget()
        spin.setValue(int(value))
        slider.setValue(int(value))

    def _aspect_lock_enabled(self) -> bool:
        return (
            self._aspect_checkbox is not None
            and self._aspect_checkbox.isChecked()
        )

    def _refresh_aspect_ratio_from_sliders(self) -> None:
        width = self._get_int_slider("width")
        height = self._get_int_slider("height")
        if width is None or height is None or height <= 0:
            return
        self._aspect_ratio = width / height

    def _paired_dims_for_aspect(self, changed_key: str, value: int) -> tuple[int, int]:
        step = self._dim_align_step()
        return pair_dims_with_aspect_lock(
            changed_key,
            value,
            self._aspect_ratio,
            w_bounds=self._int_slider_bounds("width"),
            h_bounds=self._int_slider_bounds("height"),
            step=step,
        )

    def _apply_aspect_locked_dims(self, changed_key: str, value: int) -> None:
        if not self._aspect_lock_enabled():
            return
        w, h = self._paired_dims_for_aspect(changed_key, value)
        self._aspect_lock_updating = True
        try:
            self._set_int_slider("width", w)
            self._set_int_slider("height", h)
        finally:
            self._aspect_lock_updating = False

    def _on_dim_value_changed(self, changed_key: str, value: int) -> None:
        if self._aspect_lock_updating or not self._aspect_lock_enabled():
            return
        self._apply_aspect_locked_dims(changed_key, value)

    def _on_aspect_lock_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_aspect_ratio_from_sliders()

    def _restore_aspect_lock_from_values(self) -> None:
        if self._aspect_checkbox is None:
            return
        locked = bool(self._values.get("aspect_ratio_lock", False))
        self._aspect_lock_updating = True
        try:
            self._aspect_checkbox.setChecked(locked)
            if locked:
                w = self._values.get("width")
                h = self._values.get("height")
                if (
                    isinstance(w, (int, float))
                    and isinstance(h, (int, float))
                    and float(h) > 0
                ):
                    self._aspect_ratio = float(w) / float(h)
                self._refresh_aspect_ratio_from_sliders()
        finally:
            self._aspect_lock_updating = False

    def _stash_aspect_lock_in_values(self, out: Dict[str, Any]) -> None:
        if self._aspect_checkbox is not None:
            out["aspect_ratio_lock"] = self._aspect_checkbox.isChecked()

    def _apply_import_dims_from_image(self, image_path: str) -> None:
        """Set width/height from image pixels; lock aspect if scaled to model max."""
        if not self._has_dim_fields():
            return
        size = _image_pixel_size(image_path)
        if size is None:
            show_styled_warning(
                self,
                "Import",
                "Could not read image dimensions.",
            )
            return
        src_w, src_h = size
        if src_w <= 0 or src_h <= 0:
            show_styled_warning(
                self,
                "Import",
                "Could not read image dimensions.",
            )
            return
        w, h = align_dims_for_pipeline(self.plugin.pipeline_id, src_w, src_h)
        scaled_down = w < src_w or h < src_h
        self._aspect_lock_updating = True
        try:
            self._set_int_slider("width", w)
            self._set_int_slider("height", h)
            if scaled_down and self._aspect_checkbox is not None:
                self._aspect_checkbox.setChecked(True)
                self._aspect_ratio = src_w / src_h
            elif self._aspect_lock_enabled():
                self._refresh_aspect_ratio_from_sliders()
        finally:
            self._aspect_lock_updating = False

    def _add_dim_helper_buttons(self, btn_col: QVBoxLayout) -> None:
        screen_btn = QPushButton("Screen size")
        screen_btn.clicked.connect(self._on_screen_size_dims)
        btn_col.addWidget(screen_btn, 0, Qt.AlignmentFlag.AlignTop)
        square_reverse_row = QWidget()
        square_reverse_row.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        square_reverse_layout = QHBoxLayout(square_reverse_row)
        square_reverse_layout.setContentsMargins(0, 0, 0, 0)
        square_reverse_layout.setSpacing(4)
        square_btn = QPushButton("Square")
        square_btn.setObjectName("imageGenCompactDimBtn")
        square_btn.clicked.connect(self._on_square_dims)
        square_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        square_reverse_layout.addWidget(square_btn)
        reverse_btn = QPushButton("Reverse")
        reverse_btn.setObjectName("imageGenCompactDimBtn")
        reverse_btn.clicked.connect(self._on_reverse_dims)
        reverse_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        square_reverse_layout.addWidget(reverse_btn)
        ref_w = screen_btn.sizeHint().width()
        spacing = square_reverse_layout.spacing()
        half_w = max(1, (ref_w - spacing) // 2)
        square_btn.setFixedWidth(half_w)
        reverse_btn.setFixedWidth(half_w)
        square_reverse_row.setFixedWidth(ref_w)
        btn_col.addWidget(square_reverse_row, 0, Qt.AlignmentFlag.AlignTop)
        self._aspect_checkbox = QCheckBox("Aspect Ratio Lock")
        self._aspect_checkbox.toggled.connect(self._on_aspect_lock_toggled)
        btn_col.addWidget(self._aspect_checkbox, 0, Qt.AlignmentFlag.AlignTop)
        apply_dim_helper_tooltips(
            screen_btn=screen_btn,
            square_btn=square_btn,
            reverse_btn=reverse_btn,
            aspect_checkbox=self._aspect_checkbox,
        )

    def _connect_dim_aspect_lock(self) -> None:
        if not self._has_dim_fields():
            return
        for key in ("width", "height"):
            entry = self._widgets.get(key)
            if entry is None:
                continue
            widget, _, spec = entry
            if spec.kind != "int_slider":
                continue
            inner = widget.layout()
            spin = inner.itemAt(1).widget()
            spin.valueChanged.connect(
                lambda value, k=key: self._on_dim_value_changed(k, int(value))
            )
        self._restore_aspect_lock_from_values()

    def _on_screen_size_dims(self) -> None:
        sw, sh = self._screen_pixel_size()
        w, h = align_dims_for_pipeline(self.plugin.pipeline_id, sw, sh)
        self._set_int_slider("width", w)
        self._set_int_slider("height", h)
        if self._aspect_lock_enabled():
            self._refresh_aspect_ratio_from_sliders()

    def _on_square_dims(self) -> None:
        width = self._get_int_slider("width")
        if width is None:
            return
        w_lo, w_hi = self._int_slider_bounds("width")
        h_lo, h_hi = self._int_slider_bounds("height")
        lo = max(w_lo, h_lo)
        hi = min(w_hi, h_hi)
        step = self._dim_align_step()
        side = _snap_nearest_multiple(width, step)
        side = max(lo, min(hi, side))
        self._set_int_slider("width", side)
        self._set_int_slider("height", side)
        if self._aspect_lock_enabled():
            self._aspect_ratio = 1.0

    def _on_reverse_dims(self) -> None:
        width = self._get_int_slider("width")
        height = self._get_int_slider("height")
        if width is None or height is None:
            return
        self._set_int_slider("width", height)
        self._set_int_slider("height", width)
        if self._aspect_lock_enabled() and height > 0:
            self._aspect_ratio = height / width


def apply_image_gen_preview_splitter_theme(splitter: QSplitter) -> None:
    """Visible draggable handle for preview | controls splitters."""
    t = get_active_theme()
    w = max(8, int(getattr(t, "view_border_width_px", 4) or 4) + 4)
    splitter.setHandleWidth(w)
    splitter.setStyleSheet(
        f"""
        QSplitter::handle {{
            background-color: {t.splitter_handle_hex};
        }}
        QSplitter::handle:hover {{
            background-color: {t.splitter_handle_hover_hex};
        }}
        QSplitter::handle:pressed {{
            background-color: {t.splitter_handle_pressed_hex};
        }}
        QSplitter::handle:horizontal {{
            width: {w}px;
            margin: 4px 0;
        }}
        """
    )


class ImageGenPreviewSplitter(QSplitter):
    """Horizontal splitter: preview left (capped), controls right; live resize on drag."""

    def __init__(
        self,
        parent=None,
        *,
        max_left_ratio: float = 0.7,
        initial_left_ratio: float = 0.5,
    ):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._max_left_ratio = max_left_ratio
        self._initial_left_ratio = initial_left_ratio
        self._initial_sizes_applied = False
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        apply_image_gen_preview_splitter_theme(self)
        self.splitterMoved.connect(self._clamp_left_size)

    def add_preview_pane(self, widget: QWidget) -> None:
        widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.addWidget(widget)

    def add_controls_pane(self, widget: QWidget, *, min_width: int = 300) -> None:
        widget.setMinimumWidth(min_width)
        widget.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding
        )
        self.addWidget(widget)
        if self.count() >= 2:
            self.setStretchFactor(0, 0)
            self.setStretchFactor(1, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_sizes_applied:
            self._initial_sizes_applied = True
            QTimer.singleShot(0, self._apply_initial_sizes)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._clamp_left_size()

    def _apply_initial_sizes(self) -> None:
        total = self.width()
        if total <= 0:
            return
        left = min(
            int(total * self._initial_left_ratio),
            int(total * self._max_left_ratio),
        )
        self.setSizes([left, max(1, total - left)])
        self._clamp_left_size()

    def _clamp_left_size(self, *_args) -> None:
        sizes = self.sizes()
        if len(sizes) < 2:
            return
        total = sum(sizes)
        if total <= 0:
            total = self.width()
        if total <= 0:
            return
        max_left = max(1, int(total * self._max_left_ratio))
        left = sizes[0]
        if left <= max_left:
            return
        self.blockSignals(True)
        self.setSizes([max_left, max(1, total - max_left)])
        self.blockSignals(False)


def configure_image_gen_form_layout(form: QFormLayout) -> None:
    """Legacy no-op; fields use :class:`ImageGenFieldsPanel` instead."""
    form.setVerticalSpacing(IMAGE_GEN_FORM_ROW_SPACING)
    form.setFormAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    )
    form.setLabelAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    )


def field_specs_share_seed_row(spec_keys: set) -> bool:
    """True when both seed and random_seed specs exist (one combined form row)."""
    return "seed" in spec_keys and "random_seed" in spec_keys


def build_seed_and_random_seed_row(seed_widget: QWidget, random_widget: QWidget) -> QWidget:
    """Horizontal row: seed spinbox, then Randomize checkbox (no clipping)."""
    from PySide6.QtWidgets import QCheckBox, QSpinBox

    if isinstance(seed_widget, QSpinBox):
        seed_widget.setMaximumWidth(IMAGE_GEN_SEED_SPIN_MAX_WIDTH)
        seed_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
    if isinstance(random_widget, QCheckBox):
        random_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        random_widget.setMinimumWidth(random_widget.sizeHint().width())

    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    row.addWidget(
        seed_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    row.addWidget(
        random_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    row_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return row_w


def apply_image_gen_dialog_shell(
    dlg: QDialog,
    *,
    window_title: str,
    min_width: int,
    min_height: int,
) -> None:
    """Shared window chrome for image-gen and expand dialogs."""
    dlg.setWindowTitle(window_title)
    dlg.setObjectName("imageGenDialog")
    dlg.setMinimumSize(min_width, min_height)
    dlg.setWindowFlags(
        Qt.Window
        | Qt.WindowTitleHint
        | Qt.WindowSystemMenuHint
        | Qt.WindowCloseButtonHint
        | Qt.WindowStaysOnTopHint
    )
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setStyleSheet(dlg.styleSheet() + _text_input_stylesheet())


class ImageGenDialog(ImageGenDimensionAspectMixin, QDialog):
    """Prompt + dynamically built configuration fields; model chosen via dropdown."""

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        function: str,
        parent=None,
        *,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
        window_title: str = DEFAULT_IMAGE_GEN_DIALOG_TITLE,
    ):
        super().__init__(parent)
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        self._widgets: Dict[str, Any] = {}
        self._specs: List[FieldSpec] = []
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
            self, window_title=window_title, min_width=520, min_height=480
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
        self._save_geometry()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

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
        layout.addWidget(controls, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        apply_dialog_button_tooltips(buttons)
        buttons.accepted.connect(self._on_generate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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

        self._connect_lora_steps_floor()
        self._connect_dim_aspect_lock()

    def _repopulate_side_buttons(self) -> None:
        if not self._needs_prompt_side_column():
            repopulate_image_gen_side_buttons(self, None)
            return
        repopulate_image_gen_side_buttons(self, self._build_prompt_action_buttons())

    def _on_model_combo_changed(self, _index: int = 0) -> None:
        plugin_id = self._model_combo.currentData()
        new_plugin = self._plugins_by_id.get(plugin_id)
        if (
            new_plugin is None
            or new_plugin.plugin_id == self.plugin.plugin_id
            or not new_plugin.is_available()
        ):
            return
        from imagegen_plugins.image_gen_model_selector import (
            refresh_dialog_mflux_lora_combo,
            values_after_plugin_switch,
        )

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

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

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
        self._apply_lora_steps_floor()

    def _connect_lora_steps_floor(self) -> None:
        """When LoRA requires more steps, raise the steps slider minimum and value."""
        if self.plugin.pipeline_id != "flux_schnell_mflux_play":
            return
        lora_entry = self._widgets.get("mflux_lora")
        if lora_entry is None:
            return
        lora_widget, _, lora_spec = lora_entry
        if lora_spec.kind != "choice":
            return

        def _on_lora_changed(_index: int = 0) -> None:
            self._apply_lora_steps_floor()

        lora_widget.currentIndexChanged.connect(_on_lora_changed)
        self._apply_lora_steps_floor()

    def _apply_lora_steps_floor(self) -> None:
        if self.plugin.pipeline_id != "flux_schnell_mflux_play":
            return
        lora_entry = self._widgets.get("mflux_lora")
        steps_entry = self._widgets.get("steps")
        if lora_entry is None or steps_entry is None:
            return
        lora_widget, _, lora_spec = lora_entry
        steps_widget, _, steps_spec = steps_entry
        if lora_spec.kind != "choice" or steps_spec.kind != "int_slider":
            return

        from imagegen_plugins.mflux_lora_presets import (
            coerce_lora_preset_id,
            lora_preset_min_steps,
        )

        mode = get_pipeline(self.plugin.pipeline_id)
        lora_id = coerce_lora_preset_id(lora_widget.currentData())
        lora_min = lora_preset_min_steps(lora_id)
        steps_min = mode.steps_min if lora_min is None else max(mode.steps_min, lora_min)

        inner = steps_widget.layout()
        slider = inner.itemAt(0).widget()
        spin = inner.itemAt(1).widget()
        slider.setMinimum(steps_min)
        spin.setMinimum(steps_min)
        if spin.value() < steps_min:
            spin.setValue(steps_min)

    def _main_window(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "current_view_mode"):
            return parent
        return None

    def _needs_prompt_side_column(self) -> bool:
        return (
            self._show_import_button()
            or self._has_dim_fields()
            or is_lmstudio_services_available()
        )

    def _build_prompt_action_buttons(self) -> Optional[List[QPushButton]]:
        if not self._needs_prompt_side_column():
            return None
        buttons: List[QPushButton] = []
        if self._show_import_button():
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
        ai = self._ensure_flux_prompt_ai()
        buttons.extend(ai.make_action_buttons())
        return buttons or None

    def _populate_prompt_side_buttons(self, btn_col: QVBoxLayout) -> None:
        """Legacy side column hook; prompt actions are inline under the prompt field."""
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

    def _active_image_path_for_import(self) -> Optional[str]:
        """Same image resolution as copy/edit EXIF user comment (browse or single thumbnail)."""
        mw = self._main_window()
        if mw is None:
            return None
        image_path = None
        if mw.current_view_mode == "browse":
            if hasattr(mw, "get_current_image_path"):
                image_path = mw.get_current_image_path()
        elif mw.current_view_mode == "thumbnail":
            if hasattr(mw, "selection_manager") and mw.selection_manager:
                selected_files = mw.selection_manager.get_selected_files()
                if selected_files and len(selected_files) == 1:
                    image_path = selected_files[0]
        if not image_path or not os.path.isfile(image_path):
            return None
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in _EXIF_USERCOMMENT_EXTENSIONS:
            return None
        return image_path

    def _import_prompt_text_from_active_image(self) -> bool:
        """Load prompt text from EXIF; return True on success."""
        image_path = self._active_image_path_for_import()
        if not image_path:
            show_styled_warning(self, "Import Text", "No image selected.")
            return False
        prompt_text = load_import_prompt_from_path(self, image_path)
        if prompt_text is None:
            return False
        self.set_prompt_text(prompt_text)
        return True

    def _on_import_prompt_text(self) -> None:
        self._import_prompt_text_from_active_image()

    def _on_import_available(self) -> None:
        if not self._import_prompt_text_from_active_image():
            return
        image_path = self._active_image_path_for_import()
        if not image_path:
            return
        if self._has_dim_fields():
            self._apply_import_dims_from_image(image_path)
        apply_import_extras_from_image_path(self, image_path)

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
            if spec.key == "prompt":
                edit.setMinimumHeight(
                    image_gen_prompt_height_for_lines(4, edit.fontMetrics())
                )
            else:
                edit.setMinimumHeight(72)
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
        self._stash_aspect_lock_in_values(out)
        return out

    def _on_generate(self) -> None:
        values = finalize_run_values(
            self.plugin.pipeline_id, self.collect_values()
        )
        prompt_spec = next((s for s in self._specs if s.key == "prompt"), None)
        if prompt_spec is not None and prompt_spec.required:
            prompt = (values.get("prompt") or "").strip()
            if not prompt:
                label = prompt_spec.label or "Prompt"
                show_styled_warning(
                    self,
                    f"{label} required",
                    f"Enter {label.lower()} before generating an image.",
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
