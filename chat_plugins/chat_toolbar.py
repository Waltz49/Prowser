#!/usr/bin/env python3
"""Chat pane toolbar: system prompt, copy-images toggle, and clear chat."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from theme.theme_service import get_active_theme
from thumbnails.information_action_nav import (
    INFO_ACTION_BTN_PX,
    INFO_ACTION_ICON_PX,
    info_action_button_stylesheet,
)
from widgets.icon_hover_swap import IconHoverSwap, attach_icon_hover_swap, icon_pair_from_assets

_TOOLBAR_ACTION = tuple[str, str, str, str, bool]

_LEFT_TOOLBAR_ACTIONS: tuple[_TOOLBAR_ACTION, ...] = (
    (
        "system_prompt",
        "prompt.png",
        "prompt_hover.png",
        "System prompt for chat\nOpen the system prompt library",
        False,
    ),
    (
        "copy_images",
        "copy_asst.png",
        "copy_asst_hover.png",
        "Copy images to Assistant's reply\n"
        "When enabled, assistant replies show the preceding user message images",
        True,
    ),
)

_RIGHT_TOOLBAR_ACTIONS: tuple[_TOOLBAR_ACTION, ...] = (
    (
        "clear_chat",
        "trash_icon.png",
        "trash_icon_hover.png",
        "Clear Chat\nRemove all messages and attachments",
        False,
    ),
)

_TOOLBAR_ACTIONS = _LEFT_TOOLBAR_ACTIONS + _RIGHT_TOOLBAR_ACTIONS


class ChatPaneToolbar(QWidget):
    """Horizontal toolbar for common chat pane actions."""

    def __init__(self, pane: object, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pane = pane
        self._buttons: Dict[str, QPushButton] = {}
        self._icon_hovers: Dict[str, IconHoverSwap] = {}
        self._setup_ui()

    def _make_icon_button(
        self,
        *,
        action_id: str,
        tooltip: str,
        normal_name: str,
        hover_name: str,
        on_click: Callable[[], None],
        checkable: bool = False,
    ) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(INFO_ACTION_BTN_PX, INFO_ACTION_BTN_PX)
        btn.setIconSize(QSize(INFO_ACTION_ICON_PX, INFO_ACTION_ICON_PX))
        normal, hover = icon_pair_from_assets(normal_name, hover_name)
        self._icon_hovers[action_id] = attach_icon_hover_swap(btn, normal, hover)
        if checkable:
            btn.setCheckable(True)
        btn.clicked.connect(on_click)
        return btn

    def _setup_ui(self) -> None:
        self.setAutoFillBackground(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(4)

        pane = self._pane
        for action_id, normal_name, hover_name, tooltip, checkable in _TOOLBAR_ACTIONS:
            btn = self._make_icon_button(
                action_id=action_id,
                tooltip=tooltip,
                normal_name=normal_name,
                hover_name=hover_name,
                on_click=lambda _checked=False, aid=action_id: pane.trigger_chat_toolbar_action(
                    aid
                ),
                checkable=checkable,
            )
            self._buttons[action_id] = btn

        for action_id, *_rest in _LEFT_TOOLBAR_ACTIONS:
            root.addWidget(self._buttons[action_id])

        root.addStretch(1)

        for action_id, *_rest in _RIGHT_TOOLBAR_ACTIONS:
            root.addWidget(self._buttons[action_id])

        self.refresh_theme_styles()

    def button(self, action_id: str) -> Optional[QPushButton]:
        return self._buttons.get(action_id)

    def set_copy_images_checked(self, checked: bool) -> None:
        btn = self._buttons.get("copy_images")
        if btn is not None:
            btn.setChecked(bool(checked))

    def set_toolbar_visible(self, visible: bool) -> None:
        self.setVisible(bool(visible))

    def action_icon(self, action_id: str) -> QIcon:
        btn = self._buttons.get(action_id)
        if btn is not None:
            return btn.icon()
        return QIcon()

    def refresh_theme_styles(self) -> None:
        th = get_active_theme()
        self.setStyleSheet(th.file_tree_nav_container_stylesheet())
        copy_btn = self._buttons.get("copy_images")
        copy_checked = bool(copy_btn.isChecked()) if copy_btn is not None else False
        for action_id, btn in self._buttons.items():
            highlighted = action_id == "copy_images" and copy_checked
            btn.setStyleSheet(
                info_action_button_stylesheet(
                    highlighted=highlighted,
                    text_button=False,
                )
            )
        for action_id, normal_name, hover_name, _tooltip, _checkable in _TOOLBAR_ACTIONS:
            normal, hover = icon_pair_from_assets(normal_name, hover_name)
            swap = self._icon_hovers.get(action_id)
            if swap is not None:
                swap.set_icons(normal, hover)
