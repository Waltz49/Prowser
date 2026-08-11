#!/usr/bin/env python3
"""Multi-LoRA stack field: read-only summary combo + checkable popup (apply on dismiss)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QFontMetrics, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
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


def _click_target_widget(widget: QWidget) -> QWidget:
    """Prefer the nearest QAbstractButton ancestor for forwarded clicks."""
    target = widget
    while target is not None:
        if isinstance(target, QAbstractButton):
            return target
        target = target.parentWidget()
    return widget


def _forward_mouse_click(target: QWidget, source: QMouseEvent) -> None:
    """Deliver a full click (press + release) to *target* at *source*'s global pos."""
    local = QPointF(target.mapFromGlobal(source.globalPosition().toPoint()))
    global_pos = source.globalPosition()
    button = source.button()
    modifiers = source.modifiers()
    app = QApplication.instance()
    if app is None:
        return
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        global_pos,
        button,
        button,
        modifiers,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        local,
        global_pos,
        button,
        Qt.MouseButton.NoButton,
        modifiers,
    )
    app.sendEvent(target, press)
    app.sendEvent(target, release)


class _LoraPopupClickThroughFilter(QObject):
    """Dismiss the LoRA popup on outside click and forward the click inside the host dialog."""

    def __init__(
        self,
        popup: "LoraSelectionPopup",
        *,
        host_window: QWidget,
        anchor: QWidget,
    ) -> None:
        super().__init__(popup)
        self._popup = popup
        self._host_window = host_window
        self._anchor = anchor

    def _is_popup_or_anchor(self, widget: QWidget) -> bool:
        current: Optional[QWidget] = widget
        while current is not None:
            if current is self._popup or current is self._anchor:
                return True
            current = current.parentWidget()
        return False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._popup.isVisible():
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(event, QMouseEvent):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        global_pos = event.globalPosition().toPoint()
        if self._popup.frameGeometry().contains(global_pos):
            return False

        host = self._host_window
        if host is None or not host.isVisible():
            return False
        if not host.frameGeometry().contains(global_pos):
            return False

        self._popup._remove_click_through_filter()
        self._popup.hide()
        target = QApplication.widgetAt(global_pos)
        if target is not None and not self._is_popup_or_anchor(target):
            _forward_mouse_click(_click_target_widget(target), event)
        return True


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

        self._rows: List[Tuple[str, QAbstractButton, Optional[QLineEdit]]] = []
        self._fallback_scales: Dict[str, float] = {}
        self._empty_label: Optional[QLabel] = None
        self._single_select = False
        self._radio_group: Optional[QButtonGroup] = None
        self._preferred_width = _POPUP_MIN_WIDTH
        self._committed = False
        self._click_through_filter: Optional[_LoraPopupClickThroughFilter] = None
        self._anchor_widget: Optional[QWidget] = None
        self._host_window: Optional[QWidget] = None

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
            f"QFrame#imageGenLoraSelectionPopup QCheckBox,"
            f"QFrame#imageGenLoraSelectionPopup QRadioButton {{"
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
        self._remove_click_through_filter()
        if not self._committed:
            self._committed = True
            self.accepted.emit(self._selected_ids())
        super().hideEvent(event)

    def _install_click_through_filter(self) -> None:
        self._remove_click_through_filter()
        anchor = self._anchor_widget
        host = self._host_window
        if anchor is None or host is None:
            return
        filt = _LoraPopupClickThroughFilter(
            self,
            host_window=host,
            anchor=anchor,
        )
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(filt)
        self._click_through_filter = filt

    def _remove_click_through_filter(self) -> None:
        filt = self._click_through_filter
        if filt is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(filt)
        filt.deleteLater()
        self._click_through_filter = None

    def _clear_checks(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        self._fallback_scales.clear()
        self._empty_label = None
        self._single_select = False
        if self._radio_group is not None:
            self._radio_group.deleteLater()
            self._radio_group = None

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
        selector: QAbstractButton,
        weight_edit: Optional[QLineEdit],
    ) -> None:
        if weight_edit is None:
            return

        def _on_toggled(checked: bool) -> None:
            weight_edit.setEnabled(checked)

        selector.toggled.connect(_on_toggled)
        _on_toggled(selector.isChecked())

    def _row_height_estimate(self) -> int:
        if not self._rows:
            return _ROW_HEIGHT_ESTIMATE
        _, _, weight_edit = self._rows[0]
        if weight_edit is None:
            return _ROW_HEIGHT_ESTIMATE
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
        *,
        scale_overrides: Optional[Dict[str, float]] = None,
        single_select: bool = False,
    ) -> None:
        """choices: (label, preset_id); multi-select excludes 'none', single-select includes it."""
        from imagegen_plugins.lora_catalog import get_lora_entry

        self._clear_checks()
        self._single_select = single_select
        if single_select:
            selectable = list(choices)
            if not any(pid == "none" for _, pid in selectable):
                selectable = [("None", "none")] + selectable
        else:
            selectable = [(label, preset_id) for label, preset_id in choices if preset_id != "none"]
        if not selectable:
            self._add_empty_state_row()
            self._update_popup_layout_metrics(show_header=False)
            return

        overrides = scale_overrides or {}
        self._add_header_row()
        if single_select:
            active_id = "none"
            for pid in selected_ids:
                if pid and pid != "none":
                    active_id = pid
                    break
            selected = {active_id}
        else:
            selected = set(selected_ids)
        validator = QDoubleValidator(_SCALE_MIN, _SCALE_MAX, 2, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        row = 1
        for label, preset_id in selectable:
            entry = get_lora_entry(preset_id)
            catalog_scale = float(entry.scale) if entry is not None else 1.0
            if preset_id in overrides:
                try:
                    scale = float(overrides[preset_id])
                except (TypeError, ValueError):
                    scale = catalog_scale
                else:
                    scale = max(_SCALE_MIN, min(_SCALE_MAX, scale))
            else:
                scale = catalog_scale
            if preset_id != "none":
                self._fallback_scales[preset_id] = scale

            if single_select:
                selector: QAbstractButton = QRadioButton(str(label), self._checks_host)
                if self._radio_group is None:
                    self._radio_group = QButtonGroup(self)
                self._radio_group.addButton(selector)
            else:
                selector = QCheckBox(str(label), self._checks_host)
            selector.setChecked(preset_id in selected)

            weight_edit: Optional[QLineEdit] = None
            if preset_id != "none":
                weight_edit = QLineEdit(_format_scale(scale), self._checks_host)
                weight_edit.setObjectName("loraPopupWeightEdit")
                weight_edit.setFixedWidth(_WEIGHT_COL_WIDTH)
                weight_edit.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                weight_edit.setValidator(validator)
                weight_edit.setToolTip("LoRA weight (0.1–2.0)")
                self._wire_weight_row(preset_id, selector, weight_edit)

            self._grid.addWidget(selector, row, 0, 1, 2)
            if weight_edit is not None:
                self._grid.addWidget(weight_edit, row, 2)
            self._rows.append((preset_id, selector, weight_edit))
            row += 1

        self._update_popup_layout_metrics(show_header=True)

    def _measure_popup_width(self) -> int:
        fm = QFontMetrics(self.font())
        label_w = fm.horizontalAdvance("LoRA")
        if self._empty_label is not None:
            label_w = max(label_w, fm.horizontalAdvance(_EMPTY_LORAS_MESSAGE) // 2)
        for _preset_id, selector, weight_edit in self._rows:
            label_w = max(label_w, fm.horizontalAdvance(selector.text()))
            if weight_edit is not None:
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
        for preset_id, selector, _weight_edit in self._rows:
            if not selector.isChecked():
                continue
            if preset_id == "none":
                continue
            out.append(preset_id)
        return out

    def scales_by_id(self) -> Dict[str, float]:
        return {
            preset_id: _parse_scale_text(
                weight_edit.text(),
                fallback=self._fallback_scales.get(preset_id, 1.0),
            )
            for preset_id, _selector, weight_edit in self._rows
            if weight_edit is not None
        }

    def show_below(self, anchor: QWidget) -> None:
        self._committed = False
        self._anchor_widget = anchor
        self._host_window = anchor.window()
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
        self._install_click_through_filter()


class LoraSummaryCombo(QComboBox):
    """Summary combo; redirects native popup to multi-select in stack mode."""

    def showPopup(self) -> None:
        parent = self.parent()
        popup_mode = getattr(parent, "_popup_mode", False)
        if isinstance(parent, LoraStackField) and popup_mode:
            parent._open_popup()
            return
        super().showPopup()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        parent = self.parent()
        if (
            isinstance(parent, LoraStackField)
            and parent._popup_mode
            and self.isEnabled()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            parent._open_popup()
            event.accept()
            return
        super().mousePressEvent(event)


class LoraStackField(QWidget):
    """
    LoRA control for image-gen dialogs.

    FLUX/mflux/Klein/SDXL: read-only summary combo opens multi-select popup.
    SD15: read-only summary combo opens single-select popup (radio + weight).
    """

    stack_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._stack_mode = True
        self._popup_mode = True
        self._selected_ids: List[str] = []
        self._label_by_id: Dict[str, str] = {}
        self._choices: List[Tuple[str, str]] = []
        self._scale_overrides: Dict[str, float] = {}
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

        self._click_filter_widgets: Set[QWidget] = set()
        self._sync_combo_click_filters()

    def _combo_click_filter_widgets(self) -> List[QWidget]:
        combo = self.summary_combo
        return [combo, *combo.findChildren(QWidget)]

    def _sync_combo_click_filters(self) -> None:
        """Ensure left-clicks on combo text, arrow, and chrome all open the list."""
        try:
            from shiboken6 import isValid
        except ImportError:
            def isValid(obj):  # type: ignore[misc]
                return obj is not None

        targets = set()
        for widget in self._combo_click_filter_widgets():
            if isValid(widget):
                targets.add(widget)
        for widget in targets:
            if widget not in self._click_filter_widgets:
                widget.installEventFilter(self)
                self._click_filter_widgets.add(widget)
        for widget in list(self._click_filter_widgets):
            if widget in targets:
                continue
            self._click_filter_widgets.discard(widget)
            if isValid(widget):
                widget.removeEventFilter(self)

    def _is_combo_surface_widget(self, obj: Any) -> bool:
        if obj is self.summary_combo:
            return True
        if not isinstance(obj, QWidget):
            return False
        current: Optional[QWidget] = obj
        while current is not None:
            if current is self.summary_combo:
                return True
            current = current.parentWidget()
        return False

    @property
    def combo(self) -> QComboBox:
        """Alias for dialogs that reference ``_lora_combo``."""
        return self.summary_combo

    def is_stack_mode(self) -> bool:
        return self._stack_mode

    def is_popup_mode(self) -> bool:
        """True when the summary combo opens the custom LoRA popup (stack or single)."""
        return self._popup_mode

    def selected_ids(self) -> List[str]:
        if self._popup_mode:
            return list(self._selected_ids)
        pid = coerce_lora_preset_id(self.summary_combo.currentData())
        return [] if pid == "none" else [pid]

    def scales_by_id(self) -> Dict[str, float]:
        """Effective weights for selected LoRAs (session overrides, else catalog)."""
        from imagegen_plugins.lora_catalog import get_lora_entry

        out: Dict[str, float] = {}
        for preset_id in self.selected_ids():
            if preset_id in self._scale_overrides:
                out[preset_id] = float(self._scale_overrides[preset_id])
                continue
            entry = get_lora_entry(preset_id)
            out[preset_id] = float(entry.scale) if entry is not None else 1.0
        return out

    def apply_scale_overrides(self, scales: Dict[str, float]) -> None:
        """Merge EXIF/import weights; only provided ids are updated."""
        for preset_id, raw in (scales or {}).items():
            pid = str(preset_id or "").strip()
            if not pid or pid == "none":
                continue
            try:
                scale = float(raw)
            except (TypeError, ValueError):
                continue
            self._scale_overrides[pid] = max(_SCALE_MIN, min(_SCALE_MAX, scale))

    def set_stack(self, ids: List[str]) -> None:
        if self._popup_mode:
            if self._stack_mode:
                self._selected_ids = list(ids)
            else:
                preset = ids[0] if ids else "none"
                self._selected_ids = [] if preset == "none" else [preset]
            self._update_summary_text()
            return
        preset = ids[0] if ids else "none"
        idx = self.summary_combo.findData(preset)
        if idx >= 0:
            self.summary_combo.setCurrentIndex(idx)

    def _update_summary_text(self) -> None:
        if not self._popup_mode:
            return
        if self._stack_mode and len(self._selected_ids) > 1:
            text = lora_stack_summary_text(self._selected_ids, self._label_by_id)
        elif self._selected_ids:
            text = lora_stack_summary_text(self._selected_ids, self._label_by_id)
        else:
            text = "None"
        self.summary_combo.blockSignals(True)
        self.summary_combo.clear()
        self.summary_combo.addItem(text, self._selected_ids)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setText(text)
        self.summary_combo.blockSignals(False)
        finalize_lora_combo_display(self.summary_combo)
        self._sync_combo_click_filters()

    def _configure_stack_mode_combo(self) -> None:
        self.summary_combo.setEditable(True)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setCursor(Qt.CursorShape.PointingHandCursor)
            le.setFrame(False)
            le.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        combo_h = self.summary_combo.fontMetrics().height() + 10
        self.summary_combo.setFixedHeight(combo_h)
        self.summary_combo.setMaxVisibleItems(0)
        self._sync_combo_click_filters()

    def _configure_single_mode_combo(self) -> None:
        self.summary_combo.setEditable(False)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.summary_combo.setMinimumHeight(0)
        self.summary_combo.setMaximumHeight(16777215)
        self.summary_combo.setMaxVisibleItems(12)
        self._sync_combo_click_filters()

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
        self._popup_mode = (
            plugin_supports_lora(plugin) and host_id is not None
        )

        if not plugin_supports_lora(plugin):
            self._popup_mode = False
            self._configure_single_mode_combo()
            self.summary_combo.blockSignals(True)
            self.summary_combo.clear()
            self.summary_combo.addItem(LORA_UNSUPPORTED_LABEL, LORA_UNSUPPORTED_PRESET_ID)
            self.summary_combo.setCurrentIndex(0)
            self.summary_combo.setEnabled(False)
            self.summary_combo.blockSignals(False)
            self._selected_ids = []
            self._scale_overrides.clear()
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
            self._scale_overrides = {
                pid: scale
                for pid, scale in self._scale_overrides.items()
                if pid in valid_ids
            }
            self._update_summary_text()
            tip = (
                "Select one or more LoRAs (experimental stacking). "
                "Edit weights in the popup; click outside to apply, Esc to cancel."
            )
            self.summary_combo.setToolTip(tip)
            return

        if self._popup_mode:
            self._configure_stack_mode_combo()
            self.summary_combo.setEnabled(True)
            valid_ids = {pid for _, pid in choices}
            preset = coerce_lora_preset_id(
                current_preset_id if current_preset_id is not None else "none"
            )
            if preset in valid_ids and preset != "none":
                self._selected_ids = [preset]
            else:
                self._selected_ids = []
            self._scale_overrides = {
                pid: scale
                for pid, scale in self._scale_overrides.items()
                if pid in valid_ids
            }
            self._update_summary_text()
            tip = (
                "Select a LoRA. Edit weight in the popup; "
                "click outside to apply, Esc to cancel."
            )
            self.summary_combo.setToolTip(tip)
            return

        self._configure_single_mode_combo()
        populate_image_gen_lora_combo(
            self.summary_combo,
            plugin,
            current_preset_id=current_preset_id,
        )
        self._sync_combo_click_filters()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if not self._popup_mode or not self.summary_combo.isEnabled():
            return super().eventFilter(obj, event)
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().eventFilter(obj, event)
        if event.button() != Qt.MouseButton.LeftButton:
            return super().eventFilter(obj, event)
        if not self._is_combo_surface_widget(obj):
            return super().eventFilter(obj, event)
        self._open_popup()
        return True

    def _open_popup(self) -> None:
        if not self._popup_mode or not self.summary_combo.isEnabled():
            return
        if self._popup is None:
            self._popup = LoraSelectionPopup(self.window())
            self._popup.accepted.connect(self._on_popup_accepted)
            self._popup.rejected.connect(self._on_popup_rejected)
        if self._stack_mode:
            selectable = [(label, pid) for label, pid in self._choices if pid != "none"]
        else:
            selectable = list(self._choices)
        self._popup.set_choices(
            selectable,
            self._selected_ids,
            scale_overrides=self._scale_overrides,
            single_select=not self._stack_mode,
        )
        self._popup.show_below(self.summary_combo)

    def _on_popup_accepted(self, ids: List[str]) -> None:
        try:
            from shiboken6 import isValid

            if not isValid(self) or not isValid(self.summary_combo):
                return
        except ImportError:
            pass
        if self._popup is not None:
            scales = self._popup.scales_by_id()
            self._persist_scale_changes(scales)
            for preset_id, scale in scales.items():
                self._scale_overrides[preset_id] = float(scale)
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
