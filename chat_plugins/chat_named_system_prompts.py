#!/usr/bin/env python3
"""Named system prompt library for the chat pane."""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import CHAT_DEFAULTS, get_config
from theme.theme_base import asset_path
from utils import get_button_style, get_dialog_shell_stylesheet

SYSTEM_DEFAULT_ID = "__system_default__"
ICON_BTN_SIZE = 22


@dataclass
class ChatPromptEntry:
    id: str
    name: str
    text: str


@dataclass
class ChatPromptStore:
    active_id: str | None = None
    prompts: list[ChatPromptEntry] = field(default_factory=list)

    @classmethod
    def load(cls) -> ChatPromptStore:
        settings = get_config().load_settings()
        raw_prompts = settings.get("chat_named_system_prompts")
        prompts: list[ChatPromptEntry] = []
        if isinstance(raw_prompts, list):
            for item in raw_prompts:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                prompts.append(
                    ChatPromptEntry(
                        id=str(item["id"]),
                        name=str(item.get("name", "Untitled")),
                        text=str(item.get("text", "")),
                    )
                )
        active_id = settings.get("chat_active_named_prompt_id")
        if active_id in (None, "", SYSTEM_DEFAULT_ID):
            active_id = None
        else:
            active_id = str(active_id)
            if not any(p.id == active_id for p in prompts):
                active_id = None
        return cls(active_id=active_id, prompts=prompts)

    def save(self) -> None:
        get_config().update_settings(
            {
                "chat_named_system_prompts": [
                    {"id": p.id, "name": p.name, "text": p.text}
                    for p in self.prompts
                ],
                "chat_active_named_prompt_id": self.active_id or "",
            }
        )

    def find_prompt(self, prompt_id: str) -> ChatPromptEntry | None:
        for entry in self.prompts:
            if entry.id == prompt_id:
                return entry
        return None

    def active_prompt_text(self) -> str:
        if not self.active_id or self.active_id == SYSTEM_DEFAULT_ID:
            return str(CHAT_DEFAULTS["chat_system_prompt"])
        for entry in self.prompts:
            if entry.id == self.active_id:
                return entry.text
        return str(CHAT_DEFAULTS["chat_system_prompt"])


def _icon_button_stylesheet(icon_name: str, *, hover_icon_name: str | None = None) -> str:
    icon_url = f"url({asset_path(icon_name)})"
    if hover_icon_name:
        hover_url = f"url({asset_path(hover_icon_name)})"
    else:
        hover_url = icon_url.replace(".png", "_hover.png")
    sz = ICON_BTN_SIZE
    return f"""
        QPushButton {{
            background-color: #f4f4f4;
            border: 1px solid #c8c8c8;
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:hover {{
            background-color: #e8e8e8;
            border: 1px solid #b0b0b0;
            image: {hover_url};
        }}
        QPushButton:pressed {{
            background-color: #d0d0d0;
        }}
    """


def _edit_button_stylesheet() -> str:
    return _icon_button_stylesheet("edit_icon.png", hover_icon_name="edit_icon_hover.png")


def _trash_button_stylesheet() -> str:
    return _icon_button_stylesheet("trash_icon.png", hover_icon_name="trash_icon_hover.png")


class ChatPromptEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Edit prompt",
        name: str = "",
        text: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(name)
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("System prompt:"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setMinimumHeight(180)
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

    def values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.text_edit.toPlainText()


class ChatPromptDeleteConfirmDialog(QDialog):
    def __init__(self, entry: ChatPromptEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete prompt")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Delete "{entry.name}"?'))

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(entry.text or "(empty prompt)")
        preview.setMinimumHeight(120)
        preview.setMaximumHeight(260)
        preview.setStyleSheet(
            "QTextEdit {"
            "  border: 1px solid #aaa;"
            "  border-radius: 4px;"
            "  padding: 8px;"
            "  background: #fafafa;"
            "  color: #333;"
            "}"
        )
        layout.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())


class ChatSystemPromptLibraryDialog(QDialog):
    def __init__(
        self,
        store: ChatPromptStore,
        parent: QWidget | None = None,
        *,
        new_prompt_suggestion: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("System prompts")
        self.setMinimumSize(480, 360)
        self._store = deepcopy(store)
        self._new_prompt_suggestion = new_prompt_suggestion
        self._radio_by_id: dict[str, QRadioButton] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Active system prompt:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_host = QWidget()
        self._list_layout = QVBoxLayout(list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        scroll.setWidget(list_host)
        layout.addWidget(scroll, stretch=1)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._rebuild_prompt_list()

        add_btn = QPushButton("Add prompt…")
        add_btn.clicked.connect(self._add_prompt)
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

    def result_store(self) -> ChatPromptStore:
        return self._store

    def selected_prompt_text(self) -> str:
        return self._store.active_prompt_text()

    def _rebuild_prompt_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._radio_by_id.clear()
        for btn in self._button_group.buttons():
            self._button_group.removeButton(btn)

        default_radio = QRadioButton("System default")
        default_radio.setToolTip(str(CHAT_DEFAULTS["chat_system_prompt"]))
        self._button_group.addButton(default_radio)
        self._list_layout.addWidget(default_radio)
        self._radio_by_id[SYSTEM_DEFAULT_ID] = default_radio

        for entry in self._store.prompts:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            radio = QRadioButton(entry.name or "Untitled")
            radio.setToolTip(entry.text[:200] + ("…" if len(entry.text) > 200 else ""))
            self._button_group.addButton(radio)
            self._radio_by_id[entry.id] = radio
            row_layout.addWidget(radio, stretch=1)

            edit_btn = QPushButton()
            edit_btn.setToolTip("Edit prompt")
            edit_btn.setStyleSheet(_edit_button_stylesheet())
            edit_btn.clicked.connect(lambda _=False, pid=entry.id: self._edit_prompt(pid))
            row_layout.addWidget(edit_btn)

            del_btn = QPushButton()
            del_btn.setToolTip("Delete prompt")
            del_btn.setStyleSheet(_trash_button_stylesheet())
            del_btn.clicked.connect(lambda _=False, pid=entry.id: self._delete_prompt(pid))
            row_layout.addWidget(del_btn)

            self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)
        self._select_active_radio()

    def _select_active_radio(self) -> None:
        active = self._store.active_id or SYSTEM_DEFAULT_ID
        radio = self._radio_by_id.get(active) or self._radio_by_id.get(SYSTEM_DEFAULT_ID)
        if radio:
            radio.setChecked(True)

    def _sync_active_from_ui(self) -> None:
        for prompt_id, radio in self._radio_by_id.items():
            if radio.isChecked():
                self._store.active_id = None if prompt_id == SYSTEM_DEFAULT_ID else prompt_id
                return

    def _add_prompt(self) -> None:
        suggestion = self._new_prompt_suggestion or str(CHAT_DEFAULTS["chat_system_prompt"])
        dlg = ChatPromptEditDialog(
            self,
            title="New prompt",
            name="New prompt",
            text=suggestion,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text = dlg.values()
        if not name:
            name = "Untitled"
        entry = ChatPromptEntry(id=uuid.uuid4().hex[:10], name=name, text=text)
        self._store.prompts.append(entry)
        self._store.active_id = entry.id
        self._rebuild_prompt_list()

    def _edit_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = ChatPromptEditDialog(self, title="Edit prompt", name=entry.name, text=entry.text)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text = dlg.values()
        entry.name = name or "Untitled"
        entry.text = text
        self._rebuild_prompt_list()

    def _delete_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = ChatPromptDeleteConfirmDialog(entry, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._store.prompts = [p for p in self._store.prompts if p.id != prompt_id]
        if self._store.active_id == prompt_id:
            self._store.active_id = None
        self._rebuild_prompt_list()

    def accept(self) -> None:
        self._sync_active_from_ui()
        super().accept()


def run_chat_system_prompt_library(
    parent: QWidget | None,
    *,
    suggestion_text: str = "",
) -> tuple[ChatPromptStore | None, str | None]:
    """Show library dialog. Returns (store, selected_text) on OK, else (None, None)."""
    store = ChatPromptStore.load()
    dlg = ChatSystemPromptLibraryDialog(
        store,
        parent,
        new_prompt_suggestion=suggestion_text,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None, None
    result = dlg.result_store()
    result.save()
    return result, dlg.selected_prompt_text()
