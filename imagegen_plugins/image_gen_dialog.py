#!/usr/bin/env python3
"""Dynamic image-generation dialog built from pipeline field specs."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPalette
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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from thumbnails.thumbnail_constants import CMD_SYMBOL, ENTER_SYMBOL
from exif.exif_utils import (
    decode_usercomment,
    get_usercomment_from_path,
    truncate_usercomment_before_prompt,
)
from imagegen_plugins.image_gen_naming import parse_exif_generation_metadata
from imagegen_plugins.image_gen_active_model import FUNCTION_CREATE
from imagegen_plugins.image_gen_edit_custom_size import mount_custom_size_section
from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_form_layout import (
    ImageGenFieldsPanel,
    IMAGE_GEN_FIELD_BORDER_PAD,
    IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT,
    image_gen_field_label_stylesheet,
    mount_image_gen_fields_in_scroll,
)
from imagegen_plugins.image_gen_parameter_panel import (
    ImageGenParameterPanel,
    choice_field_widget,
    default_widget_build_options,
)
from imagegen_plugins.image_gen_model_selector import (
    apply_mflux_lora_collection_guard,
    build_model_selector_row,
    mount_image_gen_lora_field,
    resolve_initial_plugin,
    switch_plugin_persisted_settings_preserving_prompt,
    sync_image_gen_generate_enabled,
    sync_image_gen_lora_field,
    sync_model_comment_label,
)
from imagegen_plugins.image_gen_persistence import (
    load_imagegen_dialog_geometry_hex,
    load_pass_image_to_ai_with_prompt,
    load_plugin_dialog_settings,
    save_imagegen_dialog_geometry_hex,
    save_pass_image_to_ai_with_prompt,
    save_plugin_dialog_settings,
)
from imagegen_plugins.image_gen_pipeline_modes import (
    align_dims_for_pipeline,
    finalize_run_values,
    get_pipeline,
)
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.imagegen_control_tooltips import (
    apply_dialog_button_tooltips,
    apply_edit_import_all_button_tooltip,
    apply_edit_import_text_button_tooltip,
    apply_field_control_tooltips,
    apply_model_combo_tooltip,
)
from imagegen_plugins.image_gen_function_switcher import (
    create_image_gen_action_buttons,
    create_image_gen_dialog_footer,
    install_image_gen_escape_to_close,
    install_image_gen_footer_keyboard_shortcuts,
    refresh_image_gen_footer_keyboard_shortcuts,
)
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from imagegen_plugins.flux_prompt_system_mount import (
    flux_prompt_system_override_for,
    schedule_deferred_flux_prompt_extras,
)
from imagegen_plugins.lmstudio_caption import is_lmstudio_sdk_installed
from theme.theme_service import apply_view_chrome_splitter_theme, get_active_theme
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
            QMessageBox.StandardButton.Yes: "Generate with Random",
        },
    )
    msg_box.exec()
    return msg_box.result_data["button"] == QMessageBox.StandardButton.Yes


def _widget_host_for_random_seed_sync(parent) -> Any:
    """Resolve the panel that owns the random_seed field widgets."""
    candidates: list[Any] = []
    if parent is not None:
        candidates.append(parent)
        settings = getattr(parent, "_settings", None)
        if settings is not None:
            candidates.append(settings)
    main_window = parent
    if not hasattr(main_window, "_imagegen_function_dialog"):
        main_window = getattr(parent, "_main_window", None)
    if main_window is not None:
        dlg = getattr(main_window, "_imagegen_function_dialog", None)
        if dlg is not None:
            panel = getattr(dlg, "_current_panel", None)
            if panel is not None:
                candidates.append(panel)
                panel_settings = getattr(panel, "_settings", None)
                if panel_settings is not None:
                    candidates.append(panel_settings)
    for obj in candidates:
        widgets = getattr(obj, "_widgets", None)
        if widgets and widgets.get("random_seed") is not None:
            return obj
    return parent


def sync_random_seed_setting(parent, value: bool) -> None:
    """Update random_seed in dialog values and the Randomize checkbox."""
    host = _widget_host_for_random_seed_sync(parent)
    widgets = getattr(host, "_widgets", None)
    if not widgets:
        return
    entry = widgets.get("random_seed")
    if entry is None:
        return
    widget, _, spec = entry
    if spec.kind == "bool":
        widget.setChecked(bool(value))
    stored = getattr(host, "_values", None)
    if isinstance(stored, dict):
        stored["random_seed"] = bool(value)


def validate_copies_require_random_seed(parent, values: Dict[str, Any]) -> bool:
    """Return False when copies > 1, random seed is off, and user cancels."""
    copies = int(values.get("copies", 1) or 1)
    if copies <= 1 or values.get("random_seed") or values.get("series_refinement"):
        return True
    if not prompt_enable_random_seed_for_copies(parent):
        return False
    values["random_seed"] = True
    sync_random_seed_setting(parent, True)
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

    MAINTAINER: document new uses in browser_window/dialogs/help_hidden_gems.py.
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
        combo = choice_field_widget(widget)
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findText(str(value))
        if idx >= 0:
            combo.setCurrentIndex(idx)

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

    if "steps" in params:
        _clamp_int_slider("steps", int(params["steps"]))

    if "quantization" in params:
        _set_choice("mflux_quantize", int(params["quantization"]))

    if "guidance" in params:
        _set_float_slider("guidance_scale", float(params["guidance"]))

    if "lora" in params and "mflux_lora" in spec_keys:
        entry = widgets.get("mflux_lora")
        if entry is not None:
            widget, _, spec = entry
            if spec.kind == "choice":
                combo = choice_field_widget(widget)
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

    sync_random_seed_setting(dialog, True)


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


def _text_input_stylesheet(*, unified_shell: bool = False) -> str:
    """Bordered arbitrary-text fields (prompt, negative prompt, etc.) in the image-gen dialog."""
    t = get_active_theme()
    input_bg = (
        t.button_bg_default_hex if unified_shell else t.dialog_input_background_hex
    )
    return f"""
    #imageGenDialog QPlainTextEdit,
    #imageGenDialog QLineEdit {{
        background-color: {input_bg};
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
    #imageGenDialog QComboBox#imageGenModelCombo,
    #imageGenDialog QComboBox#imageGenLoraCombo {{
        background-color: {input_bg};
        color: {t.dialog_text_color_hex};
        border: 1px solid {t.border_default_hex};
        border-radius: 4px;
        min-width: 280px;
        max-width: 4096px;
    }}
    #imageGenDialog QComboBox#imageGenLoraCombo QAbstractItemView {{
        min-width: 280px;
    }}
    #imageGenDialog QComboBox {{
        background-color: {input_bg};
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
    #imageGenDialog QPushButton#imageGenFluxPromptToolbarBtn {{
        padding: 5px 6px;
        font-size: 12px;
        min-height: 24px;
    }}
    #imageGenDialog QPushButton#imageGenCancelButton,
    #imageGenDialog QPushButton#imageGenCloseButton {{
        min-width: 0px;
        padding: 6px 12px;
    }}
    """ + image_gen_field_label_stylesheet()


DEFAULT_IMAGE_GEN_DIALOG_TITLE = "Create an image from text"
EXPAND_IMAGE_DIALOG_TITLE = "Expand existing image"
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


def configure_image_gen_prompt_import_button(button: QPushButton) -> None:
    """Import actions in the horizontal row under the image prompt field."""
    from imagegen_plugins.imagegen_flux_prompt_ai import configure_flux_prompt_toolbar_button

    configure_flux_prompt_toolbar_button(button)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def create_image_gen_prompt_import_row(buttons: List[QPushButton]) -> QWidget:
    from imagegen_plugins.image_gen_form_layout import (
        create_image_gen_prompt_button_bar_row,
    )

    row, layout = create_image_gen_prompt_button_bar_row(horizontal_pad=False)
    for button in buttons:
        configure_image_gen_prompt_import_button(button)
        layout.addWidget(button, 0)
    return row


def repopulate_image_gen_prompt_import_row(
    owner: Any,
    buttons: Optional[List[QPushButton]],
) -> None:
    panel = getattr(owner, "_fields_panel", None)
    if panel is None:
        return
    row = create_image_gen_prompt_import_row(buttons) if buttons else None
    panel.mount_prompt_import_row(row)


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
    col.setContentsMargins(0, 0, 0, IMAGE_GEN_FIELD_BORDER_PAD)
    col.setSpacing(IMAGE_GEN_SIDE_BUTTON_SPACING)
    col.setAlignment(Qt.AlignmentFlag.AlignTop)
    apply_image_gen_preview_client_background(host)
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


def insert_image_gen_side_column_widget_before_stretch(
    col: QVBoxLayout,
    widget: QWidget,
) -> None:
    """Insert a widget at the bottom of the side column, above the stretch."""
    stretch_idx = col.count() - 1
    if stretch_idx >= 0 and col.itemAt(stretch_idx).spacerItem() is not None:
        col.insertWidget(stretch_idx, widget, 0, Qt.AlignmentFlag.AlignTop)
    else:
        col.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)


def configure_image_gen_side_checkbox(checkbox: QCheckBox) -> None:
    checkbox.setObjectName("imageGenSideActionCheckbox")
    checkbox.setSizePolicy(
        QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
    )
    fm = checkbox.fontMetrics()
    checkbox.setMinimumHeight(fm.height() + 4)


def wrap_image_gen_side_checkbox(checkbox: QCheckBox) -> QWidget:
    """Side-column checkbox with bottom inset so labels are not clipped."""
    host = QWidget()
    host.setObjectName("imageGenSideCheckboxWrap")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, IMAGE_GEN_FIELD_BORDER_PAD)
    lay.setSpacing(0)
    lay.addWidget(checkbox)
    host.setFixedWidth(IMAGE_GEN_SIDE_BUTTON_WIDTH)
    host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
    return host


def pass_image_to_ai_checked(owner: Any) -> bool:
    cb = getattr(owner, "_pass_image_to_ai_cb", None)
    if cb is not None:
        return cb.isChecked()
    return load_pass_image_to_ai_with_prompt()


def mount_pass_image_to_ai_checkbox(
    owner: Any,
    *,
    image_noun: str = "source image",
) -> None:
    owner._pass_image_to_ai_cb = None
    if not is_lmstudio_sdk_installed():
        return
    col = getattr(owner, "_side_btn_col", None)
    if col is None:
        return
    cb = QCheckBox("Pass image to Prompt Generator")
    cb.setObjectName("imageGenPassImageToAiCheckbox")
    cb.setToolTip(
        f"Include the {image_noun} when refining the prompt with AI "
        "(requires a vision-capable model in LM Studio)."
    )
    cb.setChecked(load_pass_image_to_ai_with_prompt())

    def _on_toggled(checked: bool) -> None:
        try:
            save_pass_image_to_ai_with_prompt(bool(checked))
        except Exception:
            pass
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    cb.toggled.connect(_on_toggled)
    configure_image_gen_side_checkbox(cb)
    insert_image_gen_side_column_widget_before_stretch(
        col, wrap_image_gen_side_checkbox(cb)
    )
    owner._pass_image_to_ai_cb = cb
    host = getattr(owner, "_side_btn_host", None)
    if host is not None:
        host.updateGeometry()


def reset_image_gen_side_button_column_owner(owner: Any) -> None:
    col = getattr(owner, "_side_btn_col", None)
    if col is not None:
        clear_image_gen_side_button_layout(col)
    if hasattr(owner, "_aspect_checkbox"):
        owner._aspect_checkbox = None
    if hasattr(owner, "_flux_prompt_ai"):
        owner._flux_prompt_ai = None
    if hasattr(owner, "_pass_image_to_ai_cb"):
        owner._pass_image_to_ai_cb = None


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


def _snap_dim_floor(value: int, step: int) -> int:
    """Floor to step grid; matches pipeline align_dims_for_pipeline snapping."""
    step = max(1, int(step))
    return (int(value) // step) * step


def _aspect_pair_from_width(
    width: int,
    ratio: float,
    *,
    w_bounds: tuple[int, int],
    h_bounds: tuple[int, int],
    step: int,
) -> tuple[int, int]:
    w_lo, w_hi = w_bounds
    h_lo, h_hi = h_bounds
    if ratio <= 0:
        ratio = 1.0
    w = _snap_dim_floor(width, step)
    w = max(w_lo, min(w_hi, w))
    h = _snap_dim_floor(int(round(w / ratio)), step)
    h = max(h_lo, min(h_hi, h))
    w = _snap_dim_floor(int(round(h * ratio)), step)
    w = max(w_lo, min(w_hi, w))
    h = _snap_dim_floor(int(round(w / ratio)), step)
    h = max(h_lo, min(h_hi, h))
    return w, h


def _aspect_pair_from_height(
    height: int,
    ratio: float,
    *,
    w_bounds: tuple[int, int],
    h_bounds: tuple[int, int],
    step: int,
) -> tuple[int, int]:
    w_lo, w_hi = w_bounds
    h_lo, h_hi = h_bounds
    if ratio <= 0:
        ratio = 1.0
    h = _snap_dim_floor(height, step)
    h = max(h_lo, min(h_hi, h))
    w = _snap_dim_floor(int(round(h * ratio)), step)
    w = max(w_lo, min(w_hi, w))
    h = _snap_dim_floor(int(round(w / ratio)), step)
    h = max(h_lo, min(h_hi, h))
    w = _snap_dim_floor(int(round(h * ratio)), step)
    w = max(w_lo, min(w_hi, w))
    return w, h


def next_aspect_locked_dims(
    changed: str,
    direction: int,
    current_w: int,
    current_h: int,
    ratio: float,
    *,
    w_bounds: tuple[int, int],
    h_bounds: tuple[int, int],
    step: int,
) -> tuple[int, int]:
    """Next aspect-locked pair one step on the changed axis; avoids round-snap dead zones."""
    if direction not in (-1, 1):
        return current_w, current_h
    step = max(1, int(step))
    w_lo, w_hi = w_bounds
    h_lo, h_hi = h_bounds
    if changed == "width":
        probe = current_w + direction * step
        while w_lo <= probe <= w_hi:
            w, h = _aspect_pair_from_width(
                probe, ratio, w_bounds=w_bounds, h_bounds=h_bounds, step=step
            )
            if w != current_w or h != current_h:
                return w, h
            probe += direction * step
        return current_w, current_h
    probe = current_h + direction * step
    while h_lo <= probe <= h_hi:
        w, h = _aspect_pair_from_height(
            probe, ratio, w_bounds=w_bounds, h_bounds=h_bounds, step=step
        )
        if w != current_w or h != current_h:
            return w, h
        probe += direction * step
    return current_w, current_h


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
    if changed == "width":
        return _aspect_pair_from_width(
            value, ratio, w_bounds=w_bounds, h_bounds=h_bounds, step=step
        )
    return _aspect_pair_from_height(
        value, ratio, w_bounds=w_bounds, h_bounds=h_bounds, step=step
    )


class ImageGenDimensionAspectMixin:
    """Width/height helpers + optional aspect-ratio lock for image-gen dialogs."""

    _aspect_checkbox: Optional[QCheckBox]
    _aspect_lock_updating: bool
    _aspect_ratio: float

    def _effective_max_side(self) -> int:
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        return effective_max_for_plugin(self.plugin)

    def _apply_effective_max_to_dim_sliders(self) -> None:
        """Fit width/height to effective max edge, preserving aspect ratio."""
        if not self._has_dim_fields():
            return
        width = self._get_int_slider("width")
        height = self._get_int_slider("height")
        if width is None or height is None:
            try:
                src_w = int(self._values.get("width", 1024))
                src_h = int(self._values.get("height", 1024))
            except (TypeError, ValueError):
                return
        else:
            src_w, src_h = width, height
        if src_w <= 0 or src_h <= 0:
            return
        w, h = align_dims_for_pipeline(
            self.plugin.pipeline_id,
            src_w,
            src_h,
            effective_max_side=self._effective_max_side(),
        )
        scaled_down = w < src_w or h < src_h
        self._aspect_lock_updating = True
        try:
            self._set_int_slider("width", w)
            self._set_int_slider("height", h)
            self._values["width"] = w
            self._values["height"] = h
            if scaled_down and self._aspect_checkbox is not None:
                self._aspect_checkbox.setChecked(True)
                self._aspect_ratio = src_w / src_h
            elif self._aspect_lock_enabled():
                self._refresh_aspect_ratio_from_sliders()
        finally:
            self._aspect_lock_updating = False
            self._sync_aspect_lock_prev_dims()

    def refresh_generation_dim_limits(self) -> None:
        """Re-read app-wide max from settings; update bounds and clamp width/height."""
        if not self._has_dim_fields():
            return
        effective_max = self._effective_max_side()
        for key in ("width", "height"):
            entry = self._widgets.get(key)
            if entry is None:
                continue
            widget, _, spec = entry
            if spec.kind != "int_slider":
                continue
            lo = int(spec.min_value or 256)
            inner = widget.layout()
            slider = inner.itemAt(0).widget()
            spin = inner.itemAt(1).widget()
            slider.setMaximum(effective_max)
            spin.setMaximum(effective_max)
            slider.setMinimum(lo)
            spin.setMinimum(lo)
        self._apply_effective_max_to_dim_sliders()
        canvas = getattr(self, "_canvas", None)
        if canvas is not None and hasattr(canvas, "set_canvas_size"):
            values = self.collect_values()
            canvas.set_canvas_size(
                int(values.get("width", 1024)),
                int(values.get("height", 1024)),
            )

    def _init_dim_aspect_state(self) -> None:
        self._aspect_checkbox = None
        self._aspect_lock_updating = False
        self._aspect_ratio = 1.0
        self._aspect_lock_prev_w: Optional[int] = None
        self._aspect_lock_prev_h: Optional[int] = None

    def _sync_aspect_lock_prev_dims(self) -> None:
        width = self._get_int_slider("width")
        height = self._get_int_slider("height")
        if width is None or height is None:
            return
        self._aspect_lock_prev_w = int(width)
        self._aspect_lock_prev_h = int(height)

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
            w_bounds=self._spin_slider_limits("width"),
            h_bounds=self._spin_slider_limits("height"),
            step=step,
        )

    def _spin_slider_limits(self, key: str) -> tuple[int, int]:
        entry = self._widgets.get(key)
        if entry is None:
            return self._int_slider_bounds(key)
        widget, _, spec = entry
        if spec.kind != "int_slider":
            return self._int_slider_bounds(key)
        inner = widget.layout()
        spin = inner.itemAt(1).widget()
        return int(spin.minimum()), int(spin.maximum())

    def _resolve_aspect_locked_dims(
        self,
        changed_key: str,
        value: int,
        *,
        prev_w: int,
        prev_h: int,
    ) -> tuple[int, int]:
        old_val = prev_w if changed_key == "width" else prev_h
        if value == old_val:
            return prev_w, prev_h
        direction = 1 if value > old_val else -1
        step = self._dim_align_step()
        return next_aspect_locked_dims(
            changed_key,
            direction,
            prev_w,
            prev_h,
            self._aspect_ratio,
            w_bounds=self._spin_slider_limits("width"),
            h_bounds=self._spin_slider_limits("height"),
            step=step,
        )

    def _apply_aspect_locked_dims(self, changed_key: str, value: int) -> None:
        if not self._aspect_lock_enabled():
            return
        if self._aspect_lock_prev_w is None or self._aspect_lock_prev_h is None:
            self._sync_aspect_lock_prev_dims()
        prev_w = self._aspect_lock_prev_w
        prev_h = self._aspect_lock_prev_h
        if prev_w is None or prev_h is None:
            return
        w, h = self._resolve_aspect_locked_dims(
            changed_key,
            value,
            prev_w=prev_w,
            prev_h=prev_h,
        )
        if w == prev_w and h == prev_h:
            current_w = self._get_int_slider("width")
            current_h = self._get_int_slider("height")
            if current_w != prev_w or current_h != prev_h:
                self._aspect_lock_updating = True
                try:
                    self._set_int_slider("width", prev_w)
                    self._set_int_slider("height", prev_h)
                finally:
                    self._aspect_lock_updating = False
            return
        self._aspect_lock_updating = True
        try:
            self._set_int_slider("width", w)
            self._set_int_slider("height", h)
        finally:
            self._aspect_lock_updating = False
        self._aspect_lock_prev_w = w
        self._aspect_lock_prev_h = h

    def _on_dim_value_changed(self, changed_key: str, value: int) -> None:
        if self._aspect_lock_updating:
            return
        if self._aspect_lock_enabled():
            self._apply_aspect_locked_dims(changed_key, value)
            return
        step = self._dim_align_step()
        snapped = _snap_dim_floor(value, step)
        lo, hi = self._spin_slider_limits(changed_key)
        snapped = max(lo, min(hi, snapped))
        if snapped == value:
            return
        self._aspect_lock_updating = True
        try:
            self._set_int_slider(changed_key, snapped)
        finally:
            self._aspect_lock_updating = False
        self._sync_aspect_lock_prev_dims()

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
        self._sync_aspect_lock_prev_dims()

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
        w, h = align_dims_for_pipeline(
            self.plugin.pipeline_id,
            src_w,
            src_h,
            effective_max_side=self._effective_max_side(),
        )
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
            self._sync_aspect_lock_prev_dims()

    def _on_import_size(self) -> None:
        image_path = self._image_path_for_import_size()
        if not image_path:
            return
        self._apply_import_dims_from_image(image_path)
        if getattr(self, "_panel_mode", False):
            self.state_changed.emit()

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
        self._sync_aspect_lock_prev_dims()

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

    def _on_screen_size_dims(self) -> None:
        sw, sh = self._screen_pixel_size()
        w, h = align_dims_for_pipeline(
            self.plugin.pipeline_id,
            sw,
            sh,
            effective_max_side=self._effective_max_side(),
        )
        self._aspect_lock_updating = True
        try:
            self._set_int_slider("width", w)
            self._set_int_slider("height", h)
            if self._aspect_lock_enabled():
                self._refresh_aspect_ratio_from_sliders()
        finally:
            self._aspect_lock_updating = False
            self._sync_aspect_lock_prev_dims()

    def _on_square_dims(self) -> None:
        width = self._get_int_slider("width")
        if width is None:
            return
        w_lo, w_hi = self._int_slider_bounds("width")
        h_lo, h_hi = self._int_slider_bounds("height")
        lo = max(w_lo, h_lo)
        hi = min(w_hi, h_hi)
        step = self._dim_align_step()
        side = _snap_dim_floor(width, step)
        side = max(lo, min(hi, side))
        self._aspect_lock_updating = True
        try:
            if self._aspect_lock_enabled():
                self._aspect_ratio = 1.0
            self._set_int_slider("width", side)
            self._set_int_slider("height", side)
        finally:
            self._aspect_lock_updating = False
            self._sync_aspect_lock_prev_dims()

    def _on_reverse_dims(self) -> None:
        width = self._get_int_slider("width")
        height = self._get_int_slider("height")
        if width is None or height is None:
            return
        self._aspect_lock_updating = True
        try:
            if self._aspect_lock_enabled() and width > 0:
                self._aspect_ratio = height / width
            self._set_int_slider("width", height)
            self._set_int_slider("height", width)
        finally:
            self._aspect_lock_updating = False
            self._sync_aspect_lock_prev_dims()


IMAGE_GEN_PREVIEW_CLIENT_OBJECT_NAME = "imageGenPreviewClient"


def apply_image_gen_preview_splitter_theme(splitter: QSplitter) -> None:
    """Preview | controls splitter — same chrome as main window splitters."""
    apply_view_chrome_splitter_theme(splitter)


def image_gen_preview_workarea_fill():
    """Client-area margin behind letterboxed previews (browse border color)."""
    from config import effective_browse_border_qcolor

    return effective_browse_border_qcolor()


def image_gen_preview_client_background_hex() -> str:
    return image_gen_preview_workarea_fill().name()


def _image_gen_preview_client_stylesheet() -> str:
    """Work-area chrome (browse border color); overrides global QDialog QWidget dialog fill."""
    bg = image_gen_preview_client_background_hex()
    t = get_active_theme()
    name = IMAGE_GEN_PREVIEW_CLIENT_OBJECT_NAME
    return f"""
    #imageGenDialog,
    #imageGenDialog QWidget {{
        background-color: {bg};
        color: {t.dialog_text_color_hex};
    }}
    #imageGenDialog QLabel {{
        background-color: transparent;
    }}
    #imageGenDialog QWidget#{name},
    #imageGenDialog QFrame#{name},
    #imageGenDialog QLabel#{name},
    #imageGenDialog QWidget#imageGenBelowPromptRow,
    #imageGenDialog QWidget#imageGenControlsHost,
    #imageGenDialog QWidget#imageGenSideButtonColumn,
    #imageGenDialog QWidget#imageGenDialogFooter,
    #imageGenDialog QWidget#imageGenActionButtons {{
        background-color: {bg};
    }}
    #imageGenDialog QScrollArea {{
        background-color: {bg};
        border: none;
    }}
    #imageGenDialog QScrollArea > QWidget > QWidget {{
        background-color: {bg};
    }}
    #imageGenDialog QPushButton#imageGenFunctionSwitcherButton {{
        background-color: transparent;
    }}
    """


def apply_image_gen_preview_client_background(widget: QWidget) -> None:
    """Paint preview pane chrome using Settings > Theme > Browse border color."""
    if not widget.objectName():
        widget.setObjectName(IMAGE_GEN_PREVIEW_CLIENT_OBJECT_NAME)
    fill = image_gen_preview_workarea_fill()
    hex_color = fill.name()
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setAutoFillBackground(True)
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, fill)
    palette.setColor(QPalette.ColorRole.Base, fill)
    widget.setPalette(palette)
    prior = (widget.styleSheet() or "").strip()
    bg_rule = f"background-color: {hex_color};"
    if bg_rule not in prior:
        widget.setStyleSheet(f"{prior}\n{bg_rule}" if prior else bg_rule)


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
        apply_image_gen_preview_client_background(self)
        self.splitterMoved.connect(self._clamp_left_size)

    def add_preview_pane(self, widget: QWidget) -> None:
        apply_image_gen_preview_client_background(widget)
        widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.addWidget(widget)

    def add_controls_pane(self, widget: QWidget, *, min_width: int = 300) -> None:
        apply_image_gen_preview_client_background(widget)
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
        self._ensure_initial_sizes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._clamp_left_size()
        self._ensure_initial_sizes()

    def _ensure_initial_sizes(self) -> None:
        if self._initial_sizes_applied or self.width() <= 0:
            return
        self._initial_sizes_applied = True
        self._apply_initial_sizes()

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
        controls = self.widget(1)
        controls_min = controls.minimumWidth() if controls is not None else 0
        right_min = max(1, controls_min)
        max_left = max(1, int(total * self._max_left_ratio))
        max_left_for_controls = max(1, total - right_min)
        left_cap = min(max_left, max_left_for_controls)
        left = min(sizes[0], left_cap)
        right = max(right_min, total - left)
        if left + right > total:
            left = max(1, total - right)
        if left == sizes[0] and right == sizes[1]:
            return
        self.blockSignals(True)
        self.setSizes([left, right])
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


def apply_image_gen_dialog_shell(
    dlg: QDialog,
    *,
    window_title: str,
    min_width: int,
    min_height: int,
    unified_shell: bool = False,
) -> None:
    """Shared window chrome for image-gen and expand dialogs."""
    dlg.setWindowTitle(window_title)
    dlg.setObjectName("imageGenDialog")
    dlg.setMinimumSize(min_width, min_height)
    from utils import dialog_main_window, host_is_macos_space_mode

    flags = (
        Qt.Dialog
        | Qt.WindowTitleHint
        | Qt.WindowSystemMenuHint
        | Qt.WindowCloseButtonHint
    )
    mw = dialog_main_window(dlg)
    if mw is None or not host_is_macos_space_mode(mw):
        flags |= Qt.WindowStaysOnTopHint
    dlg.setWindowFlags(flags)
    dlg.setWindowModality(Qt.WindowModality.NonModal)
    from theme.theme import push_button_stylesheet

    t = get_active_theme()
    dlg.setStyleSheet(
        (dlg.styleSheet() or "")
        + _image_gen_preview_client_stylesheet()
        + push_button_stylesheet(t, selector="#imageGenDialog QPushButton")
        + _text_input_stylesheet(unified_shell=unified_shell)
    )


class ImageGenDialog(ImageGenDimensionAspectMixin, QDialog):
    """Prompt + dynamically built configuration fields; model chosen via dropdown."""

    state_changed = Signal()

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
        persistent_panel: bool = False,
        panel_mode: bool = False,
        installed: Optional[List[ImageGenModelPlugin]] = None,
        plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
        installed_flags: Optional[Dict[str, bool]] = None,
    ):
        super().__init__(parent)
        self._panel_mode = panel_mode
        self._image_gen_persistent_panel = persistent_panel or panel_mode
        self._plugins = list(plugins)
        self._function = function
        self._plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
        self._widgets: Dict[str, Any] = {}
        self._specs: List[FieldSpec] = []
        self._param_panel: Optional[ImageGenParameterPanel] = None
        self._fields_panel: Optional[ImageGenFieldsPanel] = None
        self._init_dim_aspect_state()
        self._flux_prompt_ai: Optional[ImageGenFluxPromptAi] = None
        self._flux_system_prompt_pane = None
        self._pass_image_to_ai_cb: Optional[QCheckBox] = None
        self._side_btn_host: Optional[QWidget] = None
        self._side_btn_col: Optional[QVBoxLayout] = None
        self._lora_steps_floor_widget: Optional[QComboBox] = None
        self._installed_flags: Dict[str, bool] = dict(installed_flags or {})
        self._defer_flux_prompt_extras = True
        self._installed_list = installed
        self._prebuilt_plugins_by_id = plugins_by_id

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
                self, window_title=window_title, min_width=520, min_height=480
            )
        self._build_ui()
        if getattr(self, "_defer_flux_prompt_extras", False):
            schedule_deferred_flux_prompt_extras(self)
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

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self._panel_mode:
            from imagegen_plugins.image_gen_panel_shell import (
                configure_image_gen_embedded_panel_layout,
            )

            configure_image_gen_embedded_panel_layout(layout, self)

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
        sync_image_gen_generate_enabled(
            self, panel=self, plugin_installed=self._selected_plugin_installed()
        )
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
        layout.addWidget(controls, 1)

        if self._panel_mode:
            return
        if self._image_gen_persistent_panel and not getattr(self, "_embedded", False):
            actions = create_image_gen_action_buttons(
                on_generate=self._on_generate,
                on_close=self.reject,
            )
            install_image_gen_escape_to_close(self)
            install_image_gen_footer_keyboard_shortcuts(self)
            layout.addWidget(
                create_image_gen_dialog_footer(self, self._function, actions)
            )
        else:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText(f"Generate {CMD_SYMBOL}{ENTER_SYMBOL}")
            apply_dialog_button_tooltips(buttons)
            buttons.accepted.connect(self._on_generate)
            buttons.rejected.connect(self.reject)
            if not getattr(self, "_embedded", False):
                layout.addWidget(
                    create_image_gen_dialog_footer(self, self._function, actions)
                )
            else:
                layout.addWidget(buttons)

    def _clear_field_rows(self) -> None:
        if self._param_panel is not None:
            self._param_panel.clear(keep_outer=IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT)
            self._widgets.clear()
        self._lora_steps_floor_widget = None

    def _populate_field_rows(self) -> None:
        if self._fields_panel is None or self.plugin is None:
            return
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        if self._param_panel is None:
            self._param_panel = ImageGenParameterPanel(
                self._fields_panel,
                build_options=default_widget_build_options(),
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
        self._connect_dim_aspect_lock()
        self._restore_aspect_lock_from_values()
        self._apply_effective_max_to_dim_sliders()
        self._connect_lora_steps_floor()
        refresh_image_gen_footer_keyboard_shortcuts(self)
        self._connect_panel_dirty_tracking()

    def _selected_plugin_installed(self) -> bool:
        if self.plugin is None:
            return False
        flagged = self._installed_flags.get(self.plugin.plugin_id)
        if flagged is not None:
            return bool(flagged)
        from imagegen_plugins.image_gen_model_selector import plugin_model_is_installed

        return plugin_model_is_installed(self.plugin)

    def _connect_panel_dirty_tracking(self) -> None:
        if not getattr(self, "_panel_mode", False):
            return
        from imagegen_plugins.image_gen_panel_dirty import connect_panel_field_widgets

        connect_panel_field_widgets(self, self.state_changed.emit)

    def _repopulate_side_buttons(self) -> None:
        repopulate_image_gen_prompt_import_row(
            self, self._build_prompt_action_buttons()
        )
        repopulate_image_gen_side_buttons(self, None)

    def _on_model_combo_changed(self, _index: int = 0) -> None:
        plugin_id = self._model_combo.currentData()
        new_plugin = self._plugins_by_id.get(plugin_id)
        if new_plugin is None:
            return
        if self.plugin is not None and new_plugin.plugin_id == self.plugin.plugin_id:
            return
        from imagegen_plugins.image_gen_model_selector import (
            refresh_dialog_mflux_lora_combo,
        )

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
        sync_image_gen_generate_enabled(
            self, panel=self, plugin_installed=self._selected_plugin_installed()
        )

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def refresh_mflux_lora_combo(self) -> None:
        """Refresh LoRA pulldown after Settings → LoRA catalog changes."""
        sync_image_gen_lora_field(self)
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

        if self._lora_steps_floor_widget is not lora_widget:
            lora_widget.currentIndexChanged.connect(self._on_mflux_lora_steps_changed)
            self._lora_steps_floor_widget = lora_widget
        self._apply_lora_steps_floor()

    def _on_mflux_lora_steps_changed(self, _index: int = 0) -> None:
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
        from imagegen_plugins.image_gen_source_nav import resolve_image_gen_main_window

        return resolve_image_gen_main_window(self)

    def _build_prompt_action_buttons(self) -> Optional[List[QPushButton]]:
        if not self._show_import_button():
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

    def _populate_prompt_side_buttons(self, btn_col: QVBoxLayout) -> None:
        """Legacy side column hook; prompt actions are inline under the prompt field."""
        buttons = self._build_prompt_action_buttons()
        if not buttons:
            return
        for button in buttons:
            btn_col.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        finalize_image_gen_side_button_column(btn_col)

    def _show_import_button(self) -> bool:
        if self._function != FUNCTION_CREATE:
            return False
        mw = self._main_window()
        if mw is None:
            return False
        if self._panel_mode:
            return True
        return mw.current_view_mode in ("browse", "thumbnail")

    def _active_image_path_for_ai(self) -> Optional[str]:
        """Browse current or single thumbnail selection (any readable image file)."""
        from imagegen_plugins.image_gen_source_nav import (
            active_image_path_for_browse_or_thumbnail,
        )

        return active_image_path_for_browse_or_thumbnail(self._main_window())

    def _image_path_for_import_size(self) -> Optional[str]:
        mw = self._main_window()
        if mw is not None and mw.current_view_mode not in ("browse", "thumbnail"):
            show_styled_warning(
                self,
                "Import Size",
                "Select an image in browse view, or select a single thumbnail, "
                "before importing.",
            )
            return None
        image_path = self._active_image_path_for_ai()
        if not image_path:
            show_styled_warning(self, "Import Size", "No image selected.")
            return None
        return image_path

    def _active_image_path_for_import(self) -> Optional[str]:
        """Same image resolution as copy/edit EXIF user comment (browse or single thumbnail)."""
        image_path = self._active_image_path_for_ai()
        if image_path is None:
            return None
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in _EXIF_USERCOMMENT_EXTENSIONS:
            return None
        return image_path

    def _import_prompt_text_from_active_image(self) -> bool:
        """Load prompt text from EXIF; return True on success."""
        mw = self._main_window()
        if mw is not None and mw.current_view_mode not in ("browse", "thumbnail"):
            show_styled_warning(
                self,
                "Import Text",
                "Select an image in browse view, or select a single thumbnail, "
                "before importing.",
            )
            return False
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
        if self._import_prompt_text_from_active_image() and self._panel_mode:
            self.state_changed.emit()

    def _on_import_available(self) -> None:
        mw = self._main_window()
        if mw is not None and mw.current_view_mode not in ("browse", "thumbnail"):
            show_styled_warning(
                self,
                "Import Rest",
                "Select an image in browse view, or select a single thumbnail, "
                "before importing.",
            )
            return
        if not self._import_prompt_text_from_active_image():
            return
        image_path = self._active_image_path_for_import()
        if not image_path:
            return
        apply_import_extras_from_image_path(self, image_path)
        if self._panel_mode:
            self.state_changed.emit()

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
                get_image_path=self._active_image_path_for_ai,
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
                label = prompt_spec.label or "Prompt"
                show_styled_warning(
                    self,
                    f"{label} required",
                    f"Enter {label.lower()} before generating an image.",
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
        )

    def restore_state(self, state, *, initial_prompt: Optional[str] = None) -> None:
        if state is not None:
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
            sync_image_gen_generate_enabled(
                self, panel=self, plugin_installed=self._selected_plugin_installed()
            )
        elif initial_prompt:
            self.set_prompt_text(initial_prompt)

    def _on_generate(self) -> None:
        if self._panel_mode:
            self.run_generate()
            return
        values = self._prepare_run_values()
        if values is None:
            return
        save_plugin_dialog_settings(
            self._function, self.plugin.plugin_id, values
        )
        if self._image_gen_persistent_panel:
            from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

            start_imagegen_without_closing(self, self._function, self.plugin, values)
            return
        self._result_values = values
        self.accept()

    def accepted_values(self) -> Optional[Dict[str, Any]]:
        return getattr(self, "_result_values", None)

    def accepted_plugin(self) -> Optional[ImageGenModelPlugin]:
        return getattr(self, "_result_values", None) and self.plugin
