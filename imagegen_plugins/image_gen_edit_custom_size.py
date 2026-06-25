#!/usr/bin/env python3
"""Custom Size group for image-generation dialogs (create, edit, expand)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_field_blocks import model_reset_default
from imagegen_plugins.image_gen_form_layout import (
    ImageGenFieldsPanel,
    create_image_gen_dim_helper_icon_button,
    make_image_gen_field_label,
    wrap_image_gen_bordered_field,
    wrap_image_gen_field_control_indent,
)
from imagegen_plugins.image_gen_parameter_panel import (
    WidgetBuildOptions,
    widget_for_field_spec,
)
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.imagegen_control_tooltips import (
    apply_dim_helper_tooltips,
    apply_field_control_tooltips,
)


def migrate_edit_size_saved_values(values: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy screen_size_experimental to use_custom_size + screen dimensions."""
    out = dict(values)
    if out.pop("screen_size_experimental", False):
        out["use_custom_size"] = True
        if "width" not in out or "height" not in out:
            from imagegen_plugins.edit_aspect_pad import screen_size_edit_target_dimensions

            w, h = screen_size_edit_target_dimensions()
            out.setdefault("width", w)
            out.setdefault("height", h)
    return out


def custom_size_width_height_specs(
    values: Dict[str, Any],
    *,
    width_min: int,
    height_min: int,
    dim_max: int,
    dim_step: int,
    model_defaults: Optional[Dict[str, Any]] = None,
) -> Tuple[FieldSpec, FieldSpec]:
    width_reset = int(model_reset_default(model_defaults, "width", 1024))
    height_reset = int(model_reset_default(model_defaults, "height", 1024))
    return (
        FieldSpec(
            key="width",
            label="Width",
            kind="int_slider",
            default=int(values.get("width", width_reset)),
            min_value=width_min,
            max_value=dim_max,
            step=dim_step,
            reset_default=width_reset,
        ),
        FieldSpec(
            key="height",
            label="Height",
            kind="int_slider",
            default=int(values.get("height", height_reset)),
            min_value=height_min,
            max_value=dim_max,
            step=dim_step,
            reset_default=height_reset,
        ),
    )


def edit_custom_size_field_specs(
    values: Dict[str, Any],
    *,
    width_min: int,
    height_min: int,
    dim_max: int,
    dim_step: int,
    model_defaults: Optional[Dict[str, Any]] = None,
) -> Tuple[FieldSpec, FieldSpec, FieldSpec]:
    width_spec, height_spec = custom_size_width_height_specs(
        values,
        width_min=width_min,
        height_min=height_min,
        dim_max=dim_max,
        dim_step=dim_step,
        model_defaults=model_defaults,
    )
    return (
        FieldSpec(
            key="use_custom_size",
            label="Use Custom Size",
            kind="bool",
            default=bool(values.get("use_custom_size", False)),
            bool_label_override="Use Custom Size",
        ),
        width_spec,
        height_spec,
    )


