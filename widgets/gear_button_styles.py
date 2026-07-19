"""Themed gear-button presets for chat, dialog, and settings contexts."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from theme.theme_service import get_active_theme
from widgets.gear_icon_button import GearIconButton

if TYPE_CHECKING:
    from settings.widgets.settings_dialog_theme import SettingsDialogChrome

CHAT_GEAR_BTN_SIZE = 26
CHAT_GEAR_ICON_PX = 18
DIALOG_GEAR_BTN_SIZE = 24
DIALOG_GEAR_ICON_PX = 16


def chat_gear_button_stylesheet() -> str:
    t = get_active_theme()
    sz = CHAT_GEAR_BTN_SIZE
    return f"""
        QPushButton#chatSystemPromptGearBtn {{
            background-color: {t.dialog_background_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton#chatSystemPromptGearBtn:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton#chatSystemPromptGearBtn:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
        }}
        QPushButton#chatSystemPromptGearBtn:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
    """


def dialog_gear_button_stylesheet() -> str:
    t = get_active_theme()
    sz = DIALOG_GEAR_BTN_SIZE
    return f"""
        QPushButton#dialogGearBtn {{
            background-color: {t.button_bg_default_hex};
            border: 1px solid {t.button_border_default_hex};
            border-radius: 6px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton#dialogGearBtn:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton#dialogGearBtn:hover {{
            background-color: {t.button_bg_hover_hex};
            border: 1px solid {t.button_border_hover_hex};
        }}
    """


def settings_gear_button_stylesheet(chrome: "SettingsDialogChrome") -> str:
    sz = 22
    return f"""
        QPushButton#settingsPreferenceGearBtn {{
            background-color: {chrome.control_bg_hex};
            border: 1px solid {chrome.control_border_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton#settingsPreferenceGearBtn:focus {{
            border: 1px solid {chrome.focus_border_hex};
            outline: none;
        }}
        QPushButton#settingsPreferenceGearBtn:hover {{
            background-color: {chrome.control_hover_bg_hex};
            border: 1px solid {chrome.control_hover_border_hex};
        }}
        QPushButton#settingsPreferenceGearBtn:pressed {{
            background-color: {chrome.tab_checked_bg_hex};
        }}
    """


def create_chat_gear_button(
    parent: Optional[QWidget] = None,
    *,
    tooltip: str = "",
) -> GearIconButton:
    return GearIconButton(
        parent,
        size_px=CHAT_GEAR_BTN_SIZE,
        icon_px=CHAT_GEAR_ICON_PX,
        tooltip=tooltip,
        object_name="chatSystemPromptGearBtn",
        stylesheet=chat_gear_button_stylesheet(),
    )


def create_dialog_gear_button(
    parent: Optional[QWidget] = None,
    *,
    tooltip: str = "",
) -> GearIconButton:
    return GearIconButton(
        parent,
        size_px=DIALOG_GEAR_BTN_SIZE,
        icon_px=DIALOG_GEAR_ICON_PX,
        tooltip=tooltip,
        object_name="dialogGearBtn",
        stylesheet=dialog_gear_button_stylesheet(),
    )
