#!/usr/bin/env python3
"""Fixed chrome palette for the settings dialog (independent of dialog_background_hex)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from thumbnails.thumbnail_constants import asset_path
from theme.theme import (
    dialog_radio_button_stylesheet,
    macos_scrollbar_stylesheet,
    push_button_stylesheet,
)
from theme.theme_service import get_active_theme
from widgets.gear_icon_button import GearIconButton

_SETTINGS_DIALOG_OBJECT_NAME = "settingsDialog"


@dataclass(frozen=True)
class SettingsDialogChrome:
    bg_hex: str
    text_hex: str
    header_hex: str
    text_disabled_hex: str
    control_bg_hex: str
    control_border_hex: str
    control_text_hex: str
    control_hover_bg_hex: str
    control_hover_border_hex: str
    control_hover_text_hex: str
    groupbox_border_hex: str
    tab_hover_bg_hex: str
    tab_checked_bg_hex: str
    focus_border_hex: str


_DARK_USER_CHROME = SettingsDialogChrome(
    bg_hex="#000000",
    text_hex="#e2e2e2",
    header_hex="#f0f0f0",
    text_disabled_hex="#888888",
    control_bg_hex="#16181c",
    control_border_hex="#38506b",
    control_text_hex="#b0bfd6",
    control_hover_bg_hex="#263447",
    control_hover_border_hex="#41a6c6",
    control_hover_text_hex="#bbecff",
    groupbox_border_hex="#606060",
    tab_hover_bg_hex="#263447",
    tab_checked_bg_hex="#16181c",
    focus_border_hex="#87ceeb",
)

_LIGHT_CHROME = SettingsDialogChrome(
    bg_hex="#ececec",
    text_hex="#1a1a1a",
    header_hex="#1a1a1a",
    text_disabled_hex="#888888",
    control_bg_hex="#ffffff",
    control_border_hex="#b8b8b8",
    control_text_hex="#1a2a3a",
    control_hover_bg_hex="#dde8f4",
    control_hover_border_hex="#4a7aaa",
    control_hover_text_hex="#0a1a2a",
    groupbox_border_hex="#b0b0b0",
    tab_hover_bg_hex="#e4e4e4",
    tab_checked_bg_hex="#d0d8e8",
    focus_border_hex="#2b6cb0",
)


def settings_chrome_for_preset(preset_id: str) -> SettingsDialogChrome:
    """Return settings-dialog chrome for dark, user, or light preset."""
    if preset_id == "light":
        return _LIGHT_CHROME
    return _DARK_USER_CHROME


def resolve_settings_chrome_from_widget(widget: Any) -> SettingsDialogChrome:
    """Walk parents for SettingsDialog._settings_chrome(); default to dark/user chrome."""
    host = widget
    while host is not None:
        getter = getattr(host, "_settings_chrome", None)
        if callable(getter):
            return getter()
        host = host.parent()
    return _DARK_USER_CHROME


_SETTINGS_GEAR_BTN_SIZE = 22
_SETTINGS_GEAR_ICON_PX = 18


def settings_gear_button_stylesheet(chrome: SettingsDialogChrome) -> str:
    """Small gear icon button for settings preference row titles."""
    sz = _SETTINGS_GEAR_BTN_SIZE
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


class SettingsGearButton(GearIconButton):
    """Gear icon button for opening a related settings or library dialog."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        tooltip: str = "",
    ) -> None:
        super().__init__(
            parent,
            size_px=_SETTINGS_GEAR_BTN_SIZE,
            icon_px=_SETTINGS_GEAR_ICON_PX,
            tooltip=tooltip,
            object_name="settingsPreferenceGearBtn",
        )
        self._refresh_stylesheet()

    def _chrome(self) -> SettingsDialogChrome:
        return resolve_settings_chrome_from_widget(self)

    def _refresh_stylesheet(self) -> None:
        self.setStyleSheet(settings_gear_button_stylesheet(self._chrome()))


