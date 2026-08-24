#!/usr/bin/env python3
"""Shared model dropdown for function-based image-gen dialogs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QListView,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_FIELD_LABEL_OBJECT_NAME,
    IMAGE_GEN_INLINE_FIELD_BLOCK_SPACING,
    ImageGenFieldsPanel,
    build_image_gen_inline_labeled_row,
    create_image_gen_lora_clear_button,
    create_image_gen_settings_gear_button,
    create_image_gen_truncating_info_label,
    image_gen_inline_field_label_width,
    set_image_gen_truncating_info_text,
    wrap_image_gen_inline_field_info_line,
)
from imagegen_plugins.image_gen_persistence import load_plugin_dialog_settings
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15, HOST_SDXL
from theme.theme_service import get_active_theme

_MODEL_COMBO_MIN_WIDTH = 300
_MODEL_COMBO_OBJECT_NAME = "imageGenModelCombo"
_LORA_COMBO_OBJECT_NAME = "imageGenLoraCombo"
_MODEL_COMMENT_LABEL_OBJECT_NAME = "imageGenModelCommentLabel"
_LORA_INFO_LABEL_OBJECT_NAME = "imageGenLoraInfoLabel"
NO_INSTALLED_MODELS_LABEL = "No models installed for this function."
_NO_INSTALLED_MODELS_PLUGIN_ID = "__no_installed_models__"


def model_label_for_plugin(
    plugin: ImageGenModelPlugin,
    saved: Optional[dict] = None,
) -> str:
    """Display name for a plugin in the model dropdown."""
    if saved is None:
        saved = load_plugin_dialog_settings(plugin.function, plugin.plugin_id)
    return plugin.model_label(saved)


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


def warm_installed_cache(plugins: List[ImageGenModelPlugin]) -> None:
    """Prime pipeline_model_is_local for each unique (pipeline_id, hf_model_id)."""
    seen: set[tuple[str, str]] = set()
    for plugin in plugins:
        if not plugin.is_available():
            continue
        key = (plugin.pipeline_id, plugin.hf_model_id)
        if key in seen:
            continue
        seen.add(key)
        plugin_model_is_installed(plugin)


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
    # Theme min-width lives on #imageGenDialog QComboBox#imageGenLoraCombo; keep size caps here.
    combo.setMinimumWidth(280)
    combo.setMaximumWidth(4096)
    if not isinstance(combo.view(), QListView):
        view = QListView(combo)
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        combo.setView(view)
    view = combo.view()
    if view is not None:
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setMinimumWidth(280)


def resolve_active_lora_model_key(widget: Optional[QWidget] = None) -> Optional[str]:
    """Map the active image-gen dialog's selected plugin to a Settings → LoRA model key."""
    from imagegen_plugins.lora_model_registry import lora_model_key_for_plugin

    host = widget
    while host is not None:
        plugin = getattr(host, "plugin", None)
        if plugin is not None and getattr(plugin, "lora_host_id", None):
            model_key = lora_model_key_for_plugin(plugin)
            if model_key:
                return model_key
        host = host.parentWidget()
    return None


def plugin_supports_lora(plugin: Optional[ImageGenModelPlugin]) -> bool:
    """True when the plugin can use LoRAs (host configured on the plugin)."""
    return plugin is not None and bool(getattr(plugin, "lora_host_id", None))



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
    set_image_gen_truncating_info_text(
        label,
        f"Model Notes: {text}" if text else "",
    )
    label.setVisible(bool(text))


def _style_lora_info_label(label: QLabel) -> None:
    label.setObjectName(_LORA_INFO_LABEL_OBJECT_NAME)
    t = get_active_theme()
    label.setStyleSheet(
        f"QLabel#{_LORA_INFO_LABEL_OBJECT_NAME} {{"
        f" color: {t.text_disabled_hex};"
        f" font-size: 11px;"
        f" font-weight: normal;"
        f"}}"
    )


