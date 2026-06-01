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
    apply_field_control_tooltips,
    apply_import_button_tooltip,
    apply_model_combo_tooltip,
)
from theme_service import get_active_theme
from utils import (
    _center_styled_dialog_on_screen,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_warning,
)

_EXIF_USERCOMMENT_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}
)


def validate_copies_require_random_seed(parent, values: Dict[str, Any]) -> bool:
    """Return False when copies > 1 but random seed is off."""
    copies = int(values.get("copies", 1) or 1)
    if copies > 1 and not values.get("random_seed"):
        show_styled_warning(
            parent,
            "Random seed required",
            "Copies greater than 1 require Random seed to be enabled "
            "so each image uses a different seed.",
        )
        return False
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


def load_import_prompt_from_path(parent: QWidget, image_path: str) -> Optional[str]:
    """EXIF user comment prompt for Import; warns and returns None on failure."""
    raw_bytes = get_usercomment_from_path(image_path)
    if raw_bytes is None:
        show_styled_warning(
            parent,
            "Import",
            "No EXIF user comment was found for this image.",
        )
        return None

    text = decode_usercomment(raw_bytes)
    prompt_text = truncate_usercomment_before_prompt(text).strip()
    if not prompt_text:
        show_styled_warning(
            parent,
            "Import",
            "The EXIF user comment is empty.",
        )
        return None
    return prompt_text


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
        padding: 6px;
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
        padding: 4px 8px;
        min-height: 24px;
        min-width: 300px;
        max-width: 480px;
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
    """


DEFAULT_IMAGE_GEN_DIALOG_TITLE = "Image Generation"
EXPAND_IMAGE_DIALOG_TITLE = "Expand Image"
IMAGE_GEN_FORM_ROW_SPACING = 4


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

    @staticmethod
    def _import_option_held() -> bool:
        return import_option_held()

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
    """Shared vertical spacing and left-aligned labels between dynamic field rows."""
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
    """Horizontal row: seed spinbox, gap, then Randomize label + checkbox."""
    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    row.addWidget(seed_widget, 0)
    row.addSpacing(28)

    random_group = QWidget()
    random_row = QHBoxLayout(random_group)
    random_row.setContentsMargins(12, 0, 0, 0)
    random_row.setSpacing(8)
    random_label = QLabel("Randomize")
    random_row.addWidget(random_label, 0)
    random_row.addWidget(random_widget, 0)
    row.addWidget(random_group, 0)
    row.addStretch(1)
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
        self._fields_form: Optional[QFormLayout] = None
        self._init_dim_aspect_state()

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
        layout.addWidget(scroll)

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

            if spec.kind == "text":
                if spec.key == "prompt" and (
                    self._show_import_button() or self._has_dim_fields()
                ):
                    row_w = QWidget()
                    row = QHBoxLayout(row_w)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(widget, 1)
                    btn_col = QVBoxLayout()
                    btn_col.setContentsMargins(0, 0, 0, 0)
                    btn_col.setSpacing(4)
                    if self._show_import_button():
                        import_btn = QPushButton("Import")
                        connect_import_button_with_option_modifier(
                            import_btn, self._on_import_prompt
                        )
                        apply_import_button_tooltip(import_btn)
                        btn_col.addWidget(import_btn, 0, Qt.AlignmentFlag.AlignTop)
                    if self._has_dim_fields():
                        self._add_dim_helper_buttons(btn_col)
                    btn_host = QWidget()
                    btn_host.setLayout(btn_col)
                    row.addWidget(btn_host, 0, Qt.AlignmentFlag.AlignTop)
                    self._fields_form.addRow(spec.label, row_w)
                else:
                    self._fields_form.addRow(spec.label, widget)
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
            else:
                self._fields_form.addRow(spec.label, widget)

        self._connect_lora_steps_floor()
        self._connect_dim_aspect_lock()

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

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA pulldown after Settings → LoRA catalog changes."""
        entry = self._widgets.get("mflux_lora")
        if entry is None:
            return
        lora_widget, _, lora_spec = entry
        if lora_spec.kind != "choice":
            return
        from imagegen_plugins.mflux_lora_presets import repopulate_mflux_lora_combo

        repopulate_mflux_lora_combo(
            lora_widget,
            pipeline_id=self.plugin.pipeline_id,
            plugin_hf_model_id=self.plugin.hf_model_id,
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

    def _on_import_prompt(self, *, option_held: bool = False) -> None:
        image_path = self._active_image_path_for_import()
        if not image_path:
            show_styled_warning(self, "Import", "No image selected.")
            return

        prompt_text = load_import_prompt_from_path(self, image_path)
        if prompt_text is None:
            return

        self.set_prompt_text(prompt_text)
        if option_held:
            if self._has_dim_fields():
                self._apply_import_dims_from_image(image_path)
            apply_import_extras_from_image_path(self, image_path)

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
            edit.setMinimumHeight(120 if spec.key == "prompt" else 72)
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
            label = QLabel(f"{val:.1f}")

            def update_label(v: int, lbl=label, sc=scale):
                lbl.setText(f"{v / sc:.1f}")

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
