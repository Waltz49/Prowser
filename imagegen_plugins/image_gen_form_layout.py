#!/usr/bin/env python3
"""Stacked field layout for image-generation dialogs (labels above controls)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_fields import FieldSpec
from theme_service import get_active_theme

IMAGE_GEN_FIELD_GROUP_SPACING = 10
IMAGE_GEN_FIELD_LABEL_SPACING = 2
IMAGE_GEN_FIELD_INSET_H = 12
IMAGE_GEN_FIELD_INSET_V = 8
# Extra right inset so scroll clipping does not cut off control borders / focus rings.
IMAGE_GEN_FIELD_BORDER_PAD = 4
IMAGE_GEN_PROMPT_STYLE_PADDING_V = 10  # 5px top + 5px bottom in dialog stylesheet
IMAGE_GEN_PROMPT_STYLE_BORDER_V = 2  # 1px top + 1px bottom border
IMAGE_GEN_SEED_SPIN_MAX_WIDTH = 118


def image_gen_prompt_height_for_lines(line_count: int, font_metrics) -> int:
    """Min height for QPlainTextEdit prompt fields (text + padding + border)."""
    lines = max(1, int(line_count))
    return (
        font_metrics.lineSpacing() * lines
        + IMAGE_GEN_PROMPT_STYLE_PADDING_V
        + IMAGE_GEN_PROMPT_STYLE_BORDER_V
        + 2
    )


def wrap_image_gen_bordered_field(control: QWidget) -> QWidget:
    """Wrap a bordered control so layout does not clip its bottom/right edges."""
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, IMAGE_GEN_FIELD_BORDER_PAD)
    lay.setSpacing(0)
    lay.addWidget(control)
    host.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    return host
IMAGE_GEN_CHECKBOX_ROW_SPACING = 14
IMAGE_GEN_COLUMN_ROW_SPACING = 10
IMAGE_GEN_BELOW_PROMPT_SPACING = 8
IMAGE_GEN_SLIDER_TRACK_WIDTH = 200
IMAGE_GEN_SLIDER_ROW_SPACING = 8
IMAGE_GEN_FIELD_LABEL_OBJECT_NAME = "imageGenFieldLabel"


def configure_image_gen_slider_track(slider: QWidget) -> None:
    """Fixed-width slider track; value widget sits beside it on the left."""
    slider.setFixedWidth(IMAGE_GEN_SLIDER_TRACK_WIDTH)
    slider.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def wrap_image_gen_slider_row(slider: QWidget, value_widget: QWidget) -> QWidget:
    """Slider + spin/label row aligned left; slider does not stretch with panel width."""
    configure_image_gen_slider_track(slider)
    value_widget.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
    )
    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(IMAGE_GEN_SLIDER_ROW_SPACING)
    row.addWidget(slider, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(
        value_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    row_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return row_w


def make_image_gen_field_label(text: str, parent: Optional[QWidget] = None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(IMAGE_GEN_FIELD_LABEL_OBJECT_NAME)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return label


class ImageGenFieldsPanel:
    """Vertical form: model + full-width prompt, then controls with optional side buttons."""

    def __init__(self, parent: QWidget):
        self.widget = QWidget(parent)
        self._layout = QVBoxLayout(self.widget)
        self._layout.setContentsMargins(
            IMAGE_GEN_FIELD_INSET_H,
            IMAGE_GEN_FIELD_INSET_V,
            IMAGE_GEN_FIELD_INSET_H + IMAGE_GEN_FIELD_BORDER_PAD,
            IMAGE_GEN_FIELD_INSET_V,
        )
        self._layout.setSpacing(IMAGE_GEN_FIELD_GROUP_SPACING)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        self._prompt_group: Optional[QWidget] = None
        self._below_row = QWidget(self.widget)
        self._below_row.setObjectName("imageGenBelowPromptRow")
        self._below_layout = QHBoxLayout(self._below_row)
        self._below_layout.setContentsMargins(0, 0, 0, 0)
        self._below_layout.setSpacing(IMAGE_GEN_BELOW_PROMPT_SPACING)
        self._below_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        self._controls_host = QWidget(self._below_row)
        self._controls_layout = QVBoxLayout(self._controls_host)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(IMAGE_GEN_FIELD_GROUP_SPACING)
        self._controls_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._below_layout.addWidget(self._controls_host, 1)

        self._side_btn_host: Optional[QWidget] = None
        self._below_row_in_layout = False

    def count(self) -> int:
        return self._layout.count() + self._controls_layout.count()

    def _ensure_below_row_in_layout(self) -> None:
        if not self._below_row_in_layout:
            self._layout.addWidget(self._below_row)
            self._below_row_in_layout = True

    def attach_side_button_column(self, host: Optional[QWidget]) -> None:
        """Place a vertical button stack to the right of controls (below the prompt)."""
        if host is None:
            if self._side_btn_host is not None:
                self._below_layout.removeWidget(self._side_btn_host)
                self._side_btn_host.hide()
                self._side_btn_host = None
            return
        self._ensure_below_row_in_layout()
        if self._side_btn_host is not None and self._side_btn_host is not host:
            self._below_layout.removeWidget(self._side_btn_host)
        self._side_btn_host = host
        host.show()
        if self._below_layout.indexOf(host) < 0:
            self._below_layout.addWidget(
                host, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )

    def clear(self, *, keep: int = 0) -> None:
        if self._prompt_group is not None:
            self._layout.removeWidget(self._prompt_group)
            self._prompt_group.deleteLater()
            self._prompt_group = None

        while self._controls_layout.count():
            item = self._controls_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    while sub.count():
                        sub_item = sub.takeAt(0)
                        sub_widget = sub_item.widget()
                        if sub_widget is not None:
                            sub_widget.deleteLater()

        if self._side_btn_host is not None:
            self._below_layout.removeWidget(self._side_btn_host)
            self._side_btn_host.hide()

        if self._below_row_in_layout:
            self._layout.removeWidget(self._below_row)
            self._below_row_in_layout = False

        while self._layout.count() > keep:
            item = self._layout.takeAt(keep)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_group(self, group: QWidget) -> None:
        self._ensure_below_row_in_layout()
        compact = (
            group.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Maximum
        )
        if not compact:
            group.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._controls_layout.addWidget(group)
        else:
            self._controls_layout.addWidget(
                group,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )

    def add_prompt_field(
        self,
        label_text: str,
        control: QWidget,
    ) -> None:
        """Full-width prompt editor above the controls / side-button row."""
        group = QWidget(self.widget)
        col = QVBoxLayout(group)
        col.setContentsMargins(1, 0, IMAGE_GEN_FIELD_BORDER_PAD, 0)
        col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
        col.addWidget(make_image_gen_field_label(label_text, group), 0)
        control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        if control.minimumHeight() < 1:
            fm = control.fontMetrics()
            control.setMinimumHeight(image_gen_prompt_height_for_lines(4, fm))
        col.addWidget(wrap_image_gen_bordered_field(control), 0)
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._prompt_group = group
        insert_at = self._layout.count()
        if self._below_row_in_layout:
            insert_at = max(0, self._layout.indexOf(self._below_row))
        self._layout.insertWidget(insert_at, group)

    def add_labeled_field(
        self,
        label_text: Optional[str],
        control: QWidget,
        *,
        stretch_control: bool = True,
        to_outer: bool = False,
    ) -> None:
        parent = self.widget if to_outer else self._controls_host
        group = QWidget(parent)
        col = QVBoxLayout(group)
        edge_pad = IMAGE_GEN_FIELD_BORDER_PAD if to_outer else 0
        col.setContentsMargins(1, 0, edge_pad, 0)
        col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
        if label_text:
            col.addWidget(make_image_gen_field_label(label_text, group), 0)
        if stretch_control:
            control.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            col.addWidget(control, 0)
            group.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        else:
            col.addWidget(
                control,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
            group.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
            )
        if to_outer:
            self._layout.addWidget(group)
        else:
            self.add_group(group)

    def add_columns(
        self,
        columns: List[Tuple[str, QWidget]],
    ) -> None:
        row = QWidget(self._controls_host)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(IMAGE_GEN_COLUMN_ROW_SPACING)
        for label_text, control in columns:
            cell = QWidget(row)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
            cell_layout.addWidget(make_image_gen_field_label(label_text, cell), 0)
            if control.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Maximum:
                cell_layout.addWidget(
                    control,
                    0,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
            else:
                control.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                cell_layout.addWidget(control, 0)
            row_layout.addWidget(cell, 1)
        self.add_group(row)

    def add_checkbox_row(self, checkboxes: List[QWidget]) -> None:
        if not checkboxes:
            return
        row = QWidget(self._controls_host)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(IMAGE_GEN_CHECKBOX_ROW_SPACING)
        for checkbox in checkboxes:
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
            )
            row_layout.addWidget(checkbox, 0)
        row_layout.addStretch(1)
        self.add_group(row)


def mount_image_gen_fields_in_scroll(
    scroll: QScrollArea,
    panel: ImageGenFieldsPanel,
) -> None:
    """Mount fields in a scroll area with padding so borders are not clipped."""
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(panel.widget)
    panel.widget.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
    )


def image_gen_field_label_stylesheet() -> str:
    t = get_active_theme()
    muted = getattr(t, "text_disabled_hex", t.dialog_text_color_hex)
    return f"""
    #imageGenDialog QLabel#{IMAGE_GEN_FIELD_LABEL_OBJECT_NAME} {{
        color: {muted};
        font-size: 11px;
        padding-top: 4px;
        margin: 0px;
    }}
    #imageGenDialog QSpinBox {{
        min-height: 22px;
        max-height: 26px;
        padding: 1px 4px;
    }}
    #imageGenDialog QSlider::groove:horizontal {{
        height: 4px;
        border-radius: 2px;
    }}
    #imageGenDialog QSlider::handle:horizontal {{
        width: 14px;
        margin: -5px 0;
    }}
    #imageGenDialog QCheckBox {{
        spacing: 6px;
        min-width: 0px;
    }}
    #imageGenDialog QComboBox {{
        min-height: 22px;
        padding: 2px 8px;
    }}
    #imageGenDialog QPlainTextEdit,
    #imageGenDialog QLineEdit {{
        padding: 5px 8px;
    }}
    """


FieldWidgetBuilder = Callable[[FieldSpec], Tuple[QWidget, Any]]
FieldHook = Callable[[FieldSpec, QWidget, Any, ImageGenFieldsPanel], bool]


def populate_image_gen_field_rows(
    panel: ImageGenFieldsPanel,
    specs: List[FieldSpec],
    widgets: Dict[str, Any],
    widget_for_spec: FieldWidgetBuilder,
    *,
    combine_seed_random: bool,
    build_seed_and_random_seed_row: Callable[[QWidget, QWidget], QWidget],
    prepare_prompt_actions: Optional[
        Callable[[], Optional[List[QPushButton]]]
    ] = None,
    field_hook: Optional[FieldHook] = None,
) -> None:
    """Populate a fields panel from pipeline specs with compact grouping rules."""
    del prepare_prompt_actions  # side column is filled via repopulate_image_gen_side_buttons
    index = 0
    while index < len(specs):
        spec = specs[index]
        if combine_seed_random and spec.key == "random_seed":
            index += 1
            continue

        if spec.kind == "bool":
            while index < len(specs) and specs[index].kind == "bool":
                current = specs[index]
                widget, extra = widget_for_spec(current)
                widgets[current.key] = (widget, extra, current)
                panel.add_labeled_field(None, widget, stretch_control=False)
                index += 1
            continue

        if (
            spec.key == "width"
            and index + 1 < len(specs)
            and specs[index + 1].key == "height"
        ):
            width_spec = spec
            height_spec = specs[index + 1]
            width_widget, width_extra = widget_for_spec(width_spec)
            height_widget, height_extra = widget_for_spec(height_spec)
            widgets[width_spec.key] = (width_widget, width_extra, width_spec)
            widgets[height_spec.key] = (height_widget, height_extra, height_spec)
            panel.add_columns(
                [
                    (width_spec.label, width_widget),
                    (height_spec.label, height_widget),
                ]
            )
            index += 2
            continue

        if (
            spec.key == "mflux_lora"
            and index + 1 < len(specs)
            and specs[index + 1].key == "mflux_quantize"
        ):
            lora_spec = spec
            quant_spec = specs[index + 1]
            lora_widget, lora_extra = widget_for_spec(lora_spec)
            quant_widget, quant_extra = widget_for_spec(quant_spec)
            widgets[lora_spec.key] = (lora_widget, lora_extra, lora_spec)
            widgets[quant_spec.key] = (quant_widget, quant_extra, quant_spec)
            panel.add_columns(
                [
                    (lora_spec.label, lora_widget),
                    (quant_spec.label, quant_widget),
                ]
            )
            index += 2
            continue

        widget, extra = widget_for_spec(spec)
        widgets[spec.key] = (widget, extra, spec)

        if field_hook is not None and field_hook(spec, widget, extra, panel):
            index += 1
            continue

        if spec.kind == "text" and spec.key == "prompt":
            panel.add_prompt_field(spec.label, widget)
            index += 1
            continue

        if combine_seed_random and spec.key == "seed":
            random_spec = next(s for s in specs if s.key == "random_seed")
            random_widget, random_extra = widget_for_spec(random_spec)
            widgets[random_spec.key] = (random_widget, random_extra, random_spec)
            panel.add_labeled_field(
                spec.label,
                build_seed_and_random_seed_row(widget, random_widget),
                stretch_control=False,
            )
            index += 1
            continue

        stretch = spec.kind not in ("int_slider", "float_slider")
        if spec.kind == "text":
            panel.add_labeled_field(spec.label, widget, stretch_control=stretch)
        elif spec.kind == "seed":
            panel.add_labeled_field(spec.label, widget, stretch_control=stretch)
        else:
            panel.add_labeled_field(spec.label, widget, stretch_control=stretch)
        index += 1
