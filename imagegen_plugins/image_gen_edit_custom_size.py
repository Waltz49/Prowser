#!/usr/bin/env python3
"""Custom Size group for image-generation dialogs (create, edit, expand)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_field_blocks import model_reset_default
from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_DIM_HELPER_BTN_SIZE,
    IMAGE_GEN_FIELD_LABEL_OBJECT_NAME,
    IMAGE_GEN_FIELD_RESET_BTN_SIZE,
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

_USE_CUSTOM_SIZE_BASE_LABEL = "Use Custom Size"
_CUSTOM_SIZE_BASE_LABEL = "Custom Size"
_COLLAPSED_ARROW = "\u25b6"  # ▶
_EXPANDED_ARROW = "\u25bc"  # ▼
_COLLAPSE_ARROW_FONT_PX = 13


class _CustomSizeCollapseHeader(QWidget):
    """Collapse/expand header compatible with bool field collection (isChecked/setChecked)."""

    toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None, *, expanded: bool = False):
        super().__init__(parent)
        self._expanded = bool(expanded)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(4)
        self._arrow = QLabel(self)
        arrow_font = self._arrow.font()
        arrow_font.setPixelSize(_COLLAPSE_ARROW_FONT_PX)
        self._arrow.setFont(arrow_font)
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._arrow.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._title = QLabel(self)
        self._title.setObjectName(IMAGE_GEN_FIELD_LABEL_OBJECT_NAME)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._title.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        row.addWidget(
            self._arrow,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        row.addWidget(
            self._title,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._apply_expanded_state()

    def isChecked(self) -> bool:
        return self._expanded

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._expanded == checked:
            return
        self._expanded = checked
        self._apply_expanded_state()
        self.toggled.emit(checked)

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)

    def set_title_text(self, text: str) -> None:
        self._title.setText(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._expanded)
            event.accept()
            return
        super().mousePressEvent(event)

    def _apply_expanded_state(self) -> None:
        self._arrow.setText(
            _EXPANDED_ARROW if self._expanded else _COLLAPSED_ARROW
        )


def _image_pixel_size(image_path: str) -> Optional[Tuple[int, int]]:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as img:
            return int(img.size[0]), int(img.size[1])
    except Exception:
        return None


def _edit_first_source_path(dialog: Any) -> Optional[str]:
    paths = getattr(dialog, "_source_paths", None) or []
    if paths:
        return str(paths[0])
    path = getattr(dialog, "source_path", None)
    return str(path) if path else None


def _first_source_pixel_size(dialog: Any) -> Optional[Tuple[int, int]]:
    path = _edit_first_source_path(dialog)
    if not path:
        return None
    size = _image_pixel_size(path)
    if size is None:
        return None
    w, h = size
    if w <= 0 or h <= 0:
        return None
    return w, h


def _custom_size_header_text(
    *,
    base_label: str,
    expanded: bool,
    size: Optional[Tuple[int, int]],
) -> str:
    if expanded or size is None:
        return base_label
    w, h = size
    return f"{base_label} ( Current: {w} x {h} )"


def _int_slider_spin(widget: QWidget):
    inner = widget.layout()
    return inner.itemAt(1).widget()


def _slider_pixel_size(
    width_widget: QWidget, height_widget: QWidget
) -> Optional[Tuple[int, int]]:
    try:
        w = int(_int_slider_spin(width_widget).value())
        h = int(_int_slider_spin(height_widget).value())
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return w, h


def _refresh_custom_size_collapse_header(
    header: QWidget,
    *,
    base_label: str,
    expanded: bool,
    size: Optional[Tuple[int, int]],
) -> None:
    if not isinstance(header, _CustomSizeCollapseHeader):
        return
    header.set_title_text(
        _custom_size_header_text(
            base_label=base_label,
            expanded=expanded,
            size=size,
        )
    )


def _connect_custom_size_dim_refresh(
    width_widget: QWidget,
    height_widget: QWidget,
    refresh: Any,
) -> None:
    for widget in (width_widget, height_widget):
        inner = widget.layout()
        if inner is None:
            continue
        for index in range(inner.count()):
            child = inner.itemAt(index).widget()
            if child is not None and hasattr(child, "valueChanged"):
                child.valueChanged.connect(lambda _v: refresh())


def _refresh_use_custom_size_header(dialog: Any, use_widget: QWidget) -> None:
    _refresh_custom_size_collapse_header(
        use_widget,
        base_label=_USE_CUSTOM_SIZE_BASE_LABEL,
        expanded=use_widget.isChecked() if isinstance(use_widget, _CustomSizeCollapseHeader) else False,
        size=_first_source_pixel_size(dialog),
    )


def _refresh_slider_custom_size_header(
    header: QWidget,
    width_widget: QWidget,
    height_widget: QWidget,
) -> None:
    expanded = header.isChecked() if isinstance(header, _CustomSizeCollapseHeader) else True
    _refresh_custom_size_collapse_header(
        header,
        base_label=_CUSTOM_SIZE_BASE_LABEL,
        expanded=expanded,
        size=_slider_pixel_size(width_widget, height_widget),
    )


def _mount_collapsible_custom_size_section(
    dialog: Any,
    panel: ImageGenFieldsPanel,
    *,
    collapse_header: _CustomSizeCollapseHeader,
    group_box: QGroupBox,
    expanded: bool,
    on_toggled: Any,
) -> QWidget:
    section = QWidget(panel._controls_host)
    section.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    section_col = QVBoxLayout(section)
    section_col.setContentsMargins(0, 0, 0, 0)
    section_col.setSpacing(8)
    section_col.addWidget(
        collapse_header,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    group_body = wrap_image_gen_field_control_indent(group_box, section)
    group_body.setVisible(expanded)
    section_col.addWidget(group_body, 0)

    def _on_collapsed_toggled(checked: bool) -> None:
        group_body.setVisible(checked)
        on_toggled(checked)
        if getattr(dialog, "_panel_mode", False):
            dialog.state_changed.emit()

    collapse_header.toggled.connect(_on_collapsed_toggled)
    panel.prepend_full_width_control_header(section)
    dialog._custom_size_header = section
    return section


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


def _compact_custom_size_dim_slider_row(row: QWidget) -> None:
    """Shrink slider/spin/reset row height inside the Custom Size group."""
    row.setObjectName("imageGenCustomSizeDimRow")
    compact = IMAGE_GEN_DIM_HELPER_BTN_SIZE
    icon_px = max(
        10,
        round(16 * compact / IMAGE_GEN_FIELD_RESET_BTN_SIZE),
    )
    for btn in row.findChildren(QPushButton):
        if btn.objectName() == "imageGenFieldResetBtn":
            btn.setFixedSize(compact, compact)
            btn.setIconSize(QSize(icon_px, icon_px))


def _add_labeled_slider_row(
    parent: QWidget,
    layout: QVBoxLayout,
    label_text: str,
    control: QWidget,
) -> None:
    _compact_custom_size_dim_slider_row(control)
    row = QWidget(parent)
    hrow = QHBoxLayout(row)
    hrow.setContentsMargins(0, 0, 0, 0)
    hrow.setSpacing(6)
    label = make_image_gen_field_label(label_text, row)
    label.setWordWrap(False)
    hrow.addWidget(
        label,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    hrow.addWidget(
        wrap_image_gen_bordered_field(control, bottom_pad=0),
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
    import_btn = create_image_gen_dim_helper_icon_button(
        "import_icon.png",
        hover_icon_name="import_icon_hover.png",
        parent=parent,
    )
    import_btn.clicked.connect(dialog._on_import_size)
    apply_dim_helper_tooltips(
        screen_btn=screen_btn,
        square_btn=square_btn,
        reverse_btn=reverse_btn,
        import_btn=import_btn,
    )
    return square_btn, reverse_btn, screen_btn, import_btn


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
    group_box.setObjectName("imageGenCustomSizeGroup")
    group_layout = QVBoxLayout(group_box)
    group_layout.setContentsMargins(6, 2, 6, 4)
    group_layout.setSpacing(0)
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
    group_layout.addSpacing(4)
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
    existing_header = getattr(dialog, "_custom_size_header", None)
    if existing_header is not None:
        if existing_header in panel._full_width_control_headers:
            panel._full_width_control_headers.remove(existing_header)
        existing_header.deleteLater()
        dialog._custom_size_header = None
    existing = getattr(dialog, "_custom_size_outer", None)
    if existing is not None:
        if existing in panel._control_groups:
            panel._control_groups.remove(existing)
        existing.deleteLater()
        dialog._custom_size_outer = None
    if existing_header is None and existing is None:
        return
    dialog._refresh_use_custom_size_label = None
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
    """Mount Custom Size controls in a full-width collapsible section."""
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

    if optional and use_spec is not None:
        use_checked = bool(use_spec.default)
        use_widget = _CustomSizeCollapseHeader(
            panel._controls_host, expanded=use_checked
        )
        from imagegen_plugins.imagegen_control_tooltips import field_tooltip

        tip = field_tooltip(use_spec)
        if tip:
            use_widget.setToolTip(tip)
        use_extra = None

        def _on_edit_custom_size_toggled(checked: bool) -> None:
            _refresh_use_custom_size_header(dialog, use_widget)

        _mount_collapsible_custom_size_section(
            dialog,
            panel,
            collapse_header=use_widget,
            group_box=group_box,
            expanded=use_checked,
            on_toggled=_on_edit_custom_size_toggled,
        )
        _refresh_use_custom_size_header(dialog, use_widget)
        dialog._refresh_use_custom_size_label = (
            lambda: _refresh_use_custom_size_header(dialog, use_widget)
        )
    else:
        collapse_header = _CustomSizeCollapseHeader(
            panel._controls_host, expanded=True
        )

        def _on_create_custom_size_toggled(checked: bool) -> None:
            _refresh_slider_custom_size_header(
                collapse_header, width_widget, height_widget
            )

        _mount_collapsible_custom_size_section(
            dialog,
            panel,
            collapse_header=collapse_header,
            group_box=group_box,
            expanded=True,
            on_toggled=_on_create_custom_size_toggled,
        )
        _refresh_slider_custom_size_header(
            collapse_header, width_widget, height_widget
        )
        dialog._refresh_use_custom_size_label = (
            lambda: _refresh_slider_custom_size_header(
                collapse_header, width_widget, height_widget
            )
        )
        _connect_custom_size_dim_refresh(
            width_widget,
            height_widget,
            dialog._refresh_use_custom_size_label,
        )

    panel.reflow_controls()

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
    """Mount collapse header + Custom Size group; merge widgets/specs on dialog."""
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
