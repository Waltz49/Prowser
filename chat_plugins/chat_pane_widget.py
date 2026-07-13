#!/usr/bin/env python3
"""Main Chat sidebar pane widget."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QSize
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from browser_window.sidebar.sidebar_pane_chrome import (
    apply_scroll_area_viewport_background,
    apply_sidebar_pane_background,
)
from chat_plugins.chat_delete_confirm import (
    confirm_chat_message_delete,
    confirm_clear_chat,
)
from chat_plugins.chat_cleanup import purge_chat_disk_and_logs
from chat_plugins.chat_assistant_image_paths import (
    normalize_assistant_message_image_paths,
)
from chat_plugins.chat_image_paths import (
    align_source_image_paths,
    chat_paths_referenced_by_messages,
    paths_for_image_gen,
    sources_for_new_attachments,
)
from chat_plugins.chat_image_gen_trigger import (
    effective_image_gen_auto_mode,
    prepare_user_message_for_storage,
    user_message_wants_assistant_sources,
)
from chat_plugins.chat_image_store import ChatImageStore, reset_image_store_session
from chat_plugins.chat_persistence import (
    clear_persisted_chat_files,
    is_preserve_chat_across_sessions,
    is_automatic_create,
    is_copy_images_to_assistant,
    load_chat_session_messages,
    save_chat_session_messages,
    set_preserve_chat_across_sessions as persist_preserve_setting,
    set_automatic_create as persist_automatic_create,
    set_copy_images_to_assistant as persist_copy_images_to_assistant,
)
from chat_plugins.chat_ui_common import chat_create_from_text_available
from chat_plugins.chat_lmstudio import (
    is_lmstudio_chat_available,
    load_chat_system_prompt,
    lmstudio_unavailable_message,
    save_chat_system_prompt,
)
from chat_plugins.chat_message_widgets import ChatMessageWidget
from chat_plugins.chat_prompt_input import ChatPromptInput
from chat_plugins.chat_session import ChatMessage, ChatSession
from chat_plugins.chat_named_user_prompts import (
    run_chat_user_prompt_library,
    run_chat_user_prompt_save_dialog,
)
from chat_plugins.chat_system_prompt_dialog import edit_chat_system_prompt
from chat_plugins.chat_tools_menu import show_chat_context_menu, show_chat_tools_menu
from chat_plugins.chat_worker import ChatLmStudioService
from theme.theme_base import job_pane_tools_icon_path
from theme.theme_service import get_active_theme
from utils import get_button_style

MIN_CHAT_PANE_WIDTH = 250
MIN_CHAT_CONTENT_HEIGHT = 80


def _chat_cmd_r_key_event(event: QKeyEvent) -> bool:
    if event.key() != Qt.Key.Key_R:
        return False
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    if not (mods & Qt.KeyboardModifier.ControlModifier):
        return False
    other = mods & ~(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier
    )
    return other in (Qt.KeyboardModifier.NoModifier, 0)


class _ChatRedoKeyFilter(QObject):
    """Cmd+R redo when focus is in the chat pane; blocks global Refresh Directory."""

    def __init__(self, pane: "ChatPaneWidget", parent: QObject | None = None) -> None:
        super().__init__(parent or pane)
        self._pane = pane

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Destroy:
            if isinstance(watched, QWidget) and isValid(watched):
                watched.removeEventFilter(self)
            return False
        if not isValid(self._pane):
            return False
        if not self._pane.isVisible():
            return False
        if event.type() == QEvent.Type.ShortcutOverride:
            if isinstance(event, QKeyEvent) and _chat_cmd_r_key_event(event):
                event.accept()
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isinstance(event, QKeyEvent):
            return False
        if not _chat_cmd_r_key_event(event):
            return False
        self._pane._redo_last_user_message()
        event.accept()
        return True


def _attach_chat_redo_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_chat_redo_key_filter", None)
    if filt is None or not isValid(host):
        return
    tracked: set[int] = getattr(host, "_chat_redo_key_filter_widgets", None) or set()
    for widget in (host, *host.findChildren(QWidget)):
        if not isValid(widget):
            continue
        wid = id(widget)
        if wid in tracked:
            continue
        widget.installEventFilter(filt)
        tracked.add(wid)
    setattr(host, "_chat_redo_key_filter_widgets", tracked)


def _detach_chat_redo_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_chat_redo_key_filter", None)
    if filt is None:
        return
    tracked: set[int] = getattr(host, "_chat_redo_key_filter_widgets", None) or set()
    if not isValid(host):
        tracked.clear()
        setattr(host, "_chat_redo_key_filter_widgets", tracked)
        return
    host.removeEventFilter(filt)
    for widget in host.findChildren(QWidget):
        if isValid(widget):
            widget.removeEventFilter(filt)
    tracked.clear()
    setattr(host, "_chat_redo_key_filter_widgets", tracked)


def install_chat_redo_key_filter(pane: "ChatPaneWidget") -> None:
    """Cmd+R — redo last user message when a chat child widget has focus."""
    filt = getattr(pane, "_chat_redo_key_filter", None)
    if filt is None:
        filt = _ChatRedoKeyFilter(pane, parent=pane)
        setattr(pane, "_chat_redo_key_filter", filt)
        app = QApplication.instance()
        if app is not None and not getattr(pane, "_chat_redo_quit_hooked", False):
            app.aboutToQuit.connect(lambda p=pane: _detach_chat_redo_key_filter(p))
            pane._chat_redo_quit_hooked = True
    _attach_chat_redo_key_filter(pane)


def _is_chat_text_field(widget: QWidget | None) -> bool:
    return isinstance(widget, (QPlainTextEdit, QTextEdit, QLineEdit))


def _chat_tab_direction(event: QKeyEvent) -> int | None:
    if event.key() == Qt.Key.Key_Backtab:
        return -1
    if event.key() != Qt.Key.Key_Tab:
        return None
    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
        return -1
    return 1


class _ChatTabKeyFilter(QObject):
    """Route Tab away from chat text fields to canvas / chat or tree focus."""

    def __init__(self, pane: "ChatPaneWidget", parent: QObject | None = None) -> None:
        super().__init__(parent or pane)
        self._pane = pane

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        del watched
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isValid(self._pane):
            return False
        if not self._pane.isVisible():
            return False
        if not isinstance(event, QKeyEvent):
            return False
        direction = _chat_tab_direction(event)
        if direction is None:
            return False
        focus = QApplication.focusWidget()
        if focus is None:
            return False
        if focus is not self._pane and not self._pane.isAncestorOf(focus):
            return False
        if not _is_chat_text_field(focus):
            return False
        mw = self._pane.main_window
        if direction > 0:
            if hasattr(mw, "focus_canvas"):
                mw.focus_canvas()
        else:
            cs = getattr(mw, "combined_sidebar", None)
            if (
                cs is not None
                and hasattr(cs, "is_chat_covering_panes")
                and cs.is_chat_covering_panes()
                and hasattr(mw, "focus_chat")
            ):
                mw.focus_chat()
            elif hasattr(mw, "focus_tree"):
                mw.focus_tree()
        event.accept()
        return True


def _attach_chat_tab_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_chat_tab_key_filter", None)
    if filt is None or not isValid(host):
        return
    tracked: set[int] = getattr(host, "_chat_tab_key_filter_widgets", None) or set()
    for widget in (host, *host.findChildren(QWidget)):
        if not isValid(widget):
            continue
        wid = id(widget)
        if wid in tracked:
            continue
        widget.installEventFilter(filt)
        tracked.add(wid)
    setattr(host, "_chat_tab_key_filter_widgets", tracked)


def install_chat_tab_key_filter(pane: "ChatPaneWidget") -> None:
    """Tab from chat text fields toggles canvas vs chat or tree (not tab order)."""
    filt = getattr(pane, "_chat_tab_key_filter", None)
    if filt is None:
        filt = _ChatTabKeyFilter(pane, parent=pane)
        setattr(pane, "_chat_tab_key_filter", filt)
    _attach_chat_tab_key_filter(pane)


def _apply_chat_text_field_focus_policies(host: QWidget) -> None:
    for widget in host.findChildren(QWidget):
        if _is_chat_text_field(widget):
            widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            widget.setTabChangesFocus(False)


class ChatPaneWidget(QWidget):
    """Scrollable chat history with LM Studio backend."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._session = ChatSession(system_prompt=load_chat_system_prompt())
        self._preserve_across_sessions = is_preserve_chat_across_sessions()
        self._copy_images_to_assistant = is_copy_images_to_assistant()
        self._automatic_create = is_automatic_create()
        self._image_store = ChatImageStore(persistent=self._preserve_across_sessions)
        self._header_getter: Callable[[], QWidget | None] | None = None
        self._message_widgets: list[ChatMessageWidget] = []
        self._editing_message_widget: ChatMessageWidget | None = None
        self._lm_service = ChatLmStudioService.instance()
        self._streaming_widget: ChatMessageWidget | None = None
        self._generating_user_widget: ChatMessageWidget | None = None
        self._lm_available_on_show = True
        self._chat_started = False
        self._setup_ui()
        install_chat_redo_key_filter(self)
        install_chat_tab_key_filter(self)
        if self._preserve_across_sessions:
            self._restore_persisted_session()
        if not self._copy_images_to_assistant:
            self._clear_assistant_message_images(refresh_widgets=True)
        app = QApplication.instance()
        if app is not None and not getattr(self, "_chat_persist_quit_hooked", False):
            app.aboutToQuit.connect(self._persist_on_quit_if_enabled)
            self._chat_persist_quit_hooked = True

    def set_header_getter(self, getter: Callable[[], QWidget | None] | None) -> None:
        self._header_getter = getter

    def attach_titlebar_tools(self) -> None:
        header = self._chat_header()
        if header is None:
            return
        btn = QPushButton()
        btn.setIcon(QIcon(job_pane_tools_icon_path()))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip("Chat tools")
        btn.clicked.connect(lambda: show_chat_tools_menu(self, btn))
        if hasattr(header, "set_tools_button"):
            header.set_tools_button(btn)

    def _chat_header(self):
        if self._header_getter is None:
            return None
        return self._header_getter()

    def _setup_ui(self) -> None:
        self.setMinimumWidth(0)
        th = get_active_theme()
        apply_sidebar_pane_background(self, th.sidebar_background_color_hex)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._unavailable_host = QWidget()
        unavailable_layout = QVBoxLayout(self._unavailable_host)
        unavailable_layout.setContentsMargins(16, 16, 16, 16)
        unavailable_layout.setSpacing(12)
        unavailable_layout.addStretch(1)

        self._unavailable_label = QLabel()
        self._unavailable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unavailable_label.setWordWrap(True)
        unavailable_layout.addWidget(self._unavailable_label)

        self._unavailable_lmstudio_btn = QPushButton("LM Studio")
        self._unavailable_lmstudio_btn.clicked.connect(self._on_open_lmstudio)
        lmstudio_btn_row = QHBoxLayout()
        lmstudio_btn_row.addStretch(1)
        lmstudio_btn_row.addWidget(self._unavailable_lmstudio_btn)
        lmstudio_btn_row.addStretch(1)
        unavailable_layout.addLayout(lmstudio_btn_row)
        unavailable_layout.addStretch(1)

        self._unavailable_host.hide()
        self._style_unavailable_panel()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(th.sidebar_pane_scroll_area_stylesheet())
        apply_scroll_area_viewport_background(self._scroll)

        self._messages_host = QWidget()
        apply_sidebar_pane_background(
            self._messages_host, th.sidebar_background_color_hex
        )
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(0, 4, 0, 4)
        self._messages_layout.setSpacing(0)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_host)
        self._scroll.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._scroll.customContextMenuRequested.connect(
            lambda pos: show_chat_context_menu(
                self, self._scroll.viewport().mapToGlobal(pos)
            )
        )

        self._prompt_input = ChatPromptInput(self, main_window=self.main_window)
        self._prompt_input.submit_requested.connect(self._on_user_submit)
        apply_sidebar_pane_background(
            self._prompt_input, th.sidebar_background_color_hex
        )
        self.ensure_input_focus_policy()

        layout.addWidget(self._unavailable_host, 1)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._prompt_input, 0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: show_chat_context_menu(self, self.mapToGlobal(pos))
        )

    def _style_unavailable_panel(self) -> None:
        th = get_active_theme()
        self._unavailable_label.setStyleSheet(
            f"color: {th.sidebar_text_color_hex}; font-size: 12px;"
        )
        self._unavailable_label.setText(lmstudio_unavailable_message())
        self._unavailable_lmstudio_btn.setStyleSheet(get_button_style())

    def _on_open_lmstudio(self) -> None:
        from browser_window.managers.lmstudio_launcher import (
            open_lmstudio_or_show_install_help,
        )

        open_lmstudio_or_show_install_help(self)

    def on_pane_activated(self) -> None:
        """Called when the user shows the chat pane; check LM Studio once."""
        available = is_lmstudio_chat_available()
        self._lm_available_on_show = available
        if not available and not self._chat_started:
            self._show_unavailable_only(True)
        else:
            self._show_unavailable_only(False)
        self.ensure_input_focus_policy()
        _attach_chat_redo_key_filter(self)
        _attach_chat_tab_key_filter(self)
        QTimer.singleShot(0, lambda: self._prompt_input.text_edit().setFocus())

    def _show_unavailable_only(self, show: bool) -> None:
        if show:
            self._style_unavailable_panel()
            self._unavailable_host.show()
            self._scroll.hide()
            self._prompt_input.hide()
        else:
            self._unavailable_host.hide()
            self._scroll.show()
            self._prompt_input.show()

    def prompt_text_edit(self):
        return self._prompt_input.text_edit()

    def ensure_input_focus_policy(self) -> None:
        """Keep chat text fields typable on click but out of the Tab focus chain."""
        _apply_chat_text_field_focus_policies(self)
        install_chat_tab_key_filter(self)

    def _redo_last_user_message(self) -> None:
        if not self.isVisible():
            return
        user_idx = self._session.last_user_index()
        if user_idx < 0:
            return
        msg = self._session.messages[user_idx]
        self._on_redo(msg.message_id)

    def preferred_content_height(self) -> int:
        return max(MIN_CHAT_CONTENT_HEIGHT, self._messages_host.sizeHint().height() + 120)

    def refresh_theme_styles(self) -> None:
        th = get_active_theme()
        pane_bg = th.sidebar_background_color_hex
        apply_sidebar_pane_background(self, pane_bg)
        apply_sidebar_pane_background(self._messages_host, pane_bg)
        apply_sidebar_pane_background(self._prompt_input, pane_bg)
        self._scroll.setStyleSheet(th.sidebar_pane_scroll_area_stylesheet())
        apply_scroll_area_viewport_background(self._scroll)
        self._style_unavailable_panel()
        for widget in self._message_widgets:
            widget.refresh_theme_styles()
        self._prompt_input.text_edit().setStyleSheet(
            __import__(
                "chat_plugins.chat_ui_common", fromlist=["chat_prompt_edit_stylesheet"]
            ).chat_prompt_edit_stylesheet()
        )

    def discard_all_data(self) -> None:
        """Remove in-memory history, temp images, and chat API log entries."""
        self._cancel_worker()
        self._session.clear()
        self._chat_started = False
        self._clear_message_widgets()
        self._prompt_input.clear_content()
        if self._preserve_across_sessions:
            clear_persisted_chat_files()
        purge_chat_disk_and_logs()
        reset_image_store_session(
            self._image_store,
            persistent=self._preserve_across_sessions,
        )

    def persist_chat_for_next_session(self) -> None:
        """Save the current conversation when preserve-across-sessions is enabled."""
        if not self._preserve_across_sessions:
            return
        if self._session.has_started():
            messages = self._messages_for_persistence()
            save_chat_session_messages(messages)
        else:
            clear_persisted_chat_files()

    def _messages_for_persistence(self) -> list[ChatMessage]:
        if self._copy_images_to_assistant:
            return list(self._session.messages)
        out: list[ChatMessage] = []
        for msg in self._session.messages:
            if msg.role == "assistant" and msg.image_paths:
                copy = ChatMessage(
                    role=msg.role,
                    text=msg.text,
                    message_id=msg.message_id,
                    image_paths=[],
                    source_image_paths=[],
                    image_gen_auto=msg.image_gen_auto,
                )
                out.append(copy)
            else:
                out.append(msg)
        return out

    def _persist_on_quit_if_enabled(self) -> None:
        self.persist_chat_for_next_session()

    def _maybe_persist_session(self) -> None:
        if self._preserve_across_sessions:
            self.persist_chat_for_next_session()

    def set_preserve_chat_across_sessions(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._preserve_across_sessions:
            return
        self._preserve_across_sessions = enabled
        persist_preserve_setting(enabled)
        if enabled:
            reset_image_store_session(self._image_store, persistent=True)
            if self._session.has_started():
                self._image_store.restage_message_images(self._session.messages)
                self.persist_chat_for_next_session()
            return
        clear_persisted_chat_files()
        reset_image_store_session(self._image_store, persistent=False)
        if self._session.has_started():
            self._image_store.restage_message_images(self._session.messages)

    def set_automatic_create(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._automatic_create:
            return
        self._automatic_create = enabled
        persist_automatic_create(enabled)

    def set_copy_images_to_assistant(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._copy_images_to_assistant:
            return
        self._copy_images_to_assistant = enabled
        persist_copy_images_to_assistant(enabled)
        if not enabled:
            self._clear_assistant_message_images(refresh_widgets=True)
            self._maybe_persist_session()

    def _clear_assistant_message_images(self, *, refresh_widgets: bool) -> None:
        for msg in self._session.messages:
            if msg.role == "assistant":
                msg.image_paths = []
        if not refresh_widgets:
            return
        for msg, widget in zip(self._session.messages, self._message_widgets):
            if msg.role == "assistant":
                widget.update_message(msg)

    def _apply_assistant_reference_images(
        self,
        message_id: str,
        user_image_paths: list[str],
    ) -> list[str]:
        # Display only the preceding user bubble's attachments (no EXIF expansion).
        paths = normalize_assistant_message_image_paths(user_image_paths)
        idx = self._session.index_of(message_id)
        if idx < 0:
            return paths
        self._session.messages[idx].image_paths = paths
        if 0 <= idx < len(self._message_widgets):
            self._message_widgets[idx].update_message(self._session.messages[idx])
        return paths

    def _restore_persisted_session(self) -> None:
        messages = load_chat_session_messages()
        if not messages:
            return
        self._show_unavailable_only(False)
        self._chat_started = True
        for message in messages:
            self._session.append(message)
            self._append_message_widget(message)
        self._maybe_persist_session()

    def clear_chat(self) -> None:
        if self._session.has_started():
            if not confirm_clear_chat(self.main_window):
                return
        self.discard_all_data()
        if not self._lm_available_on_show:
            self._show_unavailable_only(True)

    def edit_system_prompt(self) -> None:
        result = edit_chat_system_prompt(
            self.main_window,
            self._session.system_prompt,
        )
        if result is None:
            return
        self._session.system_prompt = result
        save_chat_system_prompt(result)

    def open_favorite_user_prompts(self) -> None:
        current_text = self._prompt_input.text_edit().toPlainText()
        current_images = self._prompt_input.image_paths()
        entry = run_chat_user_prompt_library(
            self.main_window,
            suggestion_text=current_text,
            suggestion_images=current_images,
            main_window=self.main_window,
        )
        if entry is None:
            return
        self._prompt_input.set_content(entry.text, entry.image_paths)

    def _on_favorite_user_prompt(self, message_id: str) -> None:
        idx = self._session.index_of(message_id)
        if idx < 0:
            return
        msg = self._session.messages[idx]
        if msg.role != "user":
            return
        image_paths = list(msg.image_paths or [])
        if not image_paths:
            for widget in self._message_widgets:
                if widget.message_id() == message_id:
                    image_paths = widget.displayed_image_paths()
                    break
        run_chat_user_prompt_save_dialog(
            self.main_window,
            text=msg.text,
            image_paths=image_paths,
            main_window=self.main_window,
        )

    def _clear_message_widgets(self) -> None:
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._message_widgets.clear()
        self._streaming_widget = None
        self._generating_user_widget = None

    def _wire_message_widget(self, widget: ChatMessageWidget) -> None:
        widget.edit_ended.connect(
            lambda w=widget: self._exclusive_edit_end(w)
        )
        widget.stop_requested.connect(self._on_stop_generation)

    def _set_generation_stop_ui(self, active: bool) -> None:
        if not active:
            for widget in self._message_widgets:
                widget.set_stop_visible(False)
            self._generating_user_widget = None
            return
        user_idx = self._session.last_user_index()
        user_widget: ChatMessageWidget | None = None
        if 0 <= user_idx < len(self._message_widgets):
            user_widget = self._message_widgets[user_idx]
        self._generating_user_widget = user_widget
        for widget in self._message_widgets:
            widget.set_stop_visible(widget is user_widget)

    def _on_stop_generation(self) -> None:
        if self._is_worker_active():
            self._cancel_worker()

    def _remove_streaming_widget(self) -> None:
        if self._streaming_widget is None:
            return
        self._messages_layout.removeWidget(self._streaming_widget)
        self._streaming_widget.deleteLater()
        if self._streaming_widget in self._message_widgets:
            self._message_widgets.remove(self._streaming_widget)
        self._streaming_widget = None

    def _exclusive_edit_begin(self, widget: ChatMessageWidget) -> None:
        current = self._editing_message_widget
        if (
            current is not None
            and current is not widget
            and current.is_editing()
        ):
            current._commit_edit()
        self._editing_message_widget = widget
        widget._enter_edit_mode()

    def _exclusive_edit_end(self, widget: ChatMessageWidget) -> None:
        if self._editing_message_widget is widget:
            self._editing_message_widget = None

    def _append_message_widget(self, message: ChatMessage) -> ChatMessageWidget:
        widget = ChatMessageWidget(
            message,
            self._messages_host,
            on_edit_saved=self._on_edit_saved,
            on_exclusive_edit_begin=self._exclusive_edit_begin,
            on_redo=self._on_redo,
            on_delete=self._on_delete,
            on_create_from_text=self._on_create_from_text,
            on_favorite=self._on_favorite_user_prompt,
            main_window=self.main_window,
        )
        self._wire_message_widget(widget)
        insert_at = max(0, self._messages_layout.count() - 1)
        self._messages_layout.insertWidget(insert_at, widget)
        self._message_widgets.append(widget)
        _attach_chat_redo_key_filter(self)
        _attach_chat_tab_key_filter(self)
        QTimer.singleShot(0, self._scroll_to_bottom)
        return widget

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_user_submit(self, text: str, image_paths: list[str]) -> None:
        if self._is_worker_active():
            return
        if not self._lm_available_on_show and not self._chat_started:
            return
        text, image_paths, image_gen_auto = prepare_user_message_for_storage(
            text, image_paths, self.main_window, automatic_create=self._automatic_create
        )
        if not text and not image_paths:
            return
        self._show_unavailable_only(False)
        self._chat_started = True
        msg = ChatMessage(role="user", text=text, image_gen_auto=image_gen_auto)
        if image_paths:
            sources = sources_for_new_attachments(image_paths)
            msg.image_paths = self._image_store.store_images(
                image_paths,
                message_id=msg.message_id,
            )
            msg.source_image_paths = align_source_image_paths(
                msg.image_paths, sources
            )
        self._session.append(msg)
        self._append_message_widget(msg)
        self._maybe_persist_session()
        self._request_assistant_response()

    def _request_assistant_response(self) -> None:
        placeholder = ChatMessage(role="assistant", text="…")
        self._streaming_widget = self._append_message_widget(placeholder)
        self._session.append(placeholder)

        def on_chunk(piece: str) -> None:
            if self._streaming_widget is None:
                return
            idx = self._session.index_of(placeholder.message_id)
            if idx >= 0:
                self._session.messages[idx].text += piece
                self._streaming_widget.update_message(self._session.messages[idx])
            self._scroll_to_bottom()

        def on_finished(final: str) -> None:
            idx = self._session.index_of(placeholder.message_id)
            if idx >= 0:
                self._session.messages[idx].text = final
                if self._streaming_widget is not None:
                    self._streaming_widget.update_message(self._session.messages[idx])
            self._streaming_widget = None
            self._set_generation_stop_ui(False)
            self._scroll_to_bottom()
            self._maybe_persist_session()

        def on_restarted() -> None:
            if self._streaming_widget is None:
                return
            idx = self._session.index_of(placeholder.message_id)
            if idx >= 0:
                self._session.messages[idx].text = "…"
                self._streaming_widget.update_message(self._session.messages[idx])

        def on_error(err: str) -> None:
            idx = self._session.index_of(placeholder.message_id)
            if idx >= 0:
                self._session.remove_at(idx)
            self._remove_streaming_widget()
            self._set_generation_stop_ui(False)
            self._maybe_persist_session()
            QMessageBox.warning(self, "Chat Error", err)

        def on_cancelled() -> None:
            idx = self._session.index_of(placeholder.message_id)
            if idx >= 0:
                text = (self._session.messages[idx].text or "").strip()
                if text in ("", "…"):
                    self._session.remove_at(idx)
                    self._remove_streaming_widget()
                elif self._streaming_widget is not None:
                    self._streaming_widget.update_message(self._session.messages[idx])
                    self._streaming_widget = None
            else:
                self._remove_streaming_widget()
            self._set_generation_stop_ui(False)
            self._scroll_to_bottom()
            self._maybe_persist_session()

        history = [
            m
            for m in self._session.messages
            if m.message_id != placeholder.message_id
        ]
        auto_image_gen_mode = None
        auto_image_gen_user_paths: list[str] = []
        attach_assistant_sources = False
        for msg in reversed(history):
            if msg.role == "user":
                auto_image_gen_mode = effective_image_gen_auto_mode(
                    msg.text,
                    has_user_images=bool(msg.image_paths),
                    image_gen_auto=msg.image_gen_auto,
                    automatic_create=self._automatic_create,
                )
                auto_image_gen_user_paths = paths_for_image_gen(msg)
                attach_assistant_sources = user_message_wants_assistant_sources(
                    msg.text,
                    has_user_images=bool(msg.image_paths),
                ) or (
                    self._copy_images_to_assistant
                    and auto_image_gen_mode == "edit"
                    and bool(auto_image_gen_user_paths)
                )
                break

        def on_finished_with_auto_generate(
            final: str, suppress_auto_image_gen: bool
        ) -> None:
            on_finished(final)
            if suppress_auto_image_gen:
                return
            edit_source_paths: list[str] = []
            if attach_assistant_sources and auto_image_gen_user_paths:
                edit_source_paths = self._apply_assistant_reference_images(
                    placeholder.message_id,
                    auto_image_gen_user_paths,
                )
                self._scroll_to_bottom()
            if auto_image_gen_mode == "create":
                self._auto_create_from_text_if_available(final)
            elif auto_image_gen_mode == "edit":
                paths = list(auto_image_gen_user_paths)
                self._auto_edit_from_text_if_available(final, paths)

        started = self._lm_service.submit(
            history,
            on_chunk=on_chunk,
            on_finished=on_finished_with_auto_generate,
            on_error=on_error,
            on_cancelled=on_cancelled,
            on_restarted=on_restarted,
            system_prompt=self._session.system_prompt,
        )
        if not started:
            self._session.remove_at(self._session.index_of(placeholder.message_id))
            self._remove_streaming_widget()
            QMessageBox.warning(
                self,
                "Chat Busy",
                "Please wait for the current response to finish.",
            )
            return
        self._set_generation_stop_ui(True)

    def _is_worker_active(self) -> bool:
        return self._lm_service.is_busy()

    def _cancel_worker(self) -> None:
        self._lm_service.cancel()

    def _on_edit_saved(self, message_id: str, text: str, image_paths: list[str]) -> None:
        idx = self._session.index_of(message_id)
        if idx < 0:
            return
        msg = self._session.messages[idx]
        image_gen_auto = msg.image_gen_auto
        if msg.role == "user":
            text, image_paths, image_gen_auto = prepare_user_message_for_storage(
                text,
                image_paths,
                self.main_window,
                automatic_create=self._automatic_create,
            )
        old_image_paths = list(msg.image_paths or [])
        old_source_paths = list(msg.source_image_paths) if msg.role == "user" else []
        old_text = msg.text
        msg.text = text
        if msg.role == "user":
            msg.image_gen_auto = image_gen_auto
        if msg.role == "user":
            still_referenced = chat_paths_referenced_by_messages(
                self._session.messages,
                except_message_id=msg.message_id,
            )
            new_sources = sources_for_new_attachments(
                image_paths,
                old_stored_paths=old_image_paths,
                old_source_paths=old_source_paths,
            )
            msg.image_paths = self._image_store.replace_message_images(
                msg.image_paths,
                image_paths,
                message_id=msg.message_id,
                still_referenced=still_referenced,
            )
            msg.source_image_paths = align_source_image_paths(
                msg.image_paths, new_sources
            )
        elif msg.role == "assistant":
            msg.image_paths = normalize_assistant_message_image_paths(image_paths)
        images_changed = sorted(old_image_paths) != sorted(msg.image_paths or [])
        text_changed = msg.text != old_text
        for i, widget in enumerate(self._message_widgets):
            if widget.message_id() != message_id:
                continue
            if images_changed:
                lay_idx = self._messages_layout.indexOf(widget)
                if self._editing_message_widget is widget:
                    self._editing_message_widget = None
                self._messages_layout.removeWidget(widget)
                widget.deleteLater()
                self._message_widgets.pop(i)
                new_widget = ChatMessageWidget(
                    msg,
                    self._messages_host,
                    on_edit_saved=self._on_edit_saved,
                    on_exclusive_edit_begin=self._exclusive_edit_begin,
                    on_redo=self._on_redo,
                    on_delete=self._on_delete,
                    on_create_from_text=self._on_create_from_text,
                    on_favorite=self._on_favorite_user_prompt,
                    main_window=self.main_window,
                )
                self._wire_message_widget(new_widget)
                self._messages_layout.insertWidget(lay_idx, new_widget)
                self._message_widgets.insert(i, new_widget)
                _attach_chat_redo_key_filter(self)
                _attach_chat_tab_key_filter(self)
            elif text_changed:
                widget.update_message(msg)
            break
        self._maybe_persist_session()

    def _on_redo(self, message_id: str) -> None:
        user_idx = self._session.user_index_for_redo(message_id)
        if user_idx < 0:
            return
        self._cancel_worker()
        while len(self._session.messages) > user_idx + 1:
            removed = self._session.messages.pop()
            still_referenced = chat_paths_referenced_by_messages(
                self._session.messages
            )
            self._image_store.remove_message_images(
                removed.image_paths,
                still_referenced=still_referenced,
            )
        while len(self._message_widgets) > user_idx + 1:
            w = self._message_widgets.pop()
            self._messages_layout.removeWidget(w)
            w.deleteLater()
        self._streaming_widget = None
        self._set_generation_stop_ui(False)
        self._request_assistant_response()

    def _auto_create_from_text_if_available(self, text: str) -> None:
        if not chat_create_from_text_available():
            return
        prompt = (text or "").strip()
        if not prompt:
            return
        self._on_create_from_text(prompt, option_held=True)

    def _auto_edit_from_text_if_available(
        self, text: str, source_image_paths: list[str]
    ) -> None:
        prompt = (text or "").strip()
        if not prompt:
            return
        paths = [p for p in source_image_paths if p]
        if not paths:
            self._auto_create_from_text_if_available(text)
            return
        try:
            from imagegen_plugins.image_gen_menu import (
                imagegen_edit_from_text_available,
                open_imagegen_edit_from_text_dialog,
            )
        except ImportError:
            self._auto_create_from_text_if_available(text)
            return
        if not imagegen_edit_from_text_available():
            self._auto_create_from_text_if_available(text)
            return
        open_imagegen_edit_from_text_dialog(
            self.main_window,
            user_comment=prompt,
            auto_generate=True,
            source_image_paths=paths,
        )

    def _on_create_from_text(
        self,
        text: str,
        option_held: bool = False,
        source_image_paths: list[str] | None = None,
    ) -> None:
        paths = [p for p in (source_image_paths or []) if p]
        if paths and self._copy_images_to_assistant:
            try:
                from imagegen_plugins.image_gen_menu import (
                    imagegen_edit_from_text_available,
                    open_imagegen_edit_from_text_dialog,
                )
            except ImportError:
                paths = []
            else:
                if imagegen_edit_from_text_available():
                    open_imagegen_edit_from_text_dialog(
                        self.main_window,
                        user_comment=text,
                        auto_generate=option_held,
                        source_image_paths=paths,
                    )
                    return
        try:
            from imagegen_plugins.image_gen_menu import open_imagegen_create_from_text_dialog
        except ImportError:
            return
        open_imagegen_create_from_text_dialog(
            self.main_window,
            user_comment=text,
            auto_generate=option_held,
        )

    def _on_delete(self, message_id: str) -> None:
        idx = self._session.index_of(message_id)
        if idx < 0:
            return
        if not confirm_chat_message_delete(self.main_window):
            return
        removed = self._session.remove_at(idx)
        if removed is not None:
            still_referenced = chat_paths_referenced_by_messages(
                self._session.messages
            )
            self._image_store.remove_message_images(
                removed.image_paths,
                still_referenced=still_referenced,
            )
        if 0 <= idx < len(self._message_widgets):
            w = self._message_widgets.pop(idx)
            self._messages_layout.removeWidget(w)
            w.deleteLater()
        self._maybe_persist_session()
