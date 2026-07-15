#!/usr/bin/env python3
"""Prefix/postfix text rules for chat and image-generation prompts."""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_prompt_config import (
    load_prefix_postfix_config,
    save_prefix_postfix_config,
)
from chat_plugins.chat_prompt_grammar import (
    add_chat_prompt_button_row,
    apply_chat_prompt_save_format_to_widget,
)
from chat_plugins.chat_ui_common import (
    chat_library_edit_button_stylesheet,
    chat_library_trash_button_stylesheet,
    chat_prompt_edit_stylesheet,
    install_cmd_enter_accept,
)
from settings.widgets.macos_preferences import MacToggleSwitch
from utils import get_button_style, get_dialog_shell_stylesheet

ICON_BTN_SIZE = 22
_COL_TEXT = 4
_COL_EDIT = 5
_COL_DELETE = 6
_COL_ACTIVE = 7


def _display_text(text: str) -> str:
    return (text or "").replace("\n", "\\n")


@dataclass
class PrefixPostfixEntry:
    id: str
    text: str
    use_with_text: bool = False
    use_with_images: bool = False
    is_prefix: bool = False
    is_postfix: bool = False
    active: bool = True


@dataclass
class PrefixPostfixStore:
    entries: list[PrefixPostfixEntry] = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def load(cls) -> PrefixPostfixStore:
        config = load_prefix_postfix_config()
        entries: list[PrefixPostfixEntry] = []
        for item in config.get("entries", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            entries.append(
                PrefixPostfixEntry(
                    id=str(item["id"]),
                    text=str(item.get("text", "")),
                    use_with_text=bool(item.get("use_with_text")),
                    use_with_images=bool(item.get("use_with_images")),
                    is_prefix=bool(item.get("is_prefix")),
                    is_postfix=bool(item.get("is_postfix")),
                    active=bool(item.get("active", True)),
                )
            )
        enabled = config.get("enabled")
        if not isinstance(enabled, bool):
            enabled = True
        return cls(entries=entries, enabled=enabled)

    def save(self) -> None:
        config = load_prefix_postfix_config()
        config["enabled"] = self.enabled
        config["entries"] = [
            {
                "id": entry.id,
                "text": entry.text,
                "use_with_text": entry.use_with_text,
                "use_with_images": entry.use_with_images,
                "is_prefix": entry.is_prefix,
                "is_postfix": entry.is_postfix,
                "active": entry.active,
            }
            for entry in self.entries
        ]
        save_prefix_postfix_config(config)

    def find_entry(self, entry_id: str) -> PrefixPostfixEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None


def apply_prefix_postfix_rules(text: str, *, for_images: bool) -> str:
    """Apply enabled prefix/postfix entries in list order."""
    store = PrefixPostfixStore.load()
    if not store.enabled:
        return text
    prefixes: list[str] = []
    postfixes: list[str] = []
    for entry in store.entries:
        if not entry.active:
            continue
        if for_images:
            if not entry.use_with_images:
                continue
        elif not entry.use_with_text:
            continue
        if entry.is_prefix and entry.text:
            prefixes.append(entry.text)
        if entry.is_postfix and entry.text:
            postfixes.append(entry.text)
    if not prefixes and not postfixes:
        return text
    return "".join(prefixes) + text + "".join(postfixes)


class _PrefixPostfixRowWidgets:
    __slots__ = (
        "entry_id",
        "use_text_cb",
        "use_images_cb",
        "prefix_cb",
        "postfix_cb",
        "text_label",
        "active_switch",
    )

    def __init__(
        self,
        entry_id: str,
        use_text_cb: QCheckBox,
        use_images_cb: QCheckBox,
        prefix_cb: QCheckBox,
        postfix_cb: QCheckBox,
        text_label: QLabel,
        active_switch: MacToggleSwitch,
    ) -> None:
        self.entry_id = entry_id
        self.use_text_cb = use_text_cb
        self.use_images_cb = use_images_cb
        self.prefix_cb = prefix_cb
        self.postfix_cb = postfix_cb
        self.text_label = text_label
        self.active_switch = active_switch


def _center_widget(widget: QWidget) -> QWidget:
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch()
    row.addWidget(widget)
    row.addStretch()
    return wrapper


def _center_checkbox(checkbox: QCheckBox) -> QWidget:
    return _center_widget(checkbox)


class PrefixPostfixTextEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Edit text",
        text: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Text to add:"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setMinimumHeight(160)
        self.text_edit.setStyleSheet(chat_prompt_edit_stylesheet())
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_chat_prompt_button_row(self, self.text_edit, layout, buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        install_cmd_enter_accept(self, self.text_edit)

    def accept(self) -> None:
        apply_chat_prompt_save_format_to_widget(self.text_edit)
        super().accept()

    def text_value(self) -> str:
        return self.text_edit.toPlainText()


class PrefixPostfixDeleteConfirmDialog(QDialog):
    def __init__(self, entry: PrefixPostfixEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete text")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Delete this prefix/postfix text?"))

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(entry.text or "(empty)")
        preview.setMinimumHeight(100)
        preview.setMaximumHeight(220)
        preview.setStyleSheet(chat_prompt_edit_stylesheet())
        layout.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())


