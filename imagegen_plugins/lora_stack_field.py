#!/usr/bin/env python3
"""Multi-LoRA stack field: read-only summary combo + checkable popup (apply on dismiss)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator, QFontMetrics, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListView,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from combo_popup_utils import position_popup_below_anchor

from imagegen_plugins.image_gen_model_selector import (
    _LORA_COMBO_OBJECT_NAME,
    configure_lora_combo,
    finalize_lora_combo_display,
    plugin_supports_lora,
    populate_image_gen_lora_combo,
)
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15, HOST_SDXL
from imagegen_plugins.mflux_lora_presets import (
    LORA_UNSUPPORTED_LABEL,
    LORA_UNSUPPORTED_PRESET_ID,
    coerce_lora_preset_id,
)
from theme.theme_service import get_active_theme

_POPUP_MAX_VISIBLE_ROWS = 10
_ROW_HEIGHT_ESTIMATE = 28
_HEADER_ROW_HEIGHT = 22
_POPUP_PADDING = 8
_POPUP_MIN_WIDTH = 280
_POPUP_WIDTH_SLACK = 16
_WEIGHT_COL_WIDTH = 52
_SCALE_MIN = 0.1
_SCALE_MAX = 2.0
_EMPTY_LORAS_MESSAGE = (
    "No LoRAs available. Enable and download in Settings → LoRA."
)


def _format_scale(value: float) -> str:
    return f"{float(value):g}"


def _parse_scale_text(text: str, *, fallback: float) -> float:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return fallback
    return max(_SCALE_MIN, min(_SCALE_MAX, value))


def lora_stack_summary_text(
    selected_ids: List[str],
    label_by_id: Dict[str, str],
    *,
    max_chars: int = 48,
) -> str:
    """Human-readable summary for the closed combo."""
    if not selected_ids:
        return "None"
    if len(selected_ids) == 1:
        name = label_by_id.get(selected_ids[0], selected_ids[0])
        if len(name) > max_chars:
            return f"{name[: max_chars - 1]}…"
        return name
    return "Multiple LoRAs"


class LoraSelectionPopup(QFrame):
    """Checkable LoRA list anchored below the summary combo; dismiss applies, Esc cancels."""

    accepted = Signal(list)
    rejected = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("imageGenLoraSelectionPopup")
        self._apply_theme()
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 0, 1, 1)
        root.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._checks_host = QWidget()
        self._grid = QGridLayout(self._checks_host)
        self._grid.setContentsMargins(
            _POPUP_PADDING, _POPUP_PADDING, _POPUP_PADDING, _POPUP_PADDING
        )
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnStretch(1, 1)
        self._scroll.setWidget(self._checks_host)
        root.addWidget(self._scroll, 0)

        self._rows: List[Tuple[str, QCheckBox, QLineEdit]] = []
        self._fallback_scales: Dict[str, float] = {}
        self._empty_label: Optional[QLabel] = None
        self._preferred_width = _POPUP_MIN_WIDTH
        self._committed = False

    def _apply_theme(self) -> None:
        t = get_active_theme()
        bg = t.dialog_input_background_hex
        border = t.border_default_hex
        text = t.dialog_text_color_hex
        self.setStyleSheet(
            f"QFrame#imageGenLoraSelectionPopup {{"
            f" background-color: {bg};"
            f" color: {text};"
            f" border: 1px solid {border};"
            f" border-top: none;"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QScrollArea {{"
            f" background-color: {bg};"
            f" border: none;"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QCheckBox {{"
            f" color: {text};"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QLabel#loraPopupHeader {{"
            f" color: {text};"
            f" font-size: 11px;"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QLabel#loraPopupEmpty {{"
            f" color: {text};"
            f" font-size: 12px;"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QLineEdit#loraPopupWeightEdit {{"
            f" background-color: {bg};"
            f" color: {text};"
            f" border: 1px solid {border};"
            f" border-radius: 3px;"
            f" padding: 2px 4px;"
            f"}}"
            f"QFrame#imageGenLoraSelectionPopup QLineEdit#loraPopupWeightEdit:disabled {{"
            f" background-color: {bg};"
            f" color: {text};"
            f" border: 1px solid transparent;"
            f" opacity: 0.45;"
            f"}}"
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._committed = True
            self.rejected.emit()
            self.hide()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        if not self._committed:
            self._committed = True
            self.accepted.emit(self._selected_ids())
        super().hideEvent(event)

    def _clear_checks(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        self._fallback_scales.clear()
        self._empty_label = None

    def _add_empty_state_row(self) -> None:
        label = QLabel(_EMPTY_LORAS_MESSAGE, self._checks_host)
        label.setObjectName("loraPopupEmpty")
        label.setWordWrap(True)
        label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._grid.addWidget(label, 0, 0, 1, 3)
        self._empty_label = label

    def _add_header_row(self) -> None:
        name_hdr = QLabel("LoRA", self._checks_host)
        name_hdr.setObjectName("loraPopupHeader")
        weight_hdr = QLabel("Wt", self._checks_host)
        weight_hdr.setObjectName("loraPopupHeader")
        weight_hdr.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._grid.addWidget(name_hdr, 0, 0, 1, 2)
        self._grid.addWidget(weight_hdr, 0, 2)

    def _wire_weight_row(
        self,
        preset_id: str,
        cb: QCheckBox,
        weight_edit: QLineEdit,
    ) -> None:
        def _on_toggled(checked: bool) -> None:
            weight_edit.setEnabled(checked)

        cb.toggled.connect(_on_toggled)
        _on_toggled(cb.isChecked())

    def _row_height_estimate(self) -> int:
        if not self._rows:
            return _ROW_HEIGHT_ESTIMATE
        _, _, weight_edit = self._rows[0]
        return max(_ROW_HEIGHT_ESTIMATE, weight_edit.sizeHint().height() + 2)

    def _update_popup_layout_metrics(self, *, show_header: bool) -> None:
        row_h = self._row_height_estimate()
        if self._empty_label is not None:
            self._empty_label.setFixedWidth(max(_POPUP_MIN_WIDTH - _POPUP_PADDING * 2 - 4, 200))
            msg_h = self._empty_label.heightForWidth(self._empty_label.width())
            scroll_h = max(msg_h, row_h) + _POPUP_PADDING * 2
        else:
            visible_data_rows = min(len(self._rows), _POPUP_MAX_VISIBLE_ROWS)
            header_h = _HEADER_ROW_HEIGHT if show_header else 0
            scroll_h = header_h + visible_data_rows * row_h + _POPUP_PADDING * 2
        self._scroll.setFixedHeight(scroll_h)
        self._preferred_width = self._measure_popup_width()
        self._checks_host.setMinimumWidth(self._preferred_width - 2)

    def set_choices(
        self,
        choices: List[Tuple[str, str]],
        selected_ids: List[str],
    ) -> None:
        """choices: (label, preset_id); excludes 'none'."""
        from imagegen_plugins.lora_catalog import get_lora_entry

        self._clear_checks()
        selectable = [(label, preset_id) for label, preset_id in choices if preset_id != "none"]
        if not selectable:
            self._add_empty_state_row()
            self._update_popup_layout_metrics(show_header=False)
            return

        self._add_header_row()
        selected = set(selected_ids)
        validator = QDoubleValidator(_SCALE_MIN, _SCALE_MAX, 2, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        row = 1
        for label, preset_id in selectable:
            entry = get_lora_entry(preset_id)
            scale = float(entry.scale) if entry is not None else 1.0
            self._fallback_scales[preset_id] = scale

            cb = QCheckBox(str(label), self._checks_host)
            cb.setChecked(preset_id in selected)
            weight_edit = QLineEdit(_format_scale(scale), self._checks_host)
            weight_edit.setObjectName("loraPopupWeightEdit")
            weight_edit.setFixedWidth(_WEIGHT_COL_WIDTH)
            weight_edit.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            weight_edit.setValidator(validator)
            weight_edit.setToolTip("LoRA weight (0.1–2.0)")
            self._wire_weight_row(preset_id, cb, weight_edit)

            self._grid.addWidget(cb, row, 0, 1, 2)
            self._grid.addWidget(weight_edit, row, 2)
            self._rows.append((preset_id, cb, weight_edit))
            row += 1

        self._update_popup_layout_metrics(show_header=True)

    def _measure_popup_width(self) -> int:
        fm = QFontMetrics(self.font())
        label_w = fm.horizontalAdvance("LoRA")
        if self._empty_label is not None:
            label_w = max(label_w, fm.horizontalAdvance(_EMPTY_LORAS_MESSAGE) // 2)
        for _preset_id, cb, weight_edit in self._rows:
            label_w = max(label_w, fm.horizontalAdvance(cb.text()))
            label_w = max(label_w, weight_edit.sizeHint().width())

        style = self.style()
        indicator = 18
        if style is not None:
            indicator = style.pixelMetric(
                QStyle.PixelMetric.PM_IndicatorWidth,
                None,
                self,
            )
        margins = self._grid.contentsMargins()
        width = (
            margins.left()
            + margins.right()
            + 2  # frame border
            + indicator
            + 8  # checkbox gap
            + label_w
            + self._grid.horizontalSpacing()
            + _WEIGHT_COL_WIDTH
            + _POPUP_WIDTH_SLACK
        )
        return max(_POPUP_MIN_WIDTH, width)

    def _selected_ids(self) -> List[str]:
        out: List[str] = []
        for preset_id, cb, _weight_edit in self._rows:
            if cb.isChecked():
                out.append(preset_id)
        return out

    def scales_by_id(self) -> Dict[str, float]:
        return {
            preset_id: _parse_scale_text(
                weight_edit.text(),
                fallback=self._fallback_scales.get(preset_id, 1.0),
            )
            for preset_id, _cb, weight_edit in self._rows
        }

    def show_below(self, anchor: QWidget) -> None:
        self._committed = False
        width = max(
            anchor.width(),
            getattr(self, "_preferred_width", _POPUP_MIN_WIDTH),
        )
        screen = anchor.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = min(width, avail.width() - 16)
        width = max(width, _POPUP_MIN_WIDTH)
        self.setFixedWidth(width)
        self.setMaximumHeight(16777215)
        self.setMinimumHeight(0)
        self.adjustSize()
        layout = self.layout()
        if layout is not None:
            self.setFixedHeight(layout.sizeHint().height())
        position_popup_below_anchor(self, anchor)
        self.show()
        self.raise_()
        self.activateWindow()


class LoraSummaryCombo(QComboBox):
    """Summary combo; redirects native popup to multi-select in stack mode."""

    def showPopup(self) -> None:
        parent = self.parent()
        stack_mode = getattr(parent, "_stack_mode", False)
        if isinstance(parent, LoraStackField) and stack_mode:
            parent._open_popup()
            return
        super().showPopup()


class LoraStackField(QWidget):
    """
    LoRA control for image-gen dialogs.

    FLUX/mflux/Klein: read-only summary combo opens multi-select popup.
    SD15: standard single-select combo (unchanged behavior).
    """

    stack_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._stack_mode = True
        self._selected_ids: List[str] = []
        self._label_by_id: Dict[str, str] = {}
        self._choices: List[Tuple[str, str]] = []
        self._popup: Optional[LoraSelectionPopup] = None
        self._plugin: Optional[ImageGenModelPlugin] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.summary_combo = LoraSummaryCombo(self)
        configure_lora_combo(self.summary_combo)
        self.summary_combo.setObjectName(_LORA_COMBO_OBJECT_NAME)
        self.summary_combo.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.summary_combo)

        self.summary_combo.installEventFilter(self)
        self._line_edit_filter_installed = False

    @property
    def combo(self) -> QComboBox:
        """Alias for dialogs that reference ``_lora_combo``."""
        return self.summary_combo

    def is_stack_mode(self) -> bool:
        return self._stack_mode

    def selected_ids(self) -> List[str]:
        if not self._stack_mode:
            pid = coerce_lora_preset_id(self.summary_combo.currentData())
            return [] if pid == "none" else [pid]
        return list(self._selected_ids)

    def set_stack(self, ids: List[str]) -> None:
        if not self._stack_mode:
            preset = ids[0] if ids else "none"
            idx = self.summary_combo.findData(preset)
            if idx >= 0:
                self.summary_combo.setCurrentIndex(idx)
            return
        self._selected_ids = list(ids)
        self._update_summary_text()

    def _update_summary_text(self) -> None:
        if not self._stack_mode:
            return
        text = lora_stack_summary_text(self._selected_ids, self._label_by_id)
        self.summary_combo.blockSignals(True)
        self.summary_combo.clear()
        self.summary_combo.addItem(text, self._selected_ids)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setText(text)
        self.summary_combo.blockSignals(False)
        finalize_lora_combo_display(self.summary_combo)

    def _configure_stack_mode_combo(self) -> None:
        self.summary_combo.setEditable(True)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setCursor(Qt.CursorShape.PointingHandCursor)
            le.setFrame(False)
            if not self._line_edit_filter_installed:
                le.installEventFilter(self)
                self._line_edit_filter_installed = True
        combo_h = self.summary_combo.fontMetrics().height() + 10
        self.summary_combo.setFixedHeight(combo_h)
        self.summary_combo.setMaxVisibleItems(0)

    def _configure_single_mode_combo(self) -> None:
        self.summary_combo.setEditable(False)
        self.summary_combo.setMinimumHeight(0)
        self.summary_combo.setMaximumHeight(16777215)
        self.summary_combo.setMaxVisibleItems(12)

    def populate(
        self,
        plugin: Optional[ImageGenModelPlugin],
        *,
        current_stack: Optional[List[str]] = None,
        current_preset_id: Any = None,
    ) -> None:
        from config import get_config
        from imagegen_plugins.lora_catalog import lora_choices_for_plugin

        self._plugin = plugin
        host_id = getattr(plugin, "lora_host_id", None) if plugin else None
        use_stack = (
            plugin_supports_lora(plugin)
            and host_id is not None
            and host_id not in (HOST_SD15,)
        )
        self._stack_mode = use_stack

        if not plugin_supports_lora(plugin):
            self._configure_single_mode_combo()
            self.summary_combo.blockSignals(True)
            self.summary_combo.clear()
            self.summary_combo.addItem(LORA_UNSUPPORTED_LABEL, LORA_UNSUPPORTED_PRESET_ID)
            self.summary_combo.setCurrentIndex(0)
            self.summary_combo.setEnabled(False)
            self.summary_combo.blockSignals(False)
            self._selected_ids = []
            return

        settings = get_config().load_settings()
        choices = lora_choices_for_plugin(plugin, settings) if plugin else []
        self._choices = list(choices)
        self._label_by_id = {pid: str(label) for label, pid in choices if pid != "none"}

        if use_stack:
            self._configure_stack_mode_combo()
            self.summary_combo.setEnabled(True)
            valid_ids = {pid for _, pid in choices}
            stack = [pid for pid in (current_stack or []) if pid in valid_ids]
            if not stack and current_preset_id is not None:
                pid = coerce_lora_preset_id(current_preset_id)
                if pid in valid_ids and pid != "none":
                    stack = [pid]
            self._selected_ids = stack
            self._update_summary_text()
            tip = (
                "Select one or more LoRAs (experimental stacking). "
                "Edit weights in the popup; click outside to apply, Esc to cancel."
            )
            self.summary_combo.setToolTip(tip)
            return

        self._configure_single_mode_combo()
        populate_image_gen_lora_combo(
            self.summary_combo,
            plugin,
            current_preset_id=current_preset_id,
        )

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if not self._stack_mode or not self.summary_combo.isEnabled():
            return super().eventFilter(obj, event)
        if event.type() != event.Type.MouseButtonPress:
            return super().eventFilter(obj, event)
        if event.button() != Qt.MouseButton.LeftButton:
            return super().eventFilter(obj, event)
        le = self.summary_combo.lineEdit()
        if obj is self.summary_combo or (le is not None and obj is le):
            self._open_popup()
            return True
        return super().eventFilter(obj, event)

    def _open_popup(self) -> None:
        if not self._stack_mode or not self.summary_combo.isEnabled():
            return
        if self._popup is None:
            self._popup = LoraSelectionPopup(self.window())
            self._popup.accepted.connect(self._on_popup_accepted)
            self._popup.rejected.connect(self._on_popup_rejected)
        selectable = [(label, pid) for label, pid in self._choices if pid != "none"]
        self._popup.set_choices(selectable, self._selected_ids)
        self._popup.show_below(self.summary_combo)

    def _on_popup_accepted(self, ids: List[str]) -> None:
        if self._popup is not None:
            self._persist_scale_changes(self._popup.scales_by_id())
        self._selected_ids = list(ids)
        self._update_summary_text()
        self.stack_changed.emit()

    def _on_popup_rejected(self) -> None:
        pass

    def _persist_scale_changes(self, scales: Dict[str, float]) -> None:
        from config import get_config
        from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata
        from imagegen_plugins.lora_catalog import get_lora_entry

        settings = get_config().load_settings()
        for lora_id, new_scale in scales.items():
            entry = get_lora_entry(lora_id, settings)
            if entry is None:
                continue
            if abs(float(entry.scale) - new_scale) < 1e-6:
                continue
            try:
                update_lora_entry_metadata(
                    lora_id,
                    display_name=entry.display_name,
                    trigger_word=entry.trigger_word,
                    scale=new_scale,
                    comment=entry.comment,
                )
            except Exception:
                pass
