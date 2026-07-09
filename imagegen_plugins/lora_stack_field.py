#!/usr/bin/env python3
"""Multi-LoRA stack field: read-only summary combo + checkable popup (apply on dismiss)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_model_selector import (
    _LORA_COMBO_OBJECT_NAME,
    configure_lora_combo,
    finalize_lora_combo_display,
    plugin_supports_lora,
    populate_image_gen_lora_combo,
)
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.lora_host_registry import HOST_SD15
from imagegen_plugins.mflux_lora_presets import (
    LORA_UNSUPPORTED_LABEL,
    LORA_UNSUPPORTED_PRESET_ID,
    coerce_lora_preset_id,
)
from theme.theme_service import get_active_theme

_POPUP_MAX_VISIBLE_ROWS = 10
_ROW_HEIGHT_ESTIMATE = 26
_POPUP_PADDING = 8


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
        self._checks_layout = QVBoxLayout(self._checks_host)
        self._checks_layout.setContentsMargins(
            _POPUP_PADDING, _POPUP_PADDING, _POPUP_PADDING, _POPUP_PADDING
        )
        self._checks_layout.setSpacing(4)
        self._scroll.setWidget(self._checks_host)
        root.addWidget(self._scroll, 1)

        self._checkboxes: List[Tuple[str, QCheckBox]] = []
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
        while self._checks_layout.count():
            item = self._checks_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._checkboxes.clear()

    def set_choices(
        self,
        choices: List[Tuple[str, str]],
        selected_ids: List[str],
    ) -> None:
        """choices: (label, preset_id); excludes 'none'."""
        self._clear_checks()
        selected = set(selected_ids)
        for label, preset_id in choices:
            if preset_id == "none":
                continue
            cb = QCheckBox(str(label), self._checks_host)
            cb.setChecked(preset_id in selected)
            self._checks_layout.addWidget(cb)
            self._checkboxes.append((preset_id, cb))
        row_count = max(1, len(self._checkboxes))
        visible_rows = min(row_count, _POPUP_MAX_VISIBLE_ROWS)
        scroll_h = visible_rows * _ROW_HEIGHT_ESTIMATE + _POPUP_PADDING * 2
        self._scroll.setFixedHeight(scroll_h)

    def _selected_ids(self) -> List[str]:
        out: List[str] = []
        for preset_id, cb in self._checkboxes:
            if cb.isChecked():
                out.append(preset_id)
        return out

    def show_below(self, anchor: QWidget) -> None:
        self._committed = False
        self.adjustSize()
        global_pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        self.setFixedWidth(max(anchor.width(), 280))
        self.move(global_pos)
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

    def _configure_stack_mode_combo(self) -> None:
        self.summary_combo.setEditable(True)
        le = self.summary_combo.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setCursor(Qt.CursorShape.PointingHandCursor)
            if not self._line_edit_filter_installed:
                le.installEventFilter(self)
                self._line_edit_filter_installed = True
        self.summary_combo.setMaxVisibleItems(0)

    def _configure_single_mode_combo(self) -> None:
        self.summary_combo.setEditable(False)
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
            plugin_supports_lora(plugin) and host_id is not None and host_id != HOST_SD15
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
                "Click to open the list; click outside to apply, Esc to cancel."
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
        self._selected_ids = list(ids)
        self._update_summary_text()
        self.stack_changed.emit()

    def _on_popup_rejected(self) -> None:
        pass
