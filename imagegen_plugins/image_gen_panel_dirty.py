#!/usr/bin/env python3
"""Connect field widgets to a panel state_changed signal."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QPlainTextEdit,
    QSlider,
)
from theme.spin_box import StepSpinBox


def connect_widget_dirty_tracking(widget: Any, emit: Callable[[], None]) -> None:
    if isinstance(widget, QPlainTextEdit):
        widget.textChanged.connect(lambda: emit())
    elif isinstance(widget, QCheckBox):
        widget.toggled.connect(lambda _v: emit())
    elif isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(lambda _i: emit())
    elif isinstance(widget, StepSpinBox):
        widget.valueChanged.connect(lambda _v: emit())
    elif isinstance(widget, QSlider):
        widget.valueChanged.connect(lambda _v: emit())


def connect_panel_field_widgets(panel, emit: Callable[[], None]) -> None:
    widgets = getattr(panel, "_widgets", None) or {}
    for _key, entry in widgets.items():
        widget = entry[0] if entry else None
        if widget is None:
            continue
        if hasattr(widget, "layout") and widget.layout() is not None:
            inner = widget.layout()
            for i in range(inner.count()):
                child = inner.itemAt(i).widget()
                if child is not None:
                    connect_widget_dirty_tracking(child, emit)
        else:
            connect_widget_dirty_tracking(widget, emit)
    series_cb = getattr(panel, "_series_refinement_cb", None)
    if series_cb is not None:
        series_cb.toggled.connect(lambda _v: emit())
    aspect_cb = getattr(panel, "_aspect_checkbox", None)
    if aspect_cb is not None:
        aspect_cb.toggled.connect(lambda _v: emit())
    pass_image_cb = getattr(panel, "_pass_image_to_ai_cb", None)
    if pass_image_cb is not None:
        pass_image_cb.toggled.connect(lambda _v: emit())
    model_combo = getattr(panel, "_model_combo", None)
    if model_combo is not None and not getattr(panel, "_model_combo_dirty_connected", False):
        model_combo.currentIndexChanged.connect(lambda _i: emit())
        panel._model_combo_dirty_connected = True
    lora_combo = getattr(panel, "_lora_combo", None)
    if lora_combo is not None and not getattr(panel, "_lora_dirty_connected", False):
        lora_combo.currentIndexChanged.connect(lambda _i: emit())
        panel._lora_dirty_connected = True
