#!/usr/bin/env python3
"""Shared horizontal action bar for File Information and related panes."""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from theme.theme_service import get_active_theme
from thumbnails.thumbnail_constants import ALT_SYMBOL, COPY_SYMBOL
from widgets.icon_hover_swap import IconHoverSwap, attach_icon_hover_swap, icon_pair_from_assets

INFO_ACTION_ICON_PX = 18
INFO_ACTION_BTN_PX = 26
INFO_NAV_ACTION_ORDER = ("edit", "copy", "speak", "delete", "create", "editai")
INFO_NAV_ACTION_ORDER_NO_EDIT = ("copy", "speak", "delete", "create", "editai")

INFO_ACTION_TOOLTIPS = {
    "speak": "Read aloud (click again to stop)",
    "copy": (
        f"Copy prompt to clipboard.\n"
        f"{ALT_SYMBOL}+click to copy full user comment."
    ),
    "edit": "Edit user comment",
    "create": "Create image from this prompt",
    "editai": "Edit this image with AI",
    "delete": "Delete user comment",
}

_IMAGE_ACTION_IDS = frozenset({"edit", "create", "editai", "delete"})
_IMAGE_ICON_PATHS = {
    "edit": ("comment_icon.png", "comment_icon_hover.png"),
    "create": ("fromText.png", "fromText_hover.png"),
    "editai": ("editAI.png", "editAI_hover.png"),
    "delete": ("trash_icon.png", "trash_icon_hover.png"),
}
_TEXT_ACTION_SYMBOLS = {
    "copy": COPY_SYMBOL,
    "speak": "꡴",
}


def info_action_chip_button_stylesheet(*, highlighted: bool = False) -> str:
    th = get_active_theme()
    border = (
        getattr(th, "button_border_hover_hex", th.accent_color_hex)
        if highlighted
        else th.information_icon_cell_border_muted_hex
    )
    fg = (
        getattr(th, "button_border_hover_hex", th.accent_color_hex)
        if highlighted
        else th.information_action_icon_muted_hex
    )
    hover_border = getattr(th, "button_border_hover_hex", th.accent_color_hex)
    px = INFO_ACTION_BTN_PX
    return f"""
        QPushButton {{
            background-color: {th.information_action_chip_bg_hex};
            border: 1px solid {border};
            border-radius: 6px;
            color: {fg};
            padding: 0px;
            font-size: 14px;
            min-width: {px}px;
            max-width: {px}px;
            min-height: {px}px;
            max-height: {px}px;
        }}
        QPushButton:hover {{
            border-color: {hover_border};
            color: {hover_border};
        }}
        QPushButton:disabled {{
            color: {th.text_disabled_hex};
            border-color: {th.information_icon_cell_border_muted_hex};
        }}
    """


def info_action_image_button_stylesheet(*, highlighted: bool = False) -> str:
    th = get_active_theme()
    border = (
        getattr(th, "button_border_hover_hex", th.accent_color_hex)
        if highlighted
        else th.information_icon_cell_border_muted_hex
    )
    hover_border = getattr(th, "button_border_hover_hex", th.accent_color_hex)
    px = INFO_ACTION_BTN_PX
    return f"""
        QPushButton {{
            background-color: {th.information_action_chip_bg_hex};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 0px;
            min-width: {px}px;
            max-width: {px}px;
            min-height: {px}px;
            max-height: {px}px;
        }}
        QPushButton:hover {{
            border-color: {hover_border};
        }}
        QPushButton:disabled {{
            border-color: {th.information_icon_cell_border_muted_hex};
        }}
    """


class InformationActionNavBar(QWidget):
    """Horizontal row of File Information action buttons."""

    action_triggered = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        action_order: Iterable[str] = INFO_NAV_ACTION_ORDER,
        include_stretch: bool = True,
        contents_margins: tuple[int, int, int, int] = (0, 4, 0, 0),
    ):
        super().__init__(parent)
        self._action_order = tuple(action_order)
        self._include_stretch = include_stretch
        self._buttons: Dict[str, QPushButton] = {}
        self._speak_highlighted = False
        self._icon_hovers: Dict[str, IconHoverSwap] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(*contents_margins)
        layout.setSpacing(4)

        for action_id in self._action_order:
            text = _TEXT_ACTION_SYMBOLS.get(action_id, "")
            btn = QPushButton(text)
            btn.setToolTip(INFO_ACTION_TOOLTIPS.get(action_id, ""))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(INFO_ACTION_BTN_PX, INFO_ACTION_BTN_PX)
            if text:
                btn.setIconSize(QSize(INFO_ACTION_ICON_PX, INFO_ACTION_ICON_PX))
            else:
                btn.setIconSize(QSize(INFO_ACTION_ICON_PX, INFO_ACTION_ICON_PX))
            btn.clicked.connect(
                lambda _checked=False, aid=action_id: self.action_triggered.emit(aid)
            )
            self._buttons[action_id] = btn
            layout.addWidget(btn)

        if include_stretch:
            layout.addStretch(1)

        self.refresh_theme_styles()

    def button(self, action_id: str) -> Optional[QPushButton]:
        return self._buttons.get(action_id)

    def apply_specs(self, specs: Dict[str, Dict[str, object]]) -> bool:
        """Apply visibility/enabled state. Returns True when any button is visible."""
        any_visible = False
        for action_id, btn in self._buttons.items():
            spec = specs.get(action_id, {})
            visible = bool(spec.get("visible", True))
            btn.setVisible(visible)
            btn.setEnabled(bool(spec.get("enabled", True)))
            if visible:
                any_visible = True
        return any_visible

    def set_speak_highlighted(self, highlighted: bool) -> None:
        self._speak_highlighted = bool(highlighted)
        self.refresh_theme_styles()

    def refresh_theme_styles(self) -> None:
        th = get_active_theme()
        self.setStyleSheet(th.file_tree_nav_container_stylesheet())
        for action_id, btn in self._buttons.items():
            if action_id in _IMAGE_ACTION_IDS:
                normal_name, hover_name = _IMAGE_ICON_PATHS[action_id]
                normal, hover = icon_pair_from_assets(normal_name, hover_name)
                swap = self._icon_hovers.get(action_id)
                if swap is None:
                    self._icon_hovers[action_id] = attach_icon_hover_swap(btn, normal, hover)
                else:
                    swap.set_icons(normal, hover)
                btn.setStyleSheet(info_action_image_button_stylesheet())
            else:
                highlighted = self._speak_highlighted if action_id == "speak" else False
                btn.setStyleSheet(
                    info_action_chip_button_stylesheet(highlighted=highlighted)
                )
