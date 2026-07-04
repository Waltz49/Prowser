#!/usr/bin/env python3
"""Fixed chrome palette for the settings dialog (independent of dialog_background_hex)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from theme.theme import push_button_stylesheet, macos_scrollbar_stylesheet
from theme.theme_service import get_active_theme

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
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QRadioButton {{
        color: {c.text_hex};
        spacing: 6px;
    }}
    #{_SETTINGS_DIALOG_OBJECT_NAME} QCheckBox::indicator,
    #{_SETTINGS_DIALOG_OBJECT_NAME} QRadioButton::indicator {{
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
