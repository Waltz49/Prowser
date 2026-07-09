#!/usr/bin/env python3
"""Shared chat pane styling and icon action buttons."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPalette, QPixmap, qGray
from PySide6.QtWidgets import QFrame, QGroupBox, QPushButton

from config import job_queue_cell_background_hex
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

_ICON_BTN_SIZE = 22
_ICON_DISPLAY_PX = 14
MAX_CHAT_IMAGES = 4
CHAT_THUMB_PX = 64


def chat_user_message_stylesheet() -> str:
    th = get_active_theme()
    bg = job_queue_cell_background_hex()
    border = th.groupbox_border_hex
    return f"""
        QGroupBox#chatUserBubble {{
            font-weight: normal;
            color: {th.dialog_text_color_hex};
            background-color: {bg};
            border: 2px solid {border};
            border-radius: 8px;
            margin: 0px;
            margin-top: 0px;
            padding: 8px;
        }}
        QGroupBox#chatUserBubble::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0px;
            margin: 0px;
            height: 0px;
            border: none;
        }}
    """


def apply_chat_user_bubble_chrome(group: QGroupBox) -> None:
    """Paint user bubble like a group box (visible border on sidebar panes)."""
    th = get_active_theme()
    bg = job_queue_cell_background_hex()
    color = QColor(bg)
    if not color.isValid():
        color = QColor(th.sidebar_background_color_hex).lighter(110)
    group.setTitle("")
    group.setFlat(False)
    palette = group.palette()
    palette.setColor(QPalette.ColorRole.Window, color)
    group.setPalette(palette)
    group.setAutoFillBackground(True)
    group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    group.setStyleSheet(chat_user_message_stylesheet())


def chat_assistant_message_stylesheet() -> str:
    return """
        QFrame#chatAssistantBubble {
            background-color: transparent;
            border: none;
        }
    """


def chat_prompt_edit_stylesheet() -> str:
    th = get_active_theme()
    return f"""
        QPlainTextEdit {{
            background-color: {th.sidebar_background_color_hex};
            color: {th.dialog_text_color_hex};
            border: 1px solid {th.border_default_hex};
            border-radius: 6px;
            padding: 6px;
        }}
    """


def _icon_button_chrome_stylesheet() -> str:
    th = get_active_theme()
    sz = _ICON_BTN_SIZE
    btn_bg = th.sidebar_background_color_hex
    btn_hover = th.widget_bg_hover_hex
    return f"""
        QPushButton {{
            background-color: {btn_bg};
            border: 1px solid {th.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton:hover {{
            background-color: {btn_hover};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def _load_icon_pixmap(icon_name: str, size_px: int) -> QPixmap:
    pixmap = QPixmap(asset_path(icon_name))
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        size_px,
        size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _grayscale_pixmap(pixmap: QPixmap) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() == 0:
                continue
            gray = qGray(color.rgb())
            image.setPixelColor(x, y, QColor(gray, gray, gray, color.alpha()))
    return QPixmap.fromImage(image)


class _ChatIconButtonHover(QObject):
    def __init__(
        self,
        button: QPushButton,
        normal_icon: QIcon,
        hover_icon: QIcon,
    ) -> None:
        super().__init__(button)
        self._button = button
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._button:
            if event.type() == QEvent.Type.HoverEnter:
                self._button.setIcon(self._hover_icon)
            elif event.type() == QEvent.Type.HoverLeave:
                self._button.setIcon(self._normal_icon)
        return False


def _create_chat_icon_button(
    parent,
    icon_name: str,
    *,
    hover_icon_name: str | None = None,
    tooltip: str = "",
) -> QPushButton:
    btn = QPushButton(parent)
    btn.setToolTip(tooltip)
    icon_px = _ICON_DISPLAY_PX
    base = _load_icon_pixmap(icon_name, icon_px)
    hover_name = hover_icon_name or icon_name.replace(".png", "_hover.png")
    hover_pm = (
        _load_icon_pixmap(hover_name, icon_px)
        if os.path.isfile(asset_path(hover_name))
        else base
    )
    normal_icon = QIcon(_grayscale_pixmap(base))
    hover_icon = QIcon(hover_pm)
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setIcon(normal_icon)
    btn.setIconSize(QSize(icon_px, icon_px))
    btn.setStyleSheet(_icon_button_chrome_stylesheet())
    _ChatIconButtonHover(btn, normal_icon, hover_icon)
    return btn


def create_chat_edit_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "edit_icon.png",
        tooltip="Edit message",
    )


def create_chat_redo_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "dim_reverse_icon.png",
        tooltip="Regenerate response",
    )


def create_chat_delete_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "trash_icon.png",
        hover_icon_name="trash_icon_hover.png",
        tooltip="Delete message",
    )


def create_chat_from_text_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "fromText.png",
        hover_icon_name="fromText_hover.png",
        tooltip="Create an image from text with this message as the prompt",
    )


def chat_create_from_text_available() -> bool:
    try:
        from imagegen_plugins.image_gen_menu import imagegen_create_from_text_available

        return imagegen_create_from_text_available()
    except ImportError:
        return False
