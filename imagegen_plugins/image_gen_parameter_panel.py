#!/usr/bin/env python3
"""Generic parameter panel builder from per-plugin field layout trees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_fields import (
    FieldGroup,
    FieldNode,
    FieldSpec,
    flatten_field_specs,
    resolve_plugin_field_layout,
)
from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_SEED_SPIN_MAX_WIDTH,
    ImageGenFieldsPanel,
    create_image_gen_field_reset_button,
    create_image_gen_prompt_edit,
    sync_image_gen_field_reset_button_active,
    wrap_image_gen_choice_row,
    wrap_image_gen_slider_row,
)
from imagegen_plugins.image_gen_model_selector import apply_mflux_lora_collection_guard
from imagegen_plugins.imagegen_control_tooltips import apply_field_control_tooltips


@dataclass
class WidgetBuildOptions:
    non_prompt_text_min_height: int = 72
    float_label_precise: bool = False
    show_field_reset_buttons: bool = True


def default_widget_build_options(
    *,
    non_prompt_text_min_height: int = 72,
    float_label_precise: bool = False,
) -> WidgetBuildOptions:
    """Default widget build options for image-gen function panels."""
    return WidgetBuildOptions(
        non_prompt_text_min_height=non_prompt_text_min_height,
        float_label_precise=float_label_precise,
    )


def choice_field_widget(widget: QWidget) -> QComboBox:
    """Return the QComboBox for a choice field, including reset-button rows."""
    if isinstance(widget, QComboBox):
        return widget
    inner = widget.layout()
    child = inner.itemAt(0).widget()
    if not isinstance(child, QComboBox):
        raise TypeError("Expected QComboBox in choice field row")
    return child


def _maybe_field_reset_button(
    spec: FieldSpec,
    *,
    options: WidgetBuildOptions,
) -> Optional[QPushButton]:
    if not options.show_field_reset_buttons:
        return None
    if spec.reset_default is None:
        return None
    if spec.kind not in ("int_slider", "float_slider", "choice"):
        return None
    return create_image_gen_field_reset_button()


def _field_current_value(spec: FieldSpec, widget: QWidget, extra: Any) -> Any:
    if spec.kind == "int_slider":
        inner = widget.layout()
        return inner.itemAt(1).widget().value()
    if spec.kind == "float_slider":
        inner = widget.layout()
        slider = inner.itemAt(0).widget()
        scale = extra or 10
        return slider.value() / scale
    if spec.kind == "choice":
        return choice_field_widget(widget).currentData()
    return None


def _field_matches_reset_default(
    spec: FieldSpec, current: Any, extra: Any
) -> bool:
    target = spec.reset_default
    if spec.kind == "float_slider":
        step = float(spec.step or 0.1)
        scale = extra or 10
        tol = max(step / 2.0, 1.0 / scale / 2.0)
        return abs(float(current) - float(target)) <= tol
    if spec.kind == "choice":
        combo_val = current
        if combo_val == target:
            return True
        return str(combo_val) == str(target)
    return int(current) == int(target)


def _sync_field_reset_button(
    spec: FieldSpec,
    widget: QWidget,
    extra: Any,
    button: QPushButton,
) -> None:
    current = _field_current_value(spec, widget, extra)
    sync_image_gen_field_reset_button_active(
        button,
        active=not _field_matches_reset_default(spec, current, extra),
    )


def _wire_field_reset_button(
    spec: FieldSpec,
    widget: QWidget,
    extra: Any,
    button: QPushButton,
) -> None:
    def _reset() -> None:
        current = _field_current_value(spec, widget, extra)
        if _field_matches_reset_default(spec, current, extra):
            return
        val = spec.reset_default
        if spec.kind == "int_slider":
            inner = widget.layout()
            spin = inner.itemAt(1).widget()
            lo = int(spec.min_value or 0)
            hi = int(spec.max_value or 100)
            spin.setValue(max(lo, min(hi, int(val))))
        elif spec.kind == "float_slider":
            inner = widget.layout()
            slider = inner.itemAt(0).widget()
            lo = float(spec.min_value or 0.0)
            hi = float(spec.max_value or 10.0)
            scale = extra or 10
            clamped = max(lo, min(hi, float(val)))
            slider.setValue(int(clamped * scale))
        elif spec.kind == "choice":
            combo = choice_field_widget(widget)
            idx = combo.findData(val)
            if idx < 0:
                idx = combo.findText(str(val))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        _sync_field_reset_button(spec, widget, extra, button)

    button.clicked.connect(_reset)

    if spec.kind == "int_slider":
        inner = widget.layout()
        spin = inner.itemAt(1).widget()
        spin.valueChanged.connect(
            lambda _v: _sync_field_reset_button(spec, widget, extra, button)
        )
    elif spec.kind == "float_slider":
        inner = widget.layout()
        slider = inner.itemAt(0).widget()
        slider.valueChanged.connect(
            lambda _v: _sync_field_reset_button(spec, widget, extra, button)
        )
    elif spec.kind == "choice":
        choice_field_widget(widget).currentIndexChanged.connect(
            lambda _i: _sync_field_reset_button(spec, widget, extra, button)
        )

    _sync_field_reset_button(spec, widget, extra, button)


def build_seed_and_random_seed_row(
    seed_widget: QWidget, random_widget: QWidget
) -> QWidget:
    """Horizontal row: seed spinbox, then Randomize checkbox."""
    if isinstance(seed_widget, QSpinBox):
        seed_widget.setMaximumWidth(IMAGE_GEN_SEED_SPIN_MAX_WIDTH)
        seed_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
    if isinstance(random_widget, QCheckBox):
        random_widget.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        random_widget.setMinimumWidth(random_widget.sizeHint().width())

    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    row.addWidget(
        seed_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    row.addWidget(
        random_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    row_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return row_w


def widget_for_field_spec(
    spec: FieldSpec,
    *,
    options: Optional[WidgetBuildOptions] = None,
) -> Tuple[QWidget, Any]:
    opts = options or WidgetBuildOptions()

    if spec.kind == "text":
        if spec.key == "prompt":
            edit = create_image_gen_prompt_edit()
        else:
            edit = QPlainTextEdit()
            edit.setMinimumHeight(opts.non_prompt_text_min_height)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        edit.setPlainText(str(spec.default or ""))
        return edit, None

    if spec.kind == "bool":
        label = spec.bool_label_override or spec.label
        cb = QCheckBox(label)
        cb.setChecked(bool(spec.default))
        apply_field_control_tooltips(spec, cb)
        if spec.key == "series_refinement":
            cb.setToolTip(
                "For a series of copies, replace the first source image with "
                "each new result before the next copy. Other source images "
                "stay in the same order."
            )
        return cb, None

    if spec.kind == "choice":
        combo = QComboBox()
        for c in spec.choices or ():
            if isinstance(c, (tuple, list)) and len(c) >= 2:
                combo.addItem(str(c[0]), c[1])
            else:
                combo.addItem(str(c), c)
        idx = combo.findData(spec.default)
        if idx < 0:
            idx = combo.findText(str(spec.default))
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        reset_btn = _maybe_field_reset_button(spec, options=opts)
        row = wrap_image_gen_choice_row(combo, reset_button=reset_btn)
        if reset_btn is not None:
            _wire_field_reset_button(spec, row, None, reset_btn)
        return row, None

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
        spin.setMaximumWidth(72)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        apply_field_control_tooltips(spec, slider, slider=slider, spin=spin)
        reset_btn = _maybe_field_reset_button(spec, options=opts)
        row = wrap_image_gen_slider_row(slider, spin, reset_button=reset_btn)
        if reset_btn is not None:
            _wire_field_reset_button(spec, row, None, reset_btn)
        return row, None

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
        if opts.float_label_precise and step < 0.1:
            label = QLabel(f"{val:.2f}")

            def update_label(v: int, lbl=label, sc=scale, st=step):
                lbl.setText(f"{v / sc:.2f}" if st < 0.1 else f"{v / sc:.1f}")

        else:
            label = QLabel(f"{val:.1f}")

            def update_label(v: int, lbl=label, sc=scale):
                lbl.setText(f"{v / sc:.1f}")

        slider.valueChanged.connect(update_label)
        apply_field_control_tooltips(spec, slider, slider=slider)
        reset_btn = _maybe_field_reset_button(spec, options=opts)
        row = wrap_image_gen_slider_row(slider, label, reset_button=reset_btn)
        if reset_btn is not None:
            _wire_field_reset_button(spec, row, scale, reset_btn)
        return row, scale

    if spec.kind == "seed":
        spin = QSpinBox()
        spin.setMinimum(0)
        spin.setMaximum(2**31 - 1)
        spin.setValue(int(spec.default or 0))
        spin.setMaximumWidth(IMAGE_GEN_SEED_SPIN_MAX_WIDTH)
        spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return spin, None

    label = QLabel(str(spec.default))
    return label, None


def collect_widget_values(
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    base_values: Dict[str, Any],
) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base_values)
    for key, (widget, extra, spec) in widgets.items():
        if spec.kind == "text":
            out[key] = widget.toPlainText()
        elif spec.kind == "bool":
            out[key] = widget.isChecked()
        elif spec.kind == "choice":
            val = choice_field_widget(widget).currentData()
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
    apply_mflux_lora_collection_guard(out, widgets)
    return out


class ImageGenParameterPanel:
    """Builds and reads parameter controls from a plugin field layout tree."""

    def __init__(
        self,
        fields_panel: ImageGenFieldsPanel,
        *,
        build_options: Optional[WidgetBuildOptions] = None,
    ):
        self._fields_panel = fields_panel
        self._build_options = build_options or WidgetBuildOptions()
        self.widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]] = {}
        self.specs: List[FieldSpec] = []
        self.layout_nodes: Tuple[FieldNode, ...] = ()

    def clear(self, *, keep_outer: int) -> None:
        self._fields_panel.clear(keep=keep_outer)
        self.widgets.clear()

    def repopulate(
        self,
        plugin,
        values: Dict[str, Any],
        *,
        keep_outer: int,
        effective_max_side: int,
    ) -> None:
        self.clear(keep_outer=keep_outer)
        self.layout_nodes = resolve_plugin_field_layout(
            plugin, values, effective_max_side=effective_max_side
        )
        self.specs = flatten_field_specs(self.layout_nodes)
        mount_field_tree(
            self._fields_panel,
            self.layout_nodes,
            self.widgets,
            build_options=self._build_options,
        )

    def collect_values(self, base_values: Dict[str, Any]) -> Dict[str, Any]:
        return collect_widget_values(self.widgets, base_values)


def mount_field_tree(
    panel: ImageGenFieldsPanel,
    nodes: Tuple[FieldNode, ...],
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    *,
    build_options: Optional[WidgetBuildOptions] = None,
) -> None:
    """Mount a resolved field layout tree into an ImageGenFieldsPanel."""
    opts = build_options or WidgetBuildOptions()
    for node in nodes:
        _mount_node(panel, node, widgets, options=opts)


def _mount_node(
    panel: ImageGenFieldsPanel,
    node: FieldNode,
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    *,
    options: WidgetBuildOptions,
) -> None:
    if isinstance(node, FieldSpec):
        _mount_leaf_spec(panel, node, widgets, options=options)
        return

    group = node
    if group.layout == "prompt_block":
        for child in group.children:
            if isinstance(child, FieldSpec) and child.key == "prompt":
                widget, extra = widget_for_field_spec(child, options=options)
                widgets[child.key] = (widget, extra, child)
                panel.add_prompt_field(child.label, widget)
            elif isinstance(child, FieldSpec) and child.key == "negative_prompt":
                widget, extra = widget_for_field_spec(child, options=options)
                widgets[child.key] = (widget, extra, child)
                panel.add_labeled_field(
                    child.label,
                    widget,
                    copy_from_edit=widget,
                )
            else:
                _mount_node(panel, child, widgets, options=options)
        return

    if group.layout == "seed_row":
        seed_spec = random_spec = None
        for child in group.children:
            if isinstance(child, FieldSpec):
                if child.key == "seed":
                    seed_spec = child
                elif child.key == "random_seed":
                    random_spec = child
        if seed_spec is None or random_spec is None:
            for child in group.children:
                _mount_node(panel, child, widgets, options=options)
            return
        seed_w, seed_extra = widget_for_field_spec(seed_spec, options=options)
        random_w, random_extra = widget_for_field_spec(random_spec, options=options)
        widgets[seed_spec.key] = (seed_w, seed_extra, seed_spec)
        widgets[random_spec.key] = (random_w, random_extra, random_spec)
        panel.add_labeled_field(
            seed_spec.label,
            build_seed_and_random_seed_row(seed_w, random_w),
            stretch_control=False,
        )
        return

    if group.layout == "bool_run":
        for child in group.children:
            if not isinstance(child, FieldSpec):
                _mount_node(panel, child, widgets, options=options)
                continue
            widget, extra = widget_for_field_spec(child, options=options)
            widgets[child.key] = (widget, extra, child)
            panel.add_labeled_field(None, widget, stretch_control=False)
        return

    if group.layout == "labeled":
        row_w = QWidget()
        col = QVBoxLayout(row_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        for child in group.children:
            if isinstance(child, FieldSpec):
                widget, extra = widget_for_field_spec(child, options=options)
                widgets[child.key] = (widget, extra, child)
                if child.kind == "bool":
                    check_row = QHBoxLayout()
                    check_row.setContentsMargins(0, 0, 0, 0)
                    check_row.addWidget(widget, 0)
                    check_row.addStretch(1)
                    col.addLayout(check_row)
                else:
                    col.addWidget(widget)
            else:
                inner = QWidget()
                inner_col = QVBoxLayout(inner)
                inner_col.setContentsMargins(0, 0, 0, 0)
                _mount_subtree_into_layout(inner_col, child, widgets, options=options)
                col.addWidget(inner)
        panel.add_labeled_field(group.label, row_w)
        return

    if group.layout == "row":
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for child in group.children:
            if isinstance(child, FieldSpec):
                widget, extra = widget_for_field_spec(child, options=options)
                widgets[child.key] = (widget, extra, child)
                row.addWidget(widget)
            else:
                inner = QWidget()
                inner_lay = QVBoxLayout(inner)
                inner_lay.setContentsMargins(0, 0, 0, 0)
                _mount_subtree_into_layout(inner_lay, child, widgets, options=options)
                row.addWidget(inner)
        panel.add_labeled_field(group.label, row_w)
        return

    if group.layout == "column":
        for child in group.children:
            _mount_node(panel, child, widgets, options=options)
        return

    for child in group.children:
        _mount_node(panel, child, widgets, options=options)


def _mount_subtree_into_layout(
    layout: QVBoxLayout,
    node: FieldNode,
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    *,
    options: WidgetBuildOptions,
) -> None:
    if isinstance(node, FieldSpec):
        widget, extra = widget_for_field_spec(node, options=options)
        widgets[node.key] = (widget, extra, node)
        layout.addWidget(widget)
        return
    for child in node.children:
        if isinstance(child, FieldSpec):
            widget, extra = widget_for_field_spec(child, options=options)
            widgets[child.key] = (widget, extra, child)
            layout.addWidget(widget)
        else:
            inner = QWidget()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            _mount_subtree_into_layout(inner_lay, child, widgets, options=options)
            layout.addWidget(inner)


def _mount_leaf_spec(
    panel: ImageGenFieldsPanel,
    spec: FieldSpec,
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    *,
    options: WidgetBuildOptions,
) -> None:
    if spec.key in ("mflux_lora", "width", "height"):
        return
    widget, extra = widget_for_field_spec(spec, options=options)
    widgets[spec.key] = (widget, extra, spec)
    if spec.kind == "text" and spec.key == "negative_prompt":
        panel.add_labeled_field(
            spec.label,
            widget,
            copy_from_edit=widget,
        )
        return
    if spec.kind == "text" and spec.key == "prompt":
        panel.add_prompt_field(spec.label, widget)
        return
    if spec.kind == "bool":
        panel.add_labeled_field(None, widget, stretch_control=False)
        return
    stretch = spec.kind not in ("int_slider", "float_slider", "choice")
    panel.add_labeled_field(spec.label, widget, stretch_control=stretch)
