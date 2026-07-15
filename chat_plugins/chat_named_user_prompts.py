#!/usr/bin/env python3
"""Named favorite user prompts for the chat pane."""

from __future__ import annotations

import os
import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_prompt_config import (
    load_user_prompt_config,
    persist_favorite_image_paths,
    remove_favorite_image_files,
    save_user_prompt_config,
)
from chat_plugins.chat_prompt_grammar import (
    add_chat_prompt_button_row,
    apply_chat_prompt_save_format_to_widget,
)
from chat_plugins.chat_ui_common import (
    ChatImageThumbRow,
    ChatPromptLibraryPreview,
    _local_paths_from_mime,
    chat_library_edit_button_stylesheet,
    chat_library_trash_button_stylesheet,
    chat_prompt_edit_stylesheet,
    install_cmd_enter_accept,
)
from utils import get_button_style, get_dialog_shell_stylesheet

ICON_BTN_SIZE = 22


def _existing_image_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    return [p for p in paths if p and os.path.isfile(p)]


def _commit_favorite_images(
    favorite_id: str,
    image_paths: list[str],
    *,
    previous_paths: list[str] | None = None,
) -> list[str]:
    stored = persist_favorite_image_paths(
        favorite_id,
        _existing_image_paths(image_paths),
    )
    if previous_paths:
        retired = [p for p in previous_paths if p not in stored]
        remove_favorite_image_files(retired)
    return stored


class _FavoritePromptImageDropFilter(QObject):
    def __init__(self, thumb_row: ChatImageThumbRow) -> None:
        super().__init__(thumb_row)
        self._thumb_row = thumb_row

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            drag_event = event
            if isinstance(drag_event, (QDragEnterEvent, QDragMoveEvent)):
                if _local_paths_from_mime(drag_event.mimeData()):
                    drag_event.acceptProposedAction()
                    return True
                drag_event.ignore()
                return True
        if event.type() == QEvent.Type.Drop:
            drop_event = event
            if isinstance(drop_event, QDropEvent):
                paths = _local_paths_from_mime(drop_event.mimeData())
                if paths:
                    self._thumb_row.add_dropped_paths(paths)
                    drop_event.acceptProposedAction()
                    return True
                drop_event.ignore()
                return True
        return super().eventFilter(watched, event)


@dataclass
class ChatUserPromptEntry:
    id: str
    name: str
    text: str
    image_paths: list[str] = field(default_factory=list)


