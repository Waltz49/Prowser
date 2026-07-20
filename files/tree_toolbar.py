#!/usr/bin/env python3
"""File tree pane toolbar: left nav actions and right filter mode controls."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from theme.theme_service import get_active_theme
from widgets.gear_button_styles import create_tree_toolbar_gear_button
from widgets.icon_hover_swap import IconHoverSwap, attach_icon_hover_swap

_TOOLBAR_BTN_PX = 26
_ICON_PX = 20

_FILTER_MODES = (
    ("all", "Filtering: None\nShow all folders regardless of image content"),
    ("images", "Filtering: Has Images\nOnly display folders that contain at least one image"),
    (
        "use_filter",
        "Filtering: Pattern Matching\nOnly display folders with images matching the filter pattern in Settings",
    ),
)


def create_tree_filter_icon(mode: str, selected: bool, *, hover: bool = False) -> QIcon:
    """Pen-drawn filter mode icon (all / images / pattern)."""
    icon_pixmap_size = 18
    pixmap = QPixmap(icon_pixmap_size, icon_pixmap_size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    th = get_active_theme()
    if selected:
        pen_color = QColor(th.file_tree_filter_icon_selected_hex)
    elif hover:
        pen_color = QColor(th.file_tree_filter_icon_selected_hex)
    else:
        pen_color = QColor(th.file_tree_filter_icon_unselected_hex)
    pen_width = 1.5

    if mode == "all":
        painter.setPen(QPen(pen_color, pen_width))
        painter.drawLine(4, 4, 14, 14)
        painter.drawLine(14, 4, 4, 14)
    elif mode == "images":
        painter.setPen(QPen(pen_color, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(5, 5, 8, 8)
    elif mode == "use_filter":
        painter.setPen(QPen(pen_color, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPoint(5, 4), QPoint(14, 4))
        painter.drawLine(QPoint(5, 4), QPoint(8, 10))
        painter.drawLine(QPoint(8, 10), QPoint(8, 15))
        painter.drawLine(QPoint(14, 4), QPoint(10, 10))
        painter.drawLine(QPoint(10, 10), QPoint(10, 15))
        painter.drawLine(QPoint(8, 15), QPoint(10, 15))

    painter.end()
    return QIcon(pixmap)


def filter_toolbar_button_stylesheet(
    theme: Any, focus_bg: str, focus_border: str, focus_text: str
) -> str:
    base = theme.file_tree_nav_icon_button_stylesheet(
        focus_bg, focus_border, focus_text, dim=False
    )
    pressed = (
        QColor(theme._file_tree_control_surface_hex()).darker(112).name()
        if theme.theme_id == "light"
        else QColor(theme._file_tree_control_surface_hex()).lighter(108).name()
    )
    hover = theme._file_tree_control_surface_hover_hex()
    hover_border = getattr(theme, "button_border_hover_hex", theme.current_image_border_color_hex)
    return (
        base
        + f"""
            QPushButton:hover {{
                border: 1px solid {hover_border};
            }}
            QPushButton:checked {{
                background-color: {pressed};
            }}
            QPushButton:checked:hover {{
                background-color: {hover};
                border: 1px solid {hover_border};
            }}
        """
    )


class FileTreeToolbar(QWidget):
    """Tree pane toolbar: three left actions, three right filter toggles."""

    def __init__(self, handler: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._handler = handler
        self.collapse_all_button: Optional[QPushButton] = None
        self.rename_status_button: Optional[QPushButton] = None
        self.settings_button: Optional[QPushButton] = None
        self._filter_mode_buttons: Dict[str, QPushButton] = {}
        self._filter_mode_group: Optional[QButtonGroup] = None
        self._icon_hovers: Dict[str, IconHoverSwap] = {}
        self._setup_ui()

    def _nav_button_stylesheet(self) -> str:
        from utils import get_button_focus_colors

        focus_bg, focus_border, focus_text = get_button_focus_colors()
        th = get_active_theme()
        hover_border = getattr(th, "button_border_hover_hex", th.current_image_border_color_hex)
        base = th.file_tree_nav_icon_button_stylesheet(
            focus_bg, focus_border, focus_text, dim=False
        )
        return base + f"""
            QPushButton:hover {{
                border: 1px solid {hover_border};
            }}
        """

    def _make_icon_button(
        self,
        *,
        tooltip: str,
        on_click: Callable[[], None],
        icon: QIcon | None = None,
        hover_icon: QIcon | None = None,
        checkable: bool = False,
        filter_stylesheet: str | None = None,
        hover_key: str | None = None,
    ) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(_TOOLBAR_BTN_PX, _TOOLBAR_BTN_PX)
        btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        if icon is not None:
            btn.setIcon(icon)
        if checkable:
            btn.setCheckable(True)
        btn.clicked.connect(on_click)
        if filter_stylesheet is not None:
            btn.setStyleSheet(filter_stylesheet)
        else:
            btn.setStyleSheet(self._nav_button_stylesheet())
        if hover_key and icon is not None and hover_icon is not None:
            self._icon_hovers[hover_key] = attach_icon_hover_swap(btn, icon, hover_icon)
        return btn

    def set_rename_status_icons(self, normal_icon: QIcon, hover_icon: QIcon) -> None:
        """Update rename-status toggle icons (normal + hover)."""
        if self.rename_status_button is None:
            return
        swap = self._icon_hovers.get("rename_status")
        if swap is None:
            swap = attach_icon_hover_swap(
                self.rename_status_button, normal_icon, hover_icon
            )
            self._icon_hovers["rename_status"] = swap
        swap.set_icons(normal_icon, hover_icon)

    def _setup_ui(self) -> None:
        self.setAutoFillBackground(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 5)
        root.setSpacing(0)

        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        handler = self._handler
        th = get_active_theme()
        squeeze_normal = handler._create_squeeze_icon(th.file_tree_nav_button_text_dim_hex)
        squeeze_hover = handler._create_squeeze_icon(th.file_tree_nav_button_text_hex)

        self.collapse_all_button = self._make_icon_button(
            tooltip="Collapse to home directory\nCollapse all and expand to home directory",
            on_click=handler.collapse_all,
            icon=squeeze_normal,
            hover_icon=squeeze_hover,
            hover_key="collapse",
        )
        self.rename_status_button = self._make_icon_button(
            tooltip=(
                "Toggle Rename Status Check\n"
                "Check if files matching filter pattern also match rename pattern "
                "and are sequentially numbered"
            ),
            on_click=handler._toggle_rename_status,
            hover_key="rename_status",
        )
        self.settings_button = create_tree_toolbar_gear_button(
            tooltip="Open Settings\nConfigure application preferences",
        )
        self.settings_button.clicked.connect(handler.open_settings_to_max_images)
        left.addWidget(self.collapse_all_button)
        left.addWidget(self.rename_status_button)
        left.addWidget(self.settings_button)

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)

        from utils import get_button_focus_colors

        theme = get_active_theme()
        focus_bg, focus_border, focus_text = get_button_focus_colors()
        filter_btn_ss = filter_toolbar_button_stylesheet(
            theme, focus_bg, focus_border, focus_text
        )

        current_mode = "images"
        if getattr(handler, "filter_proxy", None):
            current_mode = handler.filter_proxy.normalize_filtered_tree_mode()

        self._filter_mode_group = QButtonGroup(self)
        self._filter_mode_group.setExclusive(True)

        for mode, tooltip in _FILTER_MODES:
            normal = create_tree_filter_icon(mode, current_mode == mode, hover=False)
            hover = create_tree_filter_icon(mode, current_mode == mode, hover=True)
            btn = self._make_icon_button(
                tooltip=tooltip,
                on_click=lambda _checked=False, m=mode: handler._on_tree_filter_mode_selected(m),
                icon=normal,
                hover_icon=hover,
                checkable=True,
                filter_stylesheet=filter_btn_ss,
                hover_key=f"filter_{mode}",
            )
            btn.setChecked(current_mode == mode)
            self._filter_mode_buttons[mode] = btn
            self._filter_mode_group.addButton(btn)
            right.addWidget(btn)

        root.addLayout(left)
        root.addStretch(1)
        root.addLayout(right)
        self.refresh_theme_styles()

    def set_toolbar_visible(self, visible: bool) -> None:
        self.setVisible(bool(visible))

    def redraw_filter_icons(self) -> None:
        handler = self._handler
        if not getattr(handler, "filter_proxy", None):
            return
        mode = handler.filter_proxy.normalize_filtered_tree_mode()
        for m, btn in self._filter_mode_buttons.items():
            selected = mode == m
            btn.setChecked(selected)
            normal = create_tree_filter_icon(m, selected, hover=False)
            hover = create_tree_filter_icon(m, selected, hover=True)
            swap = self._icon_hovers.get(f"filter_{m}")
            if swap is not None:
                swap.set_icons(normal, hover)
            else:
                btn.setIcon(normal)

    def refresh_theme_styles(self) -> None:
        theme = get_active_theme()
        self.setStyleSheet(theme.file_tree_nav_container_stylesheet())
        nav_ss = self._nav_button_stylesheet()
        from utils import get_button_focus_colors

        focus_bg, focus_border, focus_text = get_button_focus_colors()
        filter_btn_ss = filter_toolbar_button_stylesheet(
            theme, focus_bg, focus_border, focus_text
        )
        for btn in (
            self.collapse_all_button,
            self.rename_status_button,
        ):
            if btn is not None:
                btn.setStyleSheet(nav_ss)
        if self.settings_button is not None:
            from widgets.gear_button_styles import tree_toolbar_gear_button_stylesheet

            self.settings_button.setStyleSheet(tree_toolbar_gear_button_stylesheet())
        for btn in self._filter_mode_buttons.values():
            if btn is not None:
                btn.setStyleSheet(filter_btn_ss)
        self.redraw_filter_icons()
        handler = self._handler
        if hasattr(handler, "update_rename_status_button_icon"):
            handler.update_rename_status_button_icon()
        if self.collapse_all_button is not None:
            squeeze_normal = handler._create_squeeze_icon(theme.file_tree_nav_button_text_dim_hex)
            squeeze_hover = handler._create_squeeze_icon(theme.file_tree_nav_button_text_hex)
            swap = self._icon_hovers.get("collapse")
            if swap is not None:
                swap.set_icons(squeeze_normal, squeeze_hover)

    def action_icon(self, action_id: str) -> QIcon:
        mapping = {
            "collapse": self.collapse_all_button,
            "rename_status": self.rename_status_button,
            "settings": self.settings_button,
        }
        btn = mapping.get(action_id)
        if btn is not None:
            return btn.icon()
        filter_map = {
            "filter_all": "all",
            "filter_images": "images",
            "filter_use_filter": "use_filter",
        }
        mode = filter_map.get(action_id)
        if mode and mode in self._filter_mode_buttons:
            return self._filter_mode_buttons[mode].icon()
        return QIcon()