def sync_image_gen_lora_field_accessories(lora_field: Any) -> None:
    """Refresh LoRA clear button and selected-LoRA info line visibility/text."""
    if lora_field is None:
        return
    clear_btn = getattr(lora_field, "_clear_all_btn", None)
    info_label = getattr(lora_field, "_info_label", None)
    has_selection = bool(lora_field.selected_ids()) and lora_field.summary_combo.isEnabled()
    if clear_btn is not None:
        clear_btn.setVisible(has_selection)
    if info_label is not None:
        if has_selection:
            set_image_gen_truncating_info_text(
                info_label,
                lora_field.selected_display_text(),
            )
            info_label.setVisible(True)
        else:
            set_image_gen_truncating_info_text(info_label, "")
            info_label.setVisible(False)


def sync_image_gen_lora_heading_label(lora_field: Any) -> None:
    """Use plural heading when the active model supports multi-LoRA stacking."""
    if lora_field is None:
        return
    label = getattr(lora_field, "_heading_label", None)
    if label is None:
        return
    label.setText("LoRAs" if lora_field.is_stack_mode() else "LoRA")


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
    generate_btn: Optional[Any] = None,
) -> None:
    """Enable Generate only when the panel has an installed model selected."""
    from PySide6.QtWidgets import QPushButton

    target = panel if panel is not None else host
    plugin = resolve_image_gen_panel_plugin(target)
    if plugin_installed is None:
        enabled = plugin is not None and plugin_model_is_installed(plugin)
    else:
        enabled = plugin is not None and bool(plugin_installed)
    btn = generate_btn
    if btn is None:
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
    lora_clear_btn = create_image_gen_lora_clear_button(parent)
    lora_clear_btn.hide()
    lora_settings_btn = create_image_gen_settings_gear_button(
        "lora_settings",
        parent,
        tooltip="Open LoRA settings",
    )
    field._clear_all_btn = lora_clear_btn
    info_label = create_image_gen_truncating_info_label(parent)
    _style_lora_info_label(info_label)
    info_label.hide()
    field._info_label = info_label

    def _on_lora_clear_clicked() -> None:
        field.clear_selection()

    lora_clear_btn.clicked.connect(_on_lora_clear_clicked)
    field.stack_changed.connect(lambda: sync_image_gen_lora_field_accessories(field))

    label_column_width = image_gen_inline_field_label_width(parent)
    lora_row = build_image_gen_inline_labeled_row(
        "LoRA",
        field,
        parent,
        control_accessories=[lora_settings_btn, lora_clear_btn],
        label_width=label_column_width,
    )
    field._heading_label = lora_row.findChild(QLabel, IMAGE_GEN_FIELD_LABEL_OBJECT_NAME)
    lora_block = QWidget(parent)
    lora_block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    lora_block_layout = QVBoxLayout(lora_block)
    lora_block_layout.setContentsMargins(0, 0, 0, 0)
    lora_block_layout.setSpacing(IMAGE_GEN_INLINE_FIELD_BLOCK_SPACING)
    lora_block_layout.addWidget(lora_row, 0)
    lora_block_layout.addWidget(
        wrap_image_gen_inline_field_info_line(
            info_label,
            lora_block,
            label_column_width=label_column_width,
        ),
        0,
    )
    group = panel.add_labeled_field(
        None,
        lora_block,
        to_outer=True,
        stretch_control=True,
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
    inline_label: bool = False,
) -> Tuple[QWidget, QComboBox, QLabel, Dict[str, ImageGenModelPlugin]]:
    """Block widget: model pulldown and optional model notes."""
    combo, plugins_by_id = build_plugin_model_combo(
        plugins,
        selected_plugin_id=selected_plugin_id,
        parent=parent,
        installed=installed,
        plugins_by_id=plugins_by_id,
    )
    comment_label = create_image_gen_truncating_info_label(parent)
    _style_model_comment_label(comment_label)
    current_id = combo.currentData()
    plugin = plugins_by_id.get(current_id or "") if current_id else None
    sync_model_comment_label(comment_label, plugin)

    block = QWidget(parent)
    block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    block_layout = QVBoxLayout(block)
    block_layout.setContentsMargins(0, 0, 0, 0)
    block_layout.setSpacing(IMAGE_GEN_INLINE_FIELD_BLOCK_SPACING)
    if inline_label:
        label_column_width = image_gen_inline_field_label_width(block)
        block_layout.addWidget(
            build_image_gen_inline_labeled_row(
                "Model",
                combo,
                block,
                stretch_control=True,
                label_width=label_column_width,
            ),
            0,
        )
        block_layout.addWidget(
            wrap_image_gen_inline_field_info_line(
                comment_label,
                block,
                label_column_width=label_column_width,
            ),
            0,
        )
    else:
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