def _add_labeled_slider_row(
    parent: QWidget,
    layout: QVBoxLayout,
    label_text: str,
    control: QWidget,
) -> None:
    row = QWidget(parent)
    col = QVBoxLayout(row)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    col.addWidget(make_image_gen_field_label(label_text, row), 0)
    col.addWidget(
        wrap_image_gen_field_control_indent(
            wrap_image_gen_bordered_field(control), row
        ),
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    row.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    layout.addWidget(
        row,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
    )


def _build_dim_helper_icon_buttons(dialog: Any, parent: QWidget) -> Tuple[QWidget, ...]:
    screen_btn = create_image_gen_dim_helper_icon_button(
        "dim_screen_icon.png",
        hover_icon_name="dim_screen_icon_hover.png",
        parent=parent,
    )
    screen_btn.clicked.connect(dialog._on_screen_size_dims)
    square_btn = create_image_gen_dim_helper_icon_button(
        "dim_square_icon.png",
        hover_icon_name="dim_square_icon_hover.png",
        parent=parent,
    )
    square_btn.clicked.connect(dialog._on_square_dims)
    reverse_btn = create_image_gen_dim_helper_icon_button(
        "dim_reverse_icon.png",
        hover_icon_name="dim_reverse_icon_hover.png",
        parent=parent,
    )
    reverse_btn.clicked.connect(dialog._on_reverse_dims)
    apply_dim_helper_tooltips(
        screen_btn=screen_btn,
        square_btn=square_btn,
        reverse_btn=reverse_btn,
    )
    return  square_btn, reverse_btn,screen_btn


def _build_custom_size_group_box(
    dialog: Any,
    *,
    width_spec: FieldSpec,
    height_spec: FieldSpec,
    width_widget: QWidget,
    height_widget: QWidget,
    aspect_cb: QCheckBox,
    values: Dict[str, Any],
) -> QGroupBox:
    group_box = QGroupBox("Custom Size")
    group_layout = QVBoxLayout(group_box)
    group_layout.setContentsMargins(8, 8, 8, 8)
    group_layout.setSpacing(8)
    _add_labeled_slider_row(group_box, group_layout, width_spec.label, width_widget)
    _add_labeled_slider_row(group_box, group_layout, height_spec.label, height_widget)

    controls_row = QWidget(group_box)
    controls_layout = QHBoxLayout(controls_row)
    controls_layout.setContentsMargins(0, 0, 0, 0)
    controls_layout.setSpacing(8)
    controls_layout.addWidget(
        aspect_cb, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    controls_layout.addStretch(1)

    btn_row = QWidget(controls_row)
    btn_layout = QHBoxLayout(btn_row)
    btn_layout.setContentsMargins(0, 0, 0, 0)
    btn_layout.setSpacing(4)
    for btn in _build_dim_helper_icon_buttons(dialog, btn_row):
        btn_layout.addWidget(btn)
    controls_layout.addWidget(
        btn_row, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    controls_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    group_layout.addWidget(controls_row)

    aspect_cb.setChecked(bool(values.get("aspect_ratio_lock", False)))
    apply_dim_helper_tooltips(aspect_checkbox=aspect_cb)
    aspect_cb.toggled.connect(dialog._on_aspect_lock_toggled)
    dialog._aspect_checkbox = aspect_cb
    group_box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return group_box


def _remove_existing_custom_size_section(
    dialog: Any,
    panel: ImageGenFieldsPanel,
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    specs: List[FieldSpec],
    *,
    optional: bool,
) -> None:
    existing = getattr(dialog, "_custom_size_outer", None)
    if existing is None:
        return
    if existing in panel._control_groups:
        panel._control_groups.remove(existing)
    existing.deleteLater()
    remove_keys = ("width", "height")
    if optional:
        remove_keys = ("use_custom_size", "width", "height")
    for key in remove_keys:
        widgets.pop(key, None)
    specs[:] = [s for s in specs if s.key not in remove_keys]


def mount_custom_size_section(
    dialog: Any,
    panel: ImageGenFieldsPanel,
    values: Dict[str, Any],
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    specs: List[FieldSpec],
    *,
    effective_max_side: int,
    pipeline_id: str,
    build_options: Optional[WidgetBuildOptions] = None,
    optional: bool = False,
) -> None:
    """Mount Custom Size controls; optional=True adds Use Custom Size checkbox (edit)."""
    _remove_existing_custom_size_section(
        dialog, panel, widgets, specs, optional=optional
    )

    mode = get_pipeline(pipeline_id)
    opts = build_options or WidgetBuildOptions()
    use_widget = None
    use_spec = None

    if optional:
        use_spec, width_spec, height_spec = edit_custom_size_field_specs(
            values,
            width_min=mode.width_min,
            height_min=mode.height_min,
            dim_max=effective_max_side,
            dim_step=mode.dim_step,
            model_defaults=getattr(dialog.plugin, "model_defaults", None),
        )
        use_widget, use_extra = widget_for_field_spec(use_spec, options=opts)
        apply_field_control_tooltips(use_spec, use_widget)
    else:
        width_spec, height_spec = custom_size_width_height_specs(
            values,
            width_min=mode.width_min,
            height_min=mode.height_min,
            dim_max=effective_max_side,
            dim_step=mode.dim_step,
            model_defaults=getattr(dialog.plugin, "model_defaults", None),
        )

    width_widget, width_extra = widget_for_field_spec(width_spec, options=opts)
    apply_field_control_tooltips(width_spec, width_widget)
    height_widget, height_extra = widget_for_field_spec(height_spec, options=opts)

    aspect_cb = QCheckBox("Aspect Ratio Lock")
    group_box = _build_custom_size_group_box(
        dialog,
        width_spec=width_spec,
        height_spec=height_spec,
        width_widget=width_widget,
        height_widget=height_widget,
        aspect_cb=aspect_cb,
        values=values,
    )
    outer = QWidget(panel._controls_host)
    outer.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    outer_col = QVBoxLayout(outer)
    outer_col.setContentsMargins(0, 0, 0, 0)
    outer_col.setSpacing(8)

    if optional and use_widget is not None:
        outer_col.addWidget(
            use_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        use_checked = bool(use_spec.default)
        group_box.setVisible(use_checked)

        def _on_use_custom_size_toggled(checked: bool) -> None:
            group_box.setVisible(checked)
            if getattr(dialog, "_panel_mode", False):
                dialog.state_changed.emit()

        use_widget.toggled.connect(_on_use_custom_size_toggled)
    else:
        outer_col.addWidget(
            make_image_gen_field_label("Custom size", outer),
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    outer_col.addWidget(wrap_image_gen_field_control_indent(group_box, outer))

    panel.prepend_control_group(outer)
    dialog._custom_size_outer = outer

    widgets[width_spec.key] = (width_widget, width_extra, width_spec)
    widgets[height_spec.key] = (height_widget, height_extra, height_spec)
    specs[:0] = [width_spec, height_spec]
    if optional and use_spec is not None and use_widget is not None:
        widgets[use_spec.key] = (use_widget, use_extra, use_spec)
        specs[:0] = [use_spec]


def mount_edit_custom_size_section(
    dialog: Any,
    panel: ImageGenFieldsPanel,
    values: Dict[str, Any],
    widgets: Dict[str, Tuple[QWidget, Any, FieldSpec]],
    specs: List[FieldSpec],
    *,
    effective_max_side: int,
    pipeline_id: str,
    build_options: Optional[WidgetBuildOptions] = None,
) -> None:
    """Mount Use Custom Size + Custom Size group; merge widgets/specs on dialog."""
    mount_custom_size_section(
        dialog,
        panel,
        values,
        widgets,
        specs,
        effective_max_side=effective_max_side,
        pipeline_id=pipeline_id,
        build_options=build_options,
        optional=True,
    )