@dataclass
class ChatUserPromptStore:
    prompts: list[ChatUserPromptEntry] = field(default_factory=list)
    selected_id: str | None = None

    @classmethod
    def load(cls) -> ChatUserPromptStore:
        config = load_user_prompt_config()
        prompts: list[ChatUserPromptEntry] = []
        for item in config.get("favorite_prompts", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            raw_paths = item.get("image_paths")
            image_paths = (
                _existing_image_paths([str(p) for p in raw_paths])
                if isinstance(raw_paths, list)
                else []
            )
            prompts.append(
                ChatUserPromptEntry(
                    id=str(item["id"]),
                    name=str(item.get("name", "Untitled")),
                    text=str(item.get("text", "")),
                    image_paths=image_paths,
                )
            )
        selected_id = config.get("selected_favorite_prompt_id")
        if selected_id in (None, ""):
            selected_id = None
        else:
            selected_id = str(selected_id)
            if not any(p.id == selected_id for p in prompts):
                selected_id = None
        return cls(prompts=prompts, selected_id=selected_id)

    def save(self) -> None:
        config = load_user_prompt_config()
        config["favorite_prompts"] = [
            {
                "id": p.id,
                "name": p.name,
                "text": p.text,
                "image_paths": list(p.image_paths),
            }
            for p in self.prompts
        ]
        config["selected_favorite_prompt_id"] = self.selected_id or ""
        save_user_prompt_config(config)

    def find_prompt(self, prompt_id: str) -> ChatUserPromptEntry | None:
        for entry in self.prompts:
            if entry.id == prompt_id:
                return entry
        return None

    def selected_entry(self) -> ChatUserPromptEntry | None:
        if not self.selected_id:
            return None
        return self.find_prompt(self.selected_id)


class ChatUserPromptEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Edit user prompt",
        name: str = "",
        text: str = "",
        image_paths: list[str] | None = None,
        main_window=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(name)
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("User prompt:"))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setStyleSheet(chat_prompt_edit_stylesheet())
        self.text_edit.setMinimumHeight(120)
        layout.addWidget(self.text_edit)

        self._thumb_row = ChatImageThumbRow(
            self, compact_row=True, main_window=main_window
        )
        self._thumb_row.setAcceptDrops(True)
        existing = _existing_image_paths(image_paths)
        if existing:
            self._thumb_row.set_image_paths(existing, allow_remove=True)
        drop_filter = _FavoritePromptImageDropFilter(self._thumb_row)
        self.text_edit.setAcceptDrops(True)
        self.text_edit.installEventFilter(drop_filter)
        self._thumb_row.installEventFilter(drop_filter)
        layout.addWidget(self._thumb_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_chat_prompt_button_row(self, self.text_edit, layout, buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        install_cmd_enter_accept(self, self.name_edit, self.text_edit)

    def accept(self) -> None:
        apply_chat_prompt_save_format_to_widget(self.text_edit)
        super().accept()

    def values(self) -> tuple[str, str, list[str]]:
        return (
            self.name_edit.text().strip(),
            self.text_edit.toPlainText(),
            _existing_image_paths(self._thumb_row.image_paths()),
        )


class ChatUserPromptDeleteConfirmDialog(QDialog):
    def __init__(self, entry: ChatUserPromptEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete user prompt")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Delete "{entry.name}"?'))

        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(entry.text or "(empty prompt)")
        preview.setMinimumHeight(120)
        preview.setMaximumHeight(260)
        preview.setStyleSheet(chat_prompt_edit_stylesheet())
        layout.addWidget(preview)

        if entry.image_paths:
            count = len(_existing_image_paths(entry.image_paths))
            if count:
                layout.addWidget(
                    QLabel(f"{count} attached image{'s' if count != 1 else ''}")
                )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())


class ChatUserPromptLibraryDialog(QDialog):
    def __init__(
        self,
        store: ChatUserPromptStore,
        parent: QWidget | None = None,
        *,
        new_prompt_suggestion: str = "",
        new_prompt_images: list[str] | None = None,
        main_window=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Favorite user prompts")
        self.setMinimumSize(480, 360)
        self._store = deepcopy(store)
        self._new_prompt_suggestion = new_prompt_suggestion
        self._new_prompt_images = _existing_image_paths(new_prompt_images)
        self._main_window = main_window
        self._radio_by_id: dict[str, QRadioButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.buttonToggled.connect(self._on_prompt_radio_toggled)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a favorite to use:"))

        self._preview = ChatPromptLibraryPreview(self)
        layout.addWidget(self._preview)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_host = QWidget()
        self._list_layout = QVBoxLayout(list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        scroll.setWidget(list_host)
        layout.addWidget(scroll, stretch=1)

        self._rebuild_prompt_list()

        add_btn = QPushButton("Add Favorite Prompt…")
        add_btn.clicked.connect(self._add_prompt)
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

    def result_store(self) -> ChatUserPromptStore:
        return self._store

    def selected_entry(self) -> ChatUserPromptEntry | None:
        self._sync_selected_from_ui()
        entry = self._store.selected_entry()
        if entry is None:
            return None
        return ChatUserPromptEntry(
            id=entry.id,
            name=entry.name,
            text=entry.text,
            image_paths=_existing_image_paths(entry.image_paths),
        )

    def _on_prompt_radio_toggled(self, _button: QRadioButton, checked: bool) -> None:
        if checked:
            self._update_preview()

    def _update_preview(self) -> None:
        if not self._store.prompts:
            self._preview.set_prompt_text("No favorite user prompts yet.")
            return
        for prompt_id, radio in self._radio_by_id.items():
            if radio.isChecked():
                entry = self._store.find_prompt(prompt_id)
                self._preview.set_prompt_text(entry.text if entry else "")
                return
        self._preview.set_prompt_text("")

    def _rebuild_prompt_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._radio_by_id.clear()
        for btn in self._button_group.buttons():
            self._button_group.removeButton(btn)

        if not self._store.prompts:
            empty = QLabel("No favorite user prompts yet.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
        else:
            for entry in self._store.prompts:
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                label = entry.name or "Untitled"
                image_count = len(_existing_image_paths(entry.image_paths))
                if image_count:
                    label = f"{label} ({image_count} image{'s' if image_count != 1 else ''})"
                radio = QRadioButton(label)
                tip = entry.text[:200] + ("…" if len(entry.text) > 200 else "")
                radio.setToolTip(tip)
                self._button_group.addButton(radio)
                self._radio_by_id[entry.id] = radio
                row_layout.addWidget(radio, stretch=1)

                edit_btn = QPushButton()
                edit_btn.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
                edit_btn.setToolTip("Edit prompt")
                edit_btn.setStyleSheet(chat_library_edit_button_stylesheet())
                edit_btn.clicked.connect(
                    lambda _=False, pid=entry.id: self._edit_prompt(pid)
                )
                row_layout.addWidget(edit_btn)

                del_btn = QPushButton()
                del_btn.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
                del_btn.setToolTip("Delete prompt")
                del_btn.setStyleSheet(chat_library_trash_button_stylesheet())
                del_btn.clicked.connect(
                    lambda _=False, pid=entry.id: self._delete_prompt(pid)
                )
                row_layout.addWidget(del_btn)

                self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)
        self._select_selected_radio()
        self._update_preview()

    def _select_selected_radio(self) -> None:
        if not self._radio_by_id:
            return
        radio = self._radio_by_id.get(self._store.selected_id or "")
        if radio is None:
            radio = next(iter(self._radio_by_id.values()))
        radio.setChecked(True)

    def _sync_selected_from_ui(self) -> None:
        for prompt_id, radio in self._radio_by_id.items():
            if radio.isChecked():
                self._store.selected_id = prompt_id
                return

    def _add_prompt(self) -> None:
        dlg = ChatUserPromptEditDialog(
            self,
            title="New user prompt",
            name="New prompt",
            text=self._new_prompt_suggestion,
            image_paths=self._new_prompt_images,
            main_window=self._main_window,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text, image_paths = dlg.values()
        if not name:
            name = "Untitled"
        entry_id = uuid.uuid4().hex[:10]
        entry = ChatUserPromptEntry(
            id=entry_id,
            name=name,
            text=text,
            image_paths=_commit_favorite_images(entry_id, image_paths),
        )
        self._store.prompts.append(entry)
        self._store.selected_id = entry.id
        self._rebuild_prompt_list()

    def _edit_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = ChatUserPromptEditDialog(
            self,
            title="Edit user prompt",
            name=entry.name,
            text=entry.text,
            image_paths=entry.image_paths,
            main_window=self._main_window,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text, image_paths = dlg.values()
        previous_paths = list(entry.image_paths)
        entry.name = name or "Untitled"
        entry.text = text
        entry.image_paths = _commit_favorite_images(
            entry.id,
            image_paths,
            previous_paths=previous_paths,
        )
        self._rebuild_prompt_list()

    def _delete_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = ChatUserPromptDeleteConfirmDialog(entry, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        remove_favorite_image_files(entry.image_paths)
        self._store.prompts = [p for p in self._store.prompts if p.id != prompt_id]
        if self._store.selected_id == prompt_id:
            self._store.selected_id = (
                self._store.prompts[0].id if self._store.prompts else None
            )
        self._rebuild_prompt_list()

    def accept(self) -> None:
        self._sync_selected_from_ui()
        super().accept()


def run_chat_user_prompt_save_dialog(
    parent: QWidget | None,
    *,
    name: str = "",
    text: str = "",
    image_paths: list[str] | None = None,
    main_window=None,
) -> ChatUserPromptEntry | None:
    """Show save dialog for a new favorite. Returns entry on Save, else None."""
    dlg = ChatUserPromptEditDialog(
        parent,
        title="Save user prompt",
        name=name,
        text=text,
        image_paths=image_paths,
        main_window=main_window,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    save_name, save_text, save_images = dlg.values()
    if not save_name:
        save_name = "Untitled"
    entry_id = uuid.uuid4().hex[:10]
    entry = ChatUserPromptEntry(
        id=entry_id,
        name=save_name,
        text=save_text,
        image_paths=_commit_favorite_images(entry_id, save_images),
    )
    store = ChatUserPromptStore.load()
    store.prompts.append(entry)
    store.selected_id = entry.id
    store.save()
    return entry


def run_chat_user_prompt_library(
    parent: QWidget | None,
    *,
    suggestion_text: str = "",
    suggestion_images: list[str] | None = None,
    main_window=None,
) -> ChatUserPromptEntry | None:
    """Show library dialog. Returns selected entry on OK for applying, else None."""
    store = ChatUserPromptStore.load()
    dlg = ChatUserPromptLibraryDialog(
        store,
        parent,
        new_prompt_suggestion=suggestion_text,
        new_prompt_images=suggestion_images,
        main_window=main_window,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    result = dlg.result_store()
    result.save()
    return dlg.selected_entry()