def settings_dialog_stylesheet(chrome: SettingsDialogChrome) -> str:
    """Full settings shell stylesheet; overrides global QDialog QWidget dialog fill."""
    c = chrome
    t = get_active_theme()
    disabled_btn_border = c.groupbox_border_hex if c.bg_hex != "#000000" else c.bg_hex
    return f"""
    #{_SETTINGS_DIALOG_OBJECT_NAME},
    #{_SETTINGS_DIALOG_OBJECT_NAME} QWidget {{
        background-color: {c.bg_hex};
        color: {c.text_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel {{
        background-color: transparent;
        color: {c.text_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QToolTip {{
        background-color: {t.qtooltip_bg_hex};
        color: {t.qtooltip_fg_hex};
        border: 1px solid {t.qtooltip_border_hex};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QGroupBox {{
        color: {c.header_hex};
        border: 1px solid {c.groupbox_border_hex};
        border-radius: 4px;
        margin-top: 10px;
        padding-top: 8px;
        font-weight: bold;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QGroupBox::title {{
        color: {c.header_hex};
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLineEdit,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QTextEdit,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QPlainTextEdit,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QSpinBox,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QDoubleSpinBox,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QComboBox {{
        background-color: {c.control_bg_hex};
        color: {c.control_text_hex};
        border: 1px solid {c.control_border_hex};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLineEdit:focus,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QTextEdit:focus,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QPlainTextEdit:focus,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QSpinBox:focus,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QDoubleSpinBox:focus,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QComboBox:focus {{
        border: 1px solid {c.focus_border_hex};
        outline: none;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLineEdit:hover,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QComboBox:hover {{
        border: 1px solid {c.control_hover_border_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QSpinBox,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QDoubleSpinBox {{
        padding: 4px 16px 4px 8px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox {{
        background-color: {c.control_bg_hex};
        color: {c.control_text_hex};
        border: 1px solid {c.control_border_hex};
        border-radius: 4px;
        margin-left: 0px;
        font-size: 13px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox[hasFocus="true"] {{
        border: 1px solid {c.focus_border_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QLineEdit#StepSpinEdit {{
        border: none;
        background: transparent;
        color: {c.control_text_hex};
        padding: 4px 4px 4px 6px;
        margin: 0px;
        selection-background-color: {c.focus_border_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QWidget#StepSpinButtons {{
        background: transparent;
        min-width: 12px;
        max-width: 12px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QToolButton#StepSpinUpButton,
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QToolButton#StepSpinDownButton {{
        border: none;
        border-left: 1px solid {c.control_border_hex};
        background: transparent;
        padding: 0px;
        margin: 0px;
        min-width: 12px;
        max-width: 12px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QToolButton#StepSpinUpButton {{
        border-bottom: 1px solid {c.control_border_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QToolButton#StepSpinUpButton:hover:enabled,
    #{_SETTINGS_DIALOG_OBJECT_NAME} StepSpinBox QToolButton#StepSpinDownButton:hover:enabled {{
        background-color: {c.control_hover_bg_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox {{
        color: {c.text_hex};
        spacing: 6px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox::indicator {{
        background-color: {c.control_bg_hex};
        border: 1px solid {c.control_border_hex};
        width: 11px;
        height: 11px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox::indicator:checked {{
        background-color: {c.control_hover_bg_hex};
        border: 1px solid {c.focus_border_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox::indicator:disabled {{
        background-color: {c.bg_hex};
        border: 1px solid {c.groupbox_border_hex};
    }}
    {dialog_radio_button_stylesheet(
        t,
        selector=f"#{_SETTINGS_DIALOG_OBJECT_NAME} QRadioButton",
        text_hex=c.text_hex,
    )}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QFrame#macPreferencePanel {{
        background-color: {c.control_bg_hex};
        border: 1px solid {c.groupbox_border_hex};
        border-radius: 10px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel#macPreferenceSectionTitle {{
        color: {c.text_disabled_hex};
        font-size: 11px;
        font-weight: 600;
        padding: 2px 4px 6px 4px;
        background-color: transparent;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel#macPreferenceRowTitle {{
        color: {c.text_hex};
        font-size: 13px;
        background-color: transparent;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel#macPreferenceRowSubtitle {{
        color: {c.text_disabled_hex};
        font-size: 11px;
        background-color: transparent;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel#macPreferenceRowTitle:disabled,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QLabel#macPreferenceRowSubtitle:disabled {{
        color: {c.text_disabled_hex};
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QFrame#macPreferenceDivider {{
        background-color: {c.groupbox_border_hex};
        border: none;
        margin-left: 20px;
        max-height: 1px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QScrollArea {{
        background-color: {c.bg_hex};
        border: none;
    }}
    {macos_scrollbar_stylesheet(
        track_bg_hex=c.bg_hex,
        handle_hex=c.control_border_hex,
        handle_hover_hex=c.control_hover_border_hex,
        selector_prefix=f"#{_SETTINGS_DIALOG_OBJECT_NAME}",
    )}
    """ + push_button_stylesheet(
        t,
        selector=f"#{_SETTINGS_DIALOG_OBJECT_NAME} QPushButton",
        min_width="0px",
        padding="6px 12px",
        pressed_text_hex=c.control_hover_text_hex,
    ) + f"""
    #{_SETTINGS_DIALOG_OBJECT_NAME} QPushButton:disabled {{
        border-color: {disabled_btn_border};
    }}
    """


def settings_dialog_tooltip_label_stylesheet(chrome: SettingsDialogChrome) -> str:
    """Opaque floating tooltip for settings controls (native QToolTip is unreliable on macOS)."""
    c = chrome
    return f"""
    QLabel {{
        background-color: {c.control_bg_hex};
        color: {c.control_text_hex};
        border: 1px solid {c.control_border_hex};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    """