class ChatPrefixPostfixDialog(QDialog):
    def __init__(self, store: PrefixPostfixStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Prefix and Postfix text")
        self.setMinimumSize(640, 360)
        self._store = deepcopy(store)
        self._row_widgets: list[_PrefixPostfixRowWidgets] = []

        layout = QVBoxLayout(self)
        instr_row = QHBoxLayout()
        instr_row.addWidget(
            QLabel("Prefix and postfix rules applied when sending chat or image prompts:")
        )
        instr_row.addStretch(1)
        self._enable_switch = MacToggleSwitch()
        self._enable_switch.setChecked(self._store.enabled)
        self._enable_switch.setToolTip("Enable prefix and postfix rules")
        self._enable_switch.toggled.connect(self._on_enabled_toggled)
        instr_row.addWidget(self._enable_switch)
        layout.addLayout(instr_row)

        self._table = QTableWidget(0, 8, self)
        self._table.setHorizontalHeaderLabels(
            ["T", "I", "<", ">", "Text to add", "", "", ""]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_TEXT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_EDIT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_DELETE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_ACTIVE, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 36)
        self._table.setColumnWidth(1, 36)
        self._table.setColumnWidth(2, 36)
        self._table.setColumnWidth(3, 36)
        self._table.setColumnWidth(_COL_EDIT, ICON_BTN_SIZE + 8)
        self._table.setColumnWidth(_COL_DELETE, ICON_BTN_SIZE + 8)
        self._table.setColumnWidth(_COL_ACTIVE, 48)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setFrameShape(QFrame.Shape.NoFrame)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.verticalHeader().setDefaultSectionSize(ICON_BTN_SIZE + 8)
        self._table_opacity = QGraphicsOpacityEffect(self._table)
        self._table.setGraphicsEffect(self._table_opacity)
        layout.addWidget(self._table, stretch=1)

        add_btn = QPushButton("Add…")
        add_btn.clicked.connect(self._add_entry)
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(
            get_dialog_shell_stylesheet()
            + get_button_style()
            + """
            QTableWidget {
                border: none;
                gridline-color: transparent;
            }
            QHeaderView::section {
                border: none;
                padding: 2px 4px;
            }
            """
        )
        self._rebuild_table()
        self._update_table_dim_state()

    def result_store(self) -> PrefixPostfixStore:
        return self._store

    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._store.enabled = enabled
        self._update_table_dim_state()

    def _update_table_dim_state(self) -> None:
        dimmed = not self._store.enabled
        self._table_opacity.setOpacity(0.35 if dimmed else 1.0)
        self._table.setEnabled(not dimmed)

    def _update_row_checkbox_states(self, row: _PrefixPostfixRowWidgets) -> None:
        """Grey row checkboxes when the per-entry toggle is off."""
        active = row.active_switch.isChecked()
        for checkbox in (
            row.use_text_cb,
            row.use_images_cb,
            row.prefix_cb,
            row.postfix_cb,
        ):
            checkbox.setEnabled(active)

    def _rebuild_table(self) -> None:
        self._row_widgets.clear()
        self._table.setRowCount(len(self._store.entries))
        for row, entry in enumerate(self._store.entries):
            use_text_cb = QCheckBox()
            use_text_cb.setChecked(entry.use_with_text)
            use_text_cb.setToolTip("Use with text")
            self._table.setCellWidget(row, 0, _center_checkbox(use_text_cb))

            use_images_cb = QCheckBox()
            use_images_cb.setChecked(entry.use_with_images)
            use_images_cb.setToolTip("Use with images")
            self._table.setCellWidget(row, 1, _center_checkbox(use_images_cb))

            prefix_cb = QCheckBox()
            prefix_cb.setChecked(entry.is_prefix)
            prefix_cb.setToolTip("Prefix")
            self._table.setCellWidget(row, 2, _center_checkbox(prefix_cb))

            postfix_cb = QCheckBox()
            postfix_cb.setChecked(entry.is_postfix)
            postfix_cb.setToolTip("Postfix")
            self._table.setCellWidget(row, 3, _center_checkbox(postfix_cb))

            text_label = QLabel(_display_text(entry.text))
            text_label.setWordWrap(False)
            text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_label.setToolTip(entry.text or "")
            text_host = QWidget()
            text_layout = QHBoxLayout(text_host)
            text_layout.setContentsMargins(4, 0, 4, 0)
            text_layout.addWidget(text_label, stretch=1)
            self._table.setCellWidget(row, _COL_TEXT, text_host)

            edit_btn = QPushButton()
            edit_btn.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
            edit_btn.setToolTip("Edit")
            edit_btn.setStyleSheet(chat_library_edit_button_stylesheet())
            edit_btn.clicked.connect(
                lambda _=False, eid=entry.id: self._edit_entry(eid)
            )
            self._table.setCellWidget(row, _COL_EDIT, _center_widget(edit_btn))

            del_btn = QPushButton()
            del_btn.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
            del_btn.setToolTip("Delete")
            del_btn.setStyleSheet(chat_library_trash_button_stylesheet())
            del_btn.clicked.connect(
                lambda _=False, eid=entry.id: self._delete_entry(eid)
            )
            self._table.setCellWidget(row, _COL_DELETE, _center_widget(del_btn))

            active_switch = MacToggleSwitch()
            active_switch.setChecked(entry.active)
            active_switch.setToolTip(
                "Use this text when on.\n"
                "When off, T / I / < / > settings are ignored."
            )
            self._table.setCellWidget(row, _COL_ACTIVE, _center_widget(active_switch))

            row_widgets = _PrefixPostfixRowWidgets(
                entry.id,
                use_text_cb,
                use_images_cb,
                prefix_cb,
                postfix_cb,
                text_label,
                active_switch,
            )
            active_switch.toggled.connect(
                lambda _checked, rw=row_widgets: self._update_row_checkbox_states(rw)
            )
            self._update_row_checkbox_states(row_widgets)
            self._row_widgets.append(row_widgets)

        self._update_table_dim_state()

    def _sync_row_to_entry(self, row: _PrefixPostfixRowWidgets) -> None:
        entry = self._store.find_entry(row.entry_id)
        if entry is None:
            return
        entry.use_with_text = row.use_text_cb.isChecked()
        entry.use_with_images = row.use_images_cb.isChecked()
        entry.is_prefix = row.prefix_cb.isChecked()
        entry.is_postfix = row.postfix_cb.isChecked()
        entry.active = row.active_switch.isChecked()

    def _sync_all_rows_to_store(self) -> None:
        for row in self._row_widgets:
            self._sync_row_to_entry(row)

    def _add_entry(self) -> None:
        self._sync_all_rows_to_store()
        dlg = PrefixPostfixTextEditDialog(self, title="New text")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        entry = PrefixPostfixEntry(id=uuid.uuid4().hex[:10], text=dlg.text_value())
        self._store.entries.append(entry)
        self._rebuild_table()

    def _edit_entry(self, entry_id: str) -> None:
        self._sync_all_rows_to_store()
        entry = self._store.find_entry(entry_id)
        if entry is None:
            return
        dlg = PrefixPostfixTextEditDialog(
            self,
            title="Edit text",
            text=entry.text,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        entry.text = dlg.text_value()
        self._rebuild_table()

    def _delete_entry(self, entry_id: str) -> None:
        self._sync_all_rows_to_store()
        entry = self._store.find_entry(entry_id)
        if entry is None:
            return
        dlg = PrefixPostfixDeleteConfirmDialog(entry, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._store.entries = [e for e in self._store.entries if e.id != entry_id]
        self._rebuild_table()

    def accept(self) -> None:
        self._sync_all_rows_to_store()
        self._store.enabled = self._enable_switch.isChecked()
        super().accept()


def run_chat_prefix_postfix_library(
    parent: QWidget | None,
) -> PrefixPostfixStore | None:
    """Show prefix/postfix library. Returns store on OK, else None."""
    store = PrefixPostfixStore.load()
    dlg = ChatPrefixPostfixDialog(store, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    result = dlg.result_store()
    result.save()
    return result
