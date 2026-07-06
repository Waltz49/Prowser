#!/usr/bin/env python3
"""Shared model dropdown for function-based image-gen dialogs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel
from imagegen_plugins.image_gen_persistence import load_plugin_dialog_settings
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15
from theme.theme_service import get_active_theme

_MODEL_COMBO_MIN_WIDTH = 300
_MODEL_COMBO_OBJECT_NAME = "imageGenModelCombo"
_LORA_COMBO_OBJECT_NAME = "imageGenLoraCombo"
_MODEL_COMMENT_LABEL_OBJECT_NAME = "imageGenModelCommentLabel"
NO_INSTALLED_MODELS_LABEL = "No models installed for this function."
_NO_INSTALLED_MODELS_PLUGIN_ID = "__no_installed_models__"


def model_label_for_plugin(
    plugin: ImageGenModelPlugin,
    saved: Optional[dict] = None,
) -> str:
    """Display name for a plugin in the model dropdown."""
    if saved is None:
        saved = load_plugin_dialog_settings(plugin.function, plugin.plugin_id)
    return plugin.display_name


def available_plugins(
    plugins: List[ImageGenModelPlugin],
) -> List[ImageGenModelPlugin]:
    return [p for p in plugins if p.is_available()]


def plugin_model_is_installed(plugin: ImageGenModelPlugin) -> bool:
    """True when the pipeline backend is present and model weights are in the HF cache."""
    if not plugin.is_available():
        return False
    from imagegen_plugins.image_gen_model_availability import pipeline_model_is_local

    return pipeline_model_is_local(plugin.pipeline_id, plugin.hf_model_id)


def installed_plugins(
    plugins: List[ImageGenModelPlugin],
) -> List[ImageGenModelPlugin]:
    return [p for p in plugins if plugin_model_is_installed(p)]


def build_installed_plugin_maps(
    plugins: List[ImageGenModelPlugin],
) -> Tuple[List[ImageGenModelPlugin], Dict[str, ImageGenModelPlugin], Dict[str, bool]]:
    """Single HF scan pass: installed list, id map, and per-plugin flags."""
    installed: List[ImageGenModelPlugin] = []
    by_id: Dict[str, ImageGenModelPlugin] = {}
    flags: Dict[str, bool] = {}
    for plugin in plugins:
        ok = plugin_model_is_installed(plugin)
        flags[plugin.plugin_id] = ok
        if ok:
            installed.append(plugin)
            by_id[plugin.plugin_id] = plugin
    return installed, by_id, flags


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


def sync_lora_combo_width(combo: QComboBox) -> None:
    """Keep the closed LoRA combo wide enough for trigger hints in item labels."""
    if combo.count() < 1:
        return
    longest = max(len(combo.itemText(i)) for i in range(combo.count()))
    combo.setMinimumContentsLength(max(longest, 20))
    fm = combo.fontMetrics()
    text_w = max(
        fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())
    )
    min_w = max(_MODEL_COMBO_MIN_WIDTH, text_w + 40)
    combo.setMinimumWidth(min_w)
    view = combo.view()
    if view is not None:
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setMinimumWidth(min_w + 8)


def finalize_lora_combo_display(combo: QComboBox) -> None:
    """After items are populated: full-width closed combo and non-elided dropdown labels."""
    sync_lora_combo_width(combo)


def configure_lora_combo(combo: QComboBox) -> None:
    """Full-width LoRA pulldown under the model description."""
    combo.setObjectName(_LORA_COMBO_OBJECT_NAME)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setMinimumContentsLength(20)
    combo.setMaximumWidth(4096)
    combo.setStyleSheet(
        "QComboBox#imageGenLoraCombo { min-width: 280px; max-width: 4096px; }"
        "QComboBox#imageGenLoraCombo QAbstractItemView { min-width: 280px; }"
    )
    view = combo.view()
    if view is not None:
        view.setTextElideMode(Qt.TextElideMode.ElideNone)


def plugin_supports_lora(plugin: Optional[ImageGenModelPlugin]) -> bool:
    """True when the plugin can use LoRAs (host configured on the plugin)."""
    return plugin is not None and bool(getattr(plugin, "lora_host_id", None))


def plugin_has_lora_choices(plugin: Optional[ImageGenModelPlugin]) -> bool:
    """True when the plugin has at least one selectable LoRA (besides None)."""
    if not plugin_supports_lora(plugin):
        return False
    from config import get_config
    from imagegen_plugins.lora_catalog import lora_choices_for_plugin

    choices = lora_choices_for_plugin(plugin, get_config().load_settings())
    return len(choices) > 1


def populate_image_gen_lora_combo(
    combo: QComboBox,
    plugin: Optional[ImageGenModelPlugin],
    *,
    pipeline_id: str = "",
    plugin_hf_model_id: str = "",
    current_preset_id: Any = None,
) -> None:
    """Fill the LoRA pulldown: None-only, installed choices, or unsupported (disabled)."""
    from config import get_config
    from imagegen_plugins.lora_catalog import (
        lora_choices_for_plugin,
        lora_choices_for_pipeline,
    )
    from imagegen_plugins.mflux_lora_presets import (
        LORA_UNSUPPORTED_LABEL,
        LORA_UNSUPPORTED_PRESET_ID,
        coerce_lora_preset_id,
    )

    if not plugin_supports_lora(plugin):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(LORA_UNSUPPORTED_LABEL, LORA_UNSUPPORTED_PRESET_ID)
        combo.setCurrentIndex(0)
        combo.setEnabled(False)
        combo.blockSignals(False)
        finalize_lora_combo_display(combo)
        return

    settings = get_config().load_settings()
    if plugin is not None:
        choices = lora_choices_for_plugin(plugin, settings)
    else:
        choices = lora_choices_for_pipeline(
            pipeline_id,
            plugin_hf_model_id,
            settings,
            lora_host_id=getattr(plugin, "lora_host_id", None) if plugin else None,
        )
    preset_id = coerce_lora_preset_id(
        current_preset_id if current_preset_id is not None else combo.currentData()
    )
    choice_ids = {c[1] for c in choices}
    if preset_id not in choice_ids:
        preset_id = "none"
    combo.blockSignals(True)
    combo.clear()
    for label, pid in choices:
        combo.addItem(str(label), pid)
    idx = combo.findData(preset_id)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.setEnabled(True)
    combo.blockSignals(False)
    finalize_lora_combo_display(combo)


def configure_model_combo(combo: QComboBox) -> None:
    """Model pulldown sized to fit the longest plugin label."""
    combo.setObjectName(_MODEL_COMBO_OBJECT_NAME)
    combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    # Override global theme QComboBox max-width (160px); avoid QWIDGETSIZE_MAX (warns).
    combo.setMaximumWidth(4096)


def _style_model_comment_label(label: QLabel) -> None:
    label.setObjectName(_MODEL_COMMENT_LABEL_OBJECT_NAME)
    t = get_active_theme()
    label.setStyleSheet(
        f"QLabel#{_MODEL_COMMENT_LABEL_OBJECT_NAME} {{"
        f" color: {t.text_disabled_hex};"
        f" font-size: 11px;"
        f" font-weight: normal;"
        f"}}"
    )


def sync_model_comment_label(
    label: QLabel,
    plugin: Optional[ImageGenModelPlugin],
) -> None:
    """Update the hint printed under the model pulldown for the selected plugin."""
    text = (plugin.model_comment or "").strip() if plugin is not None else ""
    label.setText(f"Model Notes: {text}" if text else "")
    label.setVisible(bool(text))


def build_plugin_model_combo(
    plugins: List[ImageGenModelPlugin],
    *,
    selected_plugin_id: Optional[str],
    parent: Optional[QWidget] = None,
    installed: Optional[List[ImageGenModelPlugin]] = None,
    plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
) -> Tuple[QComboBox, Dict[str, ImageGenModelPlugin]]:
    """Combo listing only plugins whose model weights are installed locally."""
    combo = QComboBox(parent)
    configure_model_combo(combo)
    if installed is None:
        installed = installed_plugins(plugins)
    if plugins_by_id is None:
        plugins_by_id = {p.plugin_id: p for p in installed}
    if not installed:
        combo.addItem(NO_INSTALLED_MODELS_LABEL, _NO_INSTALLED_MODELS_PLUGIN_ID)
        combo.setEnabled(False)
        sync_model_combo_width(combo)
        return combo, plugins_by_id

    for plugin in installed:
        combo.addItem(model_label_for_plugin(plugin), plugin.plugin_id)
        plugins_by_id[plugin.plugin_id] = plugin
    if selected_plugin_id:
        idx = combo.findData(selected_plugin_id)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    sync_model_combo_width(combo)
    return combo, plugins_by_id


def resolve_image_gen_panel_plugin(target: Any) -> Optional[ImageGenModelPlugin]:
    """Plugin for Generate enablement (top-level panel or nested settings)."""
    plugin = getattr(target, "plugin", None)
    if plugin is not None:
        return plugin
    settings = getattr(target, "_settings", None)
    if settings is not None:
        return getattr(settings, "plugin", None)
    return None


def sync_image_gen_generate_enabled(
    host: QWidget,
    *,
    panel: Optional[Any] = None,
    plugin_installed: Optional[bool] = None,
) -> None:
    """Enable Generate only when the panel has an installed model selected."""
    from PySide6.QtWidgets import QPushButton

    target = panel if panel is not None else host
    plugin = resolve_image_gen_panel_plugin(target)
    if plugin_installed is None:
        enabled = plugin is not None and plugin_model_is_installed(plugin)
    else:
        enabled = plugin is not None and bool(plugin_installed)
    root = host
    while root.parentWidget() is not None:
        root = root.parentWidget()
    btn = root.findChild(QPushButton, "imageGenGenerateButton")
    if btn is not None:
        btn.setEnabled(enabled)


def mount_image_gen_lora_field(
    panel: ImageGenFieldsPanel,
    *,
    parent: QWidget,
) -> Tuple[QWidget, Any]:
    """LoRA heading + control as a top-level field (not nested under Model)."""
    from imagegen_plugins.lora_stack_field import LoraStackField

    field = LoraStackField(parent)
    field.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    group = panel.add_labeled_field(
        "LoRA",
        field,
        to_outer=True,
        stretch_control=False,
    )
    group.hide()
    return group, field


def build_model_selector_row(
    plugins: List[ImageGenModelPlugin],
    *,
    selected_plugin_id: Optional[str],
    parent: Optional[QWidget] = None,
    installed: Optional[List[ImageGenModelPlugin]] = None,
    plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
) -> Tuple[QWidget, QComboBox, QLabel, Dict[str, ImageGenModelPlugin]]:
    """Block widget: model pulldown and optional model notes."""
    combo, plugins_by_id = build_plugin_model_combo(
        plugins,
        selected_plugin_id=selected_plugin_id,
        parent=parent,
        installed=installed,
        plugins_by_id=plugins_by_id,
    )
    comment_label = QLabel(parent)
    comment_label.setWordWrap(True)
    comment_label.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
    )
    _style_model_comment_label(comment_label)
    current_id = combo.currentData()
    plugin = plugins_by_id.get(current_id or "") if current_id else None
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
    installed: Optional[List[ImageGenModelPlugin]] = None,
    plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
) -> Optional[ImageGenModelPlugin]:
    """Pick the plugin to show first in a function dialog."""
    from imagegen_plugins.image_gen_active_model import load_active_plugin_id_for_function

    if installed is None:
        installed = installed_plugins(plugins)
    if not installed:
        return None
    if plugins_by_id is None:
        by_id = {p.plugin_id: p for p in installed}
    else:
        by_id = plugins_by_id
    if initial_plugin_id and initial_plugin_id in by_id:
        return by_id[initial_plugin_id]
    saved_id = load_active_plugin_id_for_function(function, plugins)
    if saved_id and saved_id in by_id:
        return by_id[saved_id]
    return installed[0]


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
        "mflux_lora_stack",
        "mflux_lora_paths",
        "mflux_lora_scales",
        "hf_model_id",
    ):
        out.pop(key, None)
    if new_plugin.hf_model_id:
        out["hf_model_id"] = new_plugin.hf_model_id
    return out


def sync_image_gen_lora_field(dialog: Any) -> None:
    """Show the LoRA control and register it in ``_widgets`` for the active plugin."""
    from imagegen_plugins.imagegen_control_tooltips import field_tooltip
    from imagegen_plugins.mflux_lora_presets import (
        coerce_lora_preset_id,
        normalize_lora_stack_from_values,
    )

    plugin = getattr(dialog, "plugin", None)
    specs: List[FieldSpec] = getattr(dialog, "_specs", None) or []
    values: Dict[str, Any] = getattr(dialog, "_values", None) or {}
    widgets: Dict[str, Any] = getattr(dialog, "_widgets", None) or {}
    lora_field = getattr(dialog, "_lora_field", None)
    lora_group = getattr(dialog, "_lora_group", None)
    if lora_field is None or lora_group is None:
        return

    host_id = getattr(plugin, "lora_host_id", None) if plugin else None
    use_stack = (
        plugin_supports_lora(plugin)
        and host_id is not None
        and host_id != HOST_SD15
    )

    lora_spec = next((s for s in specs if s.key == "mflux_lora"), None)
    if lora_spec is None and plugin is not None:
        collect = getattr(dialog, "collect_values", None)
        base_values = dict(values)
        if callable(collect):
            try:
                base_values = collect()
            except Exception:
                pass
        fresh_specs = plugin.field_specs(base_values)
        setattr(dialog, "_specs", fresh_specs)
        lora_spec = next((s for s in fresh_specs if s.key == "mflux_lora"), None)

    stack = normalize_lora_stack_from_values(values, pop=False)
    if use_stack and lora_field.is_stack_mode():
        live_stack = lora_field.selected_ids()
        if live_stack:
            stack = live_stack
    legacy = coerce_lora_preset_id(values.get("mflux_lora", "none"))
    if lora_spec is None:
        lora_spec = FieldSpec(
            key="mflux_lora",
            label="LoRA",
            kind="choice",
            default=legacy,
            choices=(("None", "none"),),
        )

    lora_group.show()
    lora_field.populate(
        plugin,
        current_stack=stack,
        current_preset_id=legacy,
    )
    if use_stack:
        if not getattr(dialog, "_lora_stack_values_connected", False):

            def _sync_lora_stack_to_dialog_values() -> None:
                lf = getattr(dialog, "_lora_field", None)
                if lf is None or not lf.is_stack_mode():
                    return
                vals = getattr(dialog, "_values", None)
                if isinstance(vals, dict):
                    vals["mflux_lora_stack"] = lf.selected_ids()

            lora_field.stack_changed.connect(_sync_lora_stack_to_dialog_values)
            dialog._lora_stack_values_connected = True
        tip = field_tooltip(lora_spec) or ""
        extra = (
            " Select one or more LoRAs (experimental stacking). "
            "Click to open the list; OK to apply."
        )
        lora_field.summary_combo.setToolTip((tip + extra).strip())
        widgets["mflux_lora_stack"] = (lora_field, None, lora_spec)
        widgets.pop("mflux_lora", None)
    else:
        tip = field_tooltip(lora_spec)
        if tip:
            lora_field.summary_combo.setToolTip(tip)
        widgets["mflux_lora"] = (lora_field.summary_combo, None, lora_spec)
        widgets.pop("mflux_lora_stack", None)

    dialog._lora_combo = lora_field.summary_combo


def apply_mflux_lora_collection_guard(
    out: Dict[str, Any],
    widgets: Dict[str, Any],
) -> None:
    """Do not pass a saved LoRA when the field is absent or unsupported."""
    stack_entry = widgets.get("mflux_lora_stack")
    if stack_entry is not None:
        widget, _, _spec = stack_entry
        if not widget.isEnabled():
            out["mflux_lora_stack"] = []
        elif hasattr(widget, "selected_ids"):
            out["mflux_lora_stack"] = widget.selected_ids()
        return

    entry = widgets.get("mflux_lora")
    if entry is None:
        out["mflux_lora"] = "none"
        out.pop("mflux_lora_stack", None)
        return
    widget, _, spec = entry
    if spec.kind == "choice" and not widget.isEnabled():
        out["mflux_lora"] = "none"


def refresh_dialog_mflux_lora_combo(dialog: Any) -> None:
    """Repopulate the LoRA pulldown for the dialog's current plugin, if present."""
    refresh = getattr(dialog, "refresh_mflux_lora_combo", None)
    if callable(refresh):
        refresh()


def switch_plugin_persisted_settings_preserving_prompt(
    function: str,
    outgoing_plugin_id: Optional[str],
    outgoing_values: Dict[str, Any],
    incoming_plugin_id: str,
    *,
    preserved_prompt: str,
) -> Dict[str, Any]:
    """Save outgoing plugin state and load incoming settings, keeping the UI prompt."""
    from imagegen_plugins.image_gen_persistence import (
        load_plugin_dialog_settings,
        switch_plugin_persisted_settings,
    )

    outgoing = dict(outgoing_values)
    outgoing["prompt"] = preserved_prompt
    if outgoing_plugin_id is None:
        incoming = load_plugin_dialog_settings(function, incoming_plugin_id)
    else:
        try:
            incoming = switch_plugin_persisted_settings(
                function,
                outgoing_plugin_id,
                outgoing,
                incoming_plugin_id,
            )
        except Exception:
            incoming = load_plugin_dialog_settings(function, incoming_plugin_id)
    incoming["prompt"] = preserved_prompt
    return incoming
