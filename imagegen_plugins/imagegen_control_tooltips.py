#!/usr/bin/env python3
"""Tooltips for image-generation dialog controls."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import QCheckBox, QDialogButtonBox, QPushButton, QSlider, QSpinBox

from imagegen_plugins.image_gen_fields import FieldSpec

_FIELD_TOOLTIPS: dict[str, str] = {
    "width": "Output image width in pixels.",
    "height": "Output image height in pixels.",
    "steps": "Diffusion steps. More steps can improve quality but take longer.",
    "guidance_scale": "How strongly the model follows the prompt.",
    "use_resolution_binning": "Snap dimensions to resolution bins supported by this model.",
    "max_sequence_length": "Maximum text length (tokens) for the prompt encoder.",
    "clean_caption": "Clean up the prompt text before generation.",
    "random_seed": "Pick a new random seed each time you generate.",
    "copies": "Images to generate in one run. Values above 1 require Random seed.",
    "low_ram": "Use less memory during generation (may be slower).",
    "overlap_percentage": "Overlap between expand tiles when blending (percent).",
    "show_progressive_images": "Show partial previews while generation is running.",
    "aspect_ratio_test": (
        "When using multiple source images, all images to\n"
        "the exact pixel size of the first image.\n"
        "(Scale down if needed, white borders, centered.)"
    ),
}

_DIM_HELPER_TOOLTIPS: dict[str, str] = {
    "import": (
        "Load prompt text from the EXIF user comment of the selected image. "
        "Hold Option while pressing Import to also set width/height from the image "
        "(scaled down proportionally with aspect lock if larger than this model allows) "
        "and to load seed, steps, quantization, LoRA, and guidance when present."
    ),
    "screen_size": (
        "Set width and height from the primary display, aligned to this model's limits."
    ),
    "square": "Set width and height to the same value within model limits.",
    "reverse": "Swap width and height.",
    "aspect": (
        "Keep width and height proportional when either dimension is changed."
    ),
}

_DIALOG_BUTTON_TOOLTIPS: dict[str, str] = {
    "generate": "Start generation with the current settings.",
    "cancel": "Close without generating.",
}

_MODEL_COMBO_TOOLTIP = "Image generation model and backend for this action."


def field_tooltip(spec: FieldSpec) -> str:
    """Tooltip for a dynamic field (sliders and checkboxes)."""
    tip = _FIELD_TOOLTIPS.get(spec.key, "")
    if not tip:
        return ""
    if spec.kind in ("int_slider", "float_slider"):
        if spec.min_value is not None and spec.max_value is not None:
            tip = f"{tip} Allowed range: {spec.min_value}–{spec.max_value}."
        if spec.kind == "int_slider" and spec.step:
            tip = f"{tip} Step: {spec.step}."
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
    screen_btn: QPushButton,
    square_btn: QPushButton,
    reverse_btn: QPushButton,
    aspect_checkbox: QCheckBox,
    import_btn: Optional[QPushButton] = None,
) -> None:
    screen_btn.setToolTip(_DIM_HELPER_TOOLTIPS["screen_size"])
    square_btn.setToolTip(_DIM_HELPER_TOOLTIPS["square"])
    reverse_btn.setToolTip(_DIM_HELPER_TOOLTIPS["reverse"])
    aspect_checkbox.setToolTip(_DIM_HELPER_TOOLTIPS["aspect"])
    if import_btn is not None:
        import_btn.setToolTip(_DIM_HELPER_TOOLTIPS["import"])


_EDIT_IMPORT_TEXT_TOOLTIP = (
    "Load prompt text from the EXIF user\n"
    "comment of the selected image."
)

_EDIT_IMPORT_ALL_TOOLTIP = (
    "Load prompt text and other available settings\n"
    "from the EXIF user comment of the selected image."
)


def apply_import_button_tooltip(import_btn: QPushButton) -> None:
    import_btn.setToolTip(_DIM_HELPER_TOOLTIPS["import"])


def apply_edit_import_text_button_tooltip(import_btn: QPushButton) -> None:
    import_btn.setToolTip(_EDIT_IMPORT_TEXT_TOOLTIP)


def apply_edit_import_all_button_tooltip(import_btn: QPushButton) -> None:
    import_btn.setToolTip(_EDIT_IMPORT_ALL_TOOLTIP)


def apply_dialog_button_tooltips(buttons: QDialogButtonBox) -> None:
    ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if ok_btn is not None:
        ok_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["generate"])
    if cancel_btn is not None:
        cancel_btn.setToolTip(_DIALOG_BUTTON_TOOLTIPS["cancel"])


def apply_model_combo_tooltip(combo) -> None:
    combo.setToolTip(_MODEL_COMBO_TOOLTIP)