def _normalize_exif_model_token(model_text: str) -> str:
    from imagegen_plugins.image_gen_naming import normalize_exif_model_name

    return normalize_exif_model_name(model_text).lower()


def _exif_model_match_keys(plugin: ImageGenModelPlugin) -> set[str]:
    keys: set[str] = set()
    for raw in (plugin.display_name, plugin.plugin_id):
        token = _normalize_exif_model_token(raw)
        if token:
            keys.add(token)
    hf_id = str(plugin.hf_model_id or "").strip()
    if hf_id:
        keys.add(_normalize_exif_model_token(hf_id))
        if "/" in hf_id:
            keys.add(_normalize_exif_model_token(hf_id.rsplit("/", 1)[-1]))
    return keys


def resolve_installed_plugin_for_exif_model(
    model_text: str,
    plugins: List[ImageGenModelPlugin],
) -> Optional[ImageGenModelPlugin]:
    """Match EXIF Image Model text to an installed plugin for this function."""
    token = _normalize_exif_model_token(model_text)
    if not token:
        return None
    for plugin in installed_plugins(plugins):
        if token in _exif_model_match_keys(plugin):
            return plugin
    return None


def switch_image_gen_dialog_plugin(
    dialog: Any,
    plugin: ImageGenModelPlugin,
) -> bool:
    """Select a model in the dialog combo (triggers persisted plugin switch)."""
    from imagegen_plugins.debug_exif_lora_trace import agent_exif_lora_dbg

    combo = getattr(dialog, "_model_combo", None)
    if combo is None:
        agent_exif_lora_dbg("H4", "image_gen_model_selector:switch_plugin", "no_combo")
        return False
    current = getattr(dialog, "plugin", None)
    if current is not None and current.plugin_id == plugin.plugin_id:
        agent_exif_lora_dbg(
            "H4",
            "image_gen_model_selector:switch_plugin",
            "already_current",
            {"plugin_id": plugin.plugin_id},
        )
        return True
    idx = combo.findData(plugin.plugin_id)
    if idx < 0:
        agent_exif_lora_dbg(
            "H4",
            "image_gen_model_selector:switch_plugin",
            "plugin_not_in_combo",
            {"plugin_id": plugin.plugin_id},
        )
        return False
    agent_exif_lora_dbg(
        "H4",
        "image_gen_model_selector:switch_plugin",
        "setCurrentIndex",
        {
            "from_plugin_id": getattr(current, "plugin_id", None),
            "to_plugin_id": plugin.plugin_id,
            "idx": idx,
        },
    )
    combo.setCurrentIndex(idx)
    return True


def resolve_plugin_for_restore(
    plugins_by_id: Dict[str, ImageGenModelPlugin],
    plugin_id: str,
    values: Optional[Dict[str, Any]] = None,
) -> Optional[ImageGenModelPlugin]:
    """Match a session plugin id, then fall back to snapshotted hf_model_id."""
    plugin = plugins_by_id.get(str(plugin_id or ""))
    if plugin is not None:
        return plugin
    hf = str((values or {}).get("hf_model_id") or "").strip()
    if not hf:
        return None
    for candidate in plugins_by_id.values():
        if str(candidate.hf_model_id or "").strip() == hf:
            return candidate
    return None


