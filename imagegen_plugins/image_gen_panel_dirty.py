#!/usr/bin/env python3
"""Connect field widgets to a panel state_changed signal."""

from __future__ import annotations

from typing import Any, Callable, Set

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QPlainTextEdit,
    QSlider,
)
from theme.spin_box import StepSpinBox


def _connected_widget_ids(panel: Any, attr: str) -> Set[int]:
    ids = getattr(panel, attr, None)
    if ids is None:
        ids = set()
        setattr(panel, attr, ids)
    return ids


def clear_widget_connection_ids(panel: Any, attr: str) -> None:
    """Drop tracked widget ids so repopulated controls can be reconnected."""
    _connected_widget_ids(panel, attr).clear()


def connect_widget_dirty_tracking_once(
    panel: Any,
    widget: Any,
    emit: Callable[[], None],
    *,
    attr: str = "_dirty_connected_widget_ids",
) -> None:
    """Connect dirty tracking once per widget instance (survives field repopulate)."""
    if widget is None:
        return
    ids = _connected_widget_ids(panel, attr)
    wid = id(widget)
    if wid in ids:
        return
    ids.add(wid)
    connect_widget_dirty_tracking(widget, emit)


def connect_spin_value_changed_once(
    panel: Any,
    spin: Any,
    slot: Callable[..., None],
    *,
    attr: str = "_spin_connected_widget_ids",
) -> None:
    """Connect spin.valueChanged once per spin instance."""
    if spin is None:
        return
    ids = _connected_widget_ids(panel, attr)
    wid = id(spin)
    if wid in ids:
        return
    ids.add(wid)
    spin.valueChanged.connect(slot)


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
    clear_widget_connection_ids(panel, "_dirty_connected_widget_ids")
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
                    connect_widget_dirty_tracking_once(panel, child, emit)
        else:
            connect_widget_dirty_tracking_once(panel, widget, emit)
    series_cb = getattr(panel, "_series_refinement_cb", None)
    if series_cb is not None:
        connect_widget_dirty_tracking_once(panel, series_cb, emit)
    aspect_cb = getattr(panel, "_aspect_checkbox", None)
    if aspect_cb is not None:
        connect_widget_dirty_tracking_once(panel, aspect_cb, emit)
    pass_image_cb = getattr(panel, "_pass_image_to_ai_cb", None)
    if pass_image_cb is not None:
        connect_widget_dirty_tracking_once(panel, pass_image_cb, emit)
    model_combo = getattr(panel, "_model_combo", None)
    if model_combo is not None and not getattr(panel, "_model_combo_dirty_connected", False):
        model_combo.currentIndexChanged.connect(lambda _i: emit())
        panel._model_combo_dirty_connected = True
    lora_field = getattr(panel, "_lora_field", None)
    if lora_field is not None and not getattr(panel, "_lora_dirty_connected", False):
        if lora_field.is_popup_mode():
            lora_field.stack_changed.connect(lambda: emit())
        else:
            lora_field.summary_combo.currentIndexChanged.connect(lambda _i: emit())
        panel._lora_dirty_connected = True
