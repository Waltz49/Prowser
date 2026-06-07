#!/usr/bin/env python3
"""Shared model dropdown for function-based image-gen dialogs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_persistence import load_dialog_settings
from imagegen_plugins.image_gen_pipeline_modes import menu_label_with_quant
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

_MODEL_COMBO_MIN_WIDTH = 300
_MODEL_COMBO_OBJECT_NAME = "imageGenModelCombo"


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


def sync_model_combo_width(combo: QComboBox) -> None:
    """Keep the closed model combo wide enough for every plugin label."""
    if combo.count() < 1:
        return
    longest = max(len(combo.itemText(i)) for i in range(combo.count()))
    combo.setMinimumContentsLength(max(longest, 20))
    fm = combo.fontMetrics()
    text_w = max(
        fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())
    )
    # Closed combo: text + drop-down affordance + dialog padding (8px each side).
    combo.setMinimumWidth(max(_MODEL_COMBO_MIN_WIDTH, text_w + 40))


def configure_model_combo(combo: QComboBox) -> None:
    """Model pulldown sized to fit the longest plugin label."""
    combo.setObjectName(_MODEL_COMBO_OBJECT_NAME)
    combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    # Override global theme QComboBox max-width (160px); avoid QWIDGETSIZE_MAX (warns).
    combo.setMaximumWidth(4096)


def sync_model_comment_label(
    label: QLabel,
    plugin: Optional[ImageGenModelPlugin],
) -> None:
    """Update the hint printed under the model pulldown for the selected plugin."""
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
    sync_model_combo_width(combo)
    return combo, plugins_by_id


def build_model_selector_row(
    plugins: List[ImageGenModelPlugin],
    *,
    selected_plugin_id: Optional[str],
    parent: Optional[QWidget] = None,
) -> Tuple[QWidget, QComboBox, QLabel, Dict[str, ImageGenModelPlugin]]:
    """Block widget: model pulldown with optional ``model_comment`` underneath."""
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

    block = QWidget(parent)
    block_layout = QVBoxLayout(block)
    block_layout.setContentsMargins(0, 0, 0, 0)
    block_layout.setSpacing(4)
    block_layout.addWidget(combo, 0)
    block_layout.addWidget(comment_label, 0)
    return block, combo, comment_label, plugins_by_id


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


def values_after_plugin_switch(
    current: Dict[str, Any],
    new_plugin: ImageGenModelPlugin,
) -> Dict[str, Any]:
    """
    Drop model-specific keys from dialog values when the user picks another plugin.

    Ensures field_specs and the LoRA pulldown target the new base model (e.g. Klein 4B vs 9B).
    """
    out = dict(current)
    for key in (
        "mflux_lora",
        "mflux_lora_paths",
        "mflux_lora_scales",
        "hf_model_id",
    ):
        out.pop(key, None)
    if new_plugin.hf_model_id:
        out["hf_model_id"] = new_plugin.hf_model_id
    return out


def refresh_dialog_mflux_lora_combo(dialog: Any) -> None:
    """Repopulate the LoRA pulldown for the dialog's current plugin, if present."""
    refresh = getattr(dialog, "refresh_mflux_lora_combo", None)
    if callable(refresh):
        refresh()