def apply_restored_dialog_plugin(dialog: Any, plugin: Optional[ImageGenModelPlugin]) -> None:
    """Set the model combo and plugin without persisting a user-driven switch."""
    if plugin is None:
        return
    combo = getattr(dialog, "_model_combo", None)
    if combo is not None:
        idx = combo.findData(plugin.plugin_id)
        if idx >= 0 and combo.currentIndex() != idx:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
    dialog.plugin = plugin
    comment = getattr(dialog, "_model_comment_label", None)
    if comment is not None:
        sync_model_comment_label(comment, plugin)



def sync_image_gen_lora_field(dialog: Any) -> None:
    """Show the LoRA control and register it in ``_widgets`` for the active plugin."""
    from imagegen_plugins.imagegen_control_tooltips import field_tooltip
    from imagegen_plugins.job_values_snapshot import (
        LORA_SCALES_BY_ID_KEY,
        job_values_snapshotted,
    )
    from imagegen_plugins.mflux_lora_presets import (
        coerce_lora_preset_id,
        lora_ids_and_scales_from_payload_paths,
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
        and host_id not in (HOST_SD15,)
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
    if use_stack:
        raw_stack = values.get("mflux_lora_stack")
        if isinstance(raw_stack, list):
            stack = normalize_lora_stack_from_values(
                {"mflux_lora_stack": raw_stack},
                pop=False,
            )
        # Keep the live widget stack across catalog refreshes, but never when
        # restoring a snapshotted job — those values are the source of truth.
        if lora_field.is_stack_mode() and not job_values_snapshotted(values):
            live_stack = lora_field.selected_ids()
            if live_stack:
                stack = live_stack
    legacy = coerce_lora_preset_id(values.get("mflux_lora", "none"))
    recovered_scales: Dict[str, float] = {}
    if (not stack and legacy == "none") or (not use_stack and legacy == "none"):
        recovered_ids, recovered_scales = lora_ids_and_scales_from_payload_paths(values)
        if recovered_ids:
            stack = recovered_ids
            if not use_stack:
                legacy = recovered_ids[0]
    if not use_stack and legacy == "none" and stack:
        legacy = coerce_lora_preset_id(stack[0])
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
    sync_image_gen_lora_heading_label(lora_field)
    from imagegen_plugins.debug_exif_lora_trace import agent_exif_lora_dbg

    agent_exif_lora_dbg(
        "H5",
        "image_gen_model_selector:sync_lora_field",
        "after_populate",
        {
            "stack_input": stack,
            "legacy_input": legacy,
            "selected_ids": lora_field.selected_ids(),
            "values_mflux_lora": values.get("mflux_lora"),
            "values_mflux_lora_stack": values.get("mflux_lora_stack"),
            "values_sd15_lora_paths": values.get("sd15_lora_paths"),
            "live_stack_used": bool(
                use_stack
                and lora_field.is_stack_mode()
                and not job_values_snapshotted(values)
                and lora_field.selected_ids()
            ),
        },
    )
    scales_raw = values.get(LORA_SCALES_BY_ID_KEY)
    if not isinstance(scales_raw, dict):
        scales_raw = recovered_scales
    elif recovered_scales:
        merged_scales = dict(recovered_scales)
        merged_scales.update(scales_raw)
        scales_raw = merged_scales
    if isinstance(scales_raw, dict) and hasattr(lora_field, "apply_scale_overrides"):
        lora_field.apply_scale_overrides(scales_raw)
    if not getattr(dialog, "_lora_popup_values_connected", False):

        def _sync_lora_popup_to_dialog_values() -> None:
            lf = getattr(dialog, "_lora_field", None)
            if lf is None or not lf.is_popup_mode():
                return
            vals = getattr(dialog, "_values", None)
            if not isinstance(vals, dict):
                return
            if lf.is_stack_mode():
                vals["mflux_lora_stack"] = lf.selected_ids()
            else:
                ids = lf.selected_ids()
                vals["mflux_lora"] = coerce_lora_preset_id(
                    ids[0] if ids else "none"
                )

        lora_field.stack_changed.connect(_sync_lora_popup_to_dialog_values)
        dialog._lora_popup_values_connected = True
    if use_stack:
        tip = field_tooltip(lora_spec) or ""
        extra = (
            " Select one or more LoRAs (experimental stacking). "
            "Click to open the list; OK to apply."
        )
        lora_field.summary_combo.setToolTip((tip + extra).strip())
        widgets["mflux_lora_stack"] = (lora_field, None, lora_spec)
        widgets.pop("mflux_lora", None)
    else:
        if not lora_field.is_popup_mode():
            tip = field_tooltip(lora_spec)
            if tip:
                lora_field.summary_combo.setToolTip(tip)
        widgets["mflux_lora"] = (lora_field.summary_combo, None, lora_spec)
        widgets.pop("mflux_lora_stack", None)

    dialog._lora_combo = lora_field.summary_combo
    sync_image_gen_lora_field_accessories(lora_field)


def _write_lora_scales_by_id(
    out: Dict[str, Any], lora_field: Any, preset_ids: list[str]
) -> None:
    from imagegen_plugins.job_values_snapshot import LORA_SCALES_BY_ID_KEY

    if not hasattr(lora_field, "scales_by_id"):
        out.pop(LORA_SCALES_BY_ID_KEY, None)
        return
    all_scales = lora_field.scales_by_id()
    scales = {
        preset_id: all_scales[preset_id]
        for preset_id in preset_ids
        if preset_id in all_scales
    }
    if scales:
        out[LORA_SCALES_BY_ID_KEY] = scales
    else:
        out.pop(LORA_SCALES_BY_ID_KEY, None)


def collect_lora_field_values(out: Dict[str, Any], lora_field: Any) -> None:
    """Write the live LoRA control into dialog values (stack or single-select)."""
    if lora_field is None:
        return
    if lora_field.is_stack_mode():
        ids = lora_field.selected_ids()
        out["mflux_lora_stack"] = ids
        _write_lora_scales_by_id(out, lora_field, ids)
        out.pop("mflux_lora", None)
        return
    ids = lora_field.selected_ids()
    preset = ids[0] if ids else "none"
    out["mflux_lora"] = preset
    if preset != "none":
        _write_lora_scales_by_id(out, lora_field, [preset])
    else:
        from imagegen_plugins.job_values_snapshot import LORA_SCALES_BY_ID_KEY

        out.pop(LORA_SCALES_BY_ID_KEY, None)
    out.pop("mflux_lora_stack", None)


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
        out.pop("mflux_lora", None)
        return

    entry = widgets.get("mflux_lora")
    if entry is None:
        out["mflux_lora"] = "none"
        out.pop("mflux_lora_stack", None)
        return
    out.pop("mflux_lora_stack", None)
    widget, _, spec = entry
    if spec.kind == "choice" and not widget.isEnabled():
        out["mflux_lora"] = "none"


def refresh_dialog_mflux_lora_combo(dialog: Any) -> None:
    """Repopulate the LoRA pulldown for the dialog's current plugin, if present."""
    refresh = getattr(dialog, "refresh_mflux_lora_combo", None)
    if callable(refresh):
        refresh()


_PRESERVE_ON_PLUGIN_SWITCH_KEYS = (
    "width",
    "height",
    "use_custom_size",
    "aspect_ratio_lock",
)


def switch_plugin_persisted_settings_preserving_prompt(
    function: str,
    outgoing_plugin_id: Optional[str],
    outgoing_values: Dict[str, Any],
    incoming_plugin_id: str,
    *,
    preserved_prompt: str,
) -> Dict[str, Any]:
    """Save outgoing plugin state; load incoming settings; keep prompt and output dims."""
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
    for key in _PRESERVE_ON_PLUGIN_SWITCH_KEYS:
        if key in outgoing_values:
            incoming[key] = outgoing_values[key]
    return incoming
