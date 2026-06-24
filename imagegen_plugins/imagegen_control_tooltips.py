#!/usr/bin/env python3
"""Tooltips for image-generation dialog controls."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QPushButton, QSlider, QSpinBox

from imagegen_plugins.image_gen_fields import FieldSpec
from thumbnails.thumbnail_constants import CMD_SYMBOL

_FIELD_TOOLTIPS: dict[str, str] = {
    "width": "Output image width in pixels.",
    "height": "Output image height in pixels.",
    "steps": (
        "How many drawing steps to use.\n"
        "More steps can look better\n"
        "but take more time."
    ),
    "guidance_scale": "How closely the image\nfollows your prompt.",
    "use_resolution_binning": (
        "Round width and height to sizes\n"
        "this model works best with."
    ),
    "max_sequence_length": "Maximum length (tokens) of your prompt text.",
    "clean_caption": "Clean up the prompt text before generation.",
    "random_seed": (
        "Use a new random number\n"
        "each time you generate."
    ),
    "copies": (
        "How many images to make at once.\n"
        "Turn on Random seed if you want\n"
        "more than one."
    ),
    "low_ram": (
        "Use less computer memory.\n"
        "May run slower."
    ),
    "overlap_percentage": "Overlap between expand tiles when blending (percent).",
    "show_progressive_images": (
        "View intermediate previews while the image\n"
        "is being generated. Turn off to avoid interruptions.\n"
        "Progress may still be seen in job status or File Information\n"
        "pane for images used as source for the current generation."
    ),
    "aspect_ratio_test": (
        "When you use several images,\n"
        "use copies to preserve the aspect ratio.\n"
        "May introduce borders in result, but not\n"
        "checking this may produce stretched or squashed\n"
        "results."

    ),
    "use_custom_size": (
        "Use custom width and height for the resulting image.\n"
        "May introduce borders in result."
        "If unchecked, the resulting image is the same size\n"
        "as the first source image."
    ),
    "mflux_lora": (
        "Optional style add-on for this model.\n"
        "Some styles need a trigger word\n"
        "within your prompt."
    ),
}

_DIM_HELPER_TOOLTIPS: dict[str, str] = {
    "import": (
        "Load prompt text saved\n"
        "in the EXIF user comment."
    ),
    "screen_size": (
        "Set size to fit your screen.\n"
        "Limited by aspect ratio lock and\n"
        "max size from Settings Dialog."
    ),
    "square": "Square:\nMake width and height equal.",
    "reverse": "Reverse:\nSwap width and height.",
    "aspect":"Keep width and height proportional\nwhen either dimension is changed.",
}

_DIALOG_BUTTON_TOOLTIPS: dict[str, str] = {
    "generate": (
        "Start making the image\nwith these settings.\n"
        "Also saves settings to the EXIF user comment."
    ),
    "cancel": "Close dialog without saving changes.",
    "close": f"Close this dialog ({CMD_SYMBOL}W).",
}

_MODEL_COMBO_TOOLTIP = "Choose which model\nmakes the image."


def field_tooltip(spec: FieldSpec) -> str:
    """Tooltip for a dynamic field (sliders and checkboxes)."""
    tip = _FIELD_TOOLTIPS.get(spec.key, "")
    if not tip:
        return ""
    if spec.kind in ("int_slider", "float_slider"):
        if spec.min_value is not None and spec.max_value is not None:
            tip = f"{tip}\nRange: {spec.min_value}–{spec.max_value}."
        if spec.kind == "int_slider" and spec.step:
            tip = f"{tip}\nStep: {spec.step}."
    return tip


def apply_field_control_tooltips(
    spec: FieldSpec,
    widget: Any,
    *,
    slider: Optional[QSlider] = None,
    spin: Optional[QSpinBox] = None,
) -> None:
    """Set tooltips on bool checkboxes and slider/spin controls."""
    tip = field_tooltip(spec)
    if not tip:
        return
    if spec.kind == "bool" and isinstance(widget, QCheckBox):
        widget.setToolTip(tip)
    elif spec.kind == "int_slider":
        if slider is not None:
            slider.setToolTip(tip)
        if spin is not None:
            spin.setToolTip(tip)
    elif spec.kind == "float_slider" and slider is not None:
        slider.setToolTip(tip)


def apply_dim_helper_tooltips(
    *,
    screen_btn: Optional[QPushButton] = None,
    square_btn: Optional[QPushButton] = None,
    reverse_btn: Optional[QPushButton] = None,
    aspect_checkbox: Optional[QCheckBox] = None,
    import_btn: Optional[QPushButton] = None,
) -> None:
    if screen_btn is not None:
        screen_btn.setToolTip(_DIM_HELPER_TOOLTIPS["screen_size"])
    if square_btn is not None:
        square_btn.setToolTip(_DIM_HELPER_TOOLTIPS["square"])
    if reverse_btn is not None:
        reverse_btn.setToolTip(_DIM_HELPER_TOOLTIPS["reverse"])
    if aspect_checkbox is not None:
        aspect_checkbox.setToolTip(_DIM_HELPER_TOOLTIPS["aspect"])
    if import_btn is not None:
        import_btn.setToolTip(_DIM_HELPER_TOOLTIPS["import"])


_EDIT_IMPORT_TEXT_TOOLTIP = (
    "Load the prompt text saved\n"
    "in the EXIF user comment\n"
    "of the selected image."
)

_EDIT_IMPORT_ALL_TOOLTIP = (
    "Load all settings except prompt text\n"
    "saved in the EXIF user comment\n"
    "of the selected image."
)

_EDIT_IMPORT_ALL_SETTINGS_TOOLTIP = (
    "Load settings and reference images\n"
    "saved with the selected image's\nEXIF user comment."
)


def apply_import_button_tooltip(import_btn: QPushButton) -> None:
    import_btn.setToolTip(_DIM_HELPER_TOOLTIPS["import"])


def apply_edit_import_text_button_tooltip(import_btn: QPushButton) -> None:
    import_btn.setToolTip(_EDIT_IMPORT_TEXT_TOOLTIP)


def apply_edit_import_all_button_tooltip(
    import_btn: QPushButton, *, include_prompt: bool = True
) -> None:
    import_btn.setToolTip(
        _EDIT_IMPORT_ALL_TOOLTIP
        if include_prompt
        else _EDIT_IMPORT_ALL_SETTINGS_TOOLTIP
    )


def apply_dialog_button_tooltips(buttons: QDialogButtonBox) -> None:
    ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if ok_btn is not None:
        ok_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["generate"])
    if cancel_btn is not None:
        cancel_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["cancel"])


def apply_image_gen_action_button_tooltips(
    close_btn: QPushButton,
    generate_btn: QPushButton,
) -> None:
    close_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["close"])
    generate_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["generate"])


def apply_model_combo_tooltip(combo) -> None:
    combo.setToolTip(_MODEL_COMBO_TOOLTIP)
