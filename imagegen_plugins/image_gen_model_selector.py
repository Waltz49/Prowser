#!/usr/bin/env python3
"""Shared model dropdown for function-based image-gen dialogs."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from imagegen_plugins.image_gen_persistence import load_dialog_settings
from imagegen_plugins.image_gen_pipeline_modes import menu_label_with_quant
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

_MODEL_COMBO_MIN_WIDTH = 300
_MODEL_COMBO_MAX_WIDTH = 480
_MODEL_COMBO_OBJECT_NAME = "imageGenModelCombo"
_MODEL_COMBO_MIN_CONTENTS_LENGTH = 48


def model_label_for_plugin(
    plugin: ImageGenModelPlugin,
    saved: Optional[dict] = None,
) -> str:
    """Display name for a plugin in the model dropdown (quant substitution only)."""
    if saved is None:
        saved = load_dialog_settings(
            plugin.function, fallback_plugin_id=plugin.plugin_id
        )
    return menu_label_with_quant(plugin.display_name, saved)


def available_plugins(
    plugins: List[ImageGenModelPlugin],
) -> List[ImageGenModelPlugin]:
    return [p for p in plugins if p.is_available()]


def configure_model_combo(combo: QComboBox) -> None:
    """Model pulldown width: overrides app theme max-width 160px on QComboBox."""
    combo.setObjectName(_MODEL_COMBO_OBJECT_NAME)
    combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(_MODEL_COMBO_MIN_WIDTH)
    combo.setMaximumWidth(_MODEL_COMBO_MAX_WIDTH)
    combo.setMinimumContentsLength(_MODEL_COMBO_MIN_CONTENTS_LENGTH)


def sync_model_comment_label(
    label: QLabel,
    plugin: Optional[ImageGenModelPlugin],
) -> None:
    """Update the hint printed beside the model pulldown for the selected plugin."""
    text = (plugin.model_comment or "").strip() if plugin is not None else ""
    label.setText(text)
    label.setVisible(bool(text))


def build_plugin_model_combo(
    plugins: List[ImageGenModelPlugin],
    *,
    selected_plugin_id: Optional[str],
    parent: Optional[QWidget] = None,
) -> Tuple[QComboBox, Dict[str, ImageGenModelPlugin]]:
    """Combo listing all function plugins; unavailable entries are disabled."""
    combo = QComboBox(parent)
    configure_model_combo(combo)
    plugins_by_id: Dict[str, ImageGenModelPlugin] = {}
    for plugin in plugins:
        combo.addItem(model_label_for_plugin(plugin), plugin.plugin_id)
        idx = combo.count() - 1
        if not plugin.is_available():
            item = combo.model().item(idx)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        plugins_by_id[plugin.plugin_id] = plugin
    if selected_plugin_id:
        idx = combo.findData(selected_plugin_id)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    elif combo.count() and not any(p.is_available() for p in plugins):
        combo.setCurrentIndex(0)
    return combo, plugins_by_id


def build_model_selector_row(
    plugins: List[ImageGenModelPlugin],
    *,
    selected_plugin_id: Optional[str],
    parent: Optional[QWidget] = None,
) -> Tuple[QWidget, QComboBox, QLabel, Dict[str, ImageGenModelPlugin]]:
    """Row widget: model pulldown + optional ``model_comment`` beside it."""
    combo, plugins_by_id = build_plugin_model_combo(
        plugins,
        selected_plugin_id=selected_plugin_id,
        parent=parent,
    )
    comment_label = QLabel(parent)
    comment_label.setWordWrap(True)
    comment_label.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    plugin = plugins_by_id.get(selected_plugin_id or "") or (
        plugins[0] if plugins else None
    )
    sync_model_comment_label(comment_label, plugin)

    row = QWidget(parent)
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.addWidget(combo, 0)
    row_layout.addWidget(comment_label, 1)
    return row, combo, comment_label, plugins_by_id


def resolve_initial_plugin(
    plugins: List[ImageGenModelPlugin],
    *,
    function: str,
    initial_plugin_id: Optional[str] = None,
) -> Optional[ImageGenModelPlugin]:
    """Pick the plugin to show first in a function dialog."""
    from imagegen_plugins.image_gen_active_model import load_active_plugin_id_for_function

    usable = available_plugins(plugins)
    if not usable:
        return None
    by_id = {p.plugin_id: p for p in usable}
    if initial_plugin_id and initial_plugin_id in by_id:
        return by_id[initial_plugin_id]
    saved_id = load_active_plugin_id_for_function(function, plugins)
    if saved_id and saved_id in by_id:
        return by_id[saved_id]
    return usable[0]
