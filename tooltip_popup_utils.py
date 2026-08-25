#!/usr/bin/env python3
"""Position custom floating QLabel tooltips away from the cursor and on-screen."""

from __future__ import annotations

import re
from typing import Callable

from shiboken6 import isValid

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QUrl
from PySide6.QtGui import QCursor, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

TOOLTIP_MARGIN = 10
_OFFSET_X = 12
_OFFSET_Y = 20
GRAPHIC_TOOLTIP_ICON_PX = 48
_GRAPHIC_TOOLTIP_TEXT_MAX_WIDTH = 320
_GRAPHIC_TOOLTIP_MARGIN_LEFT = 6
_GRAPHIC_TOOLTIP_MARGIN_TOP = 6
_GRAPHIC_TOOLTIP_MARGIN_RIGHT = 8
_GRAPHIC_TOOLTIP_MARGIN_BOTTOM = 6
_GRAPHIC_TOOLTIP_SPACING = 8
_CSS_IMAGE_URL_RE = re.compile(r"image\s*:\s*url\(([^)]+)\)", re.IGNORECASE)
_ICON_BUTTON_TYPES = (QPushButton, QToolButton)


def clamp_bounds_for_widget(widget: QWidget | None) -> QRect:
    """Global rect to keep the popup inside (host window, else screen)."""
    if widget is not None:
        win = widget.window()
        if win is not None and win.isVisible() and not isinstance(win, QMenu):
            return win.frameGeometry()
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is not None:
        return screen.availableGeometry()
    return QRect(0, 0, 1920, 1080)


def clamp_popup_position(
    global_pos: QPoint, size, bounds: QRect, *, margin: int = TOOLTIP_MARGIN
) -> QPoint:
    x, y = global_pos.x(), global_pos.y()
    left = bounds.left() + margin
    top = bounds.top() + margin
    right = bounds.right() - margin - size.width()
    bottom = bounds.bottom() - margin - size.height()
    return QPoint(max(left, min(x, right)), max(top, min(y, bottom)))


def position_tooltip_near_cursor(
    label: QWidget,
    *,
    clamp_widget: QWidget | None = None,
    margin: int = TOOLTIP_MARGIN,
    offset_x: int = _OFFSET_X,
    offset_y: int = _OFFSET_Y,
) -> QPoint:
    """Place ``label`` below-right of the cursor; flip and clamp if needed."""
    bounds = clamp_bounds_for_widget(clamp_widget)
    cursor = QCursor.pos()
    size = label.sizeHint() if not label.isVisible() else label.size()

    x = cursor.x() + offset_x
    y = cursor.y() + offset_y
    if x + size.width() > bounds.right() - margin:
        x = cursor.x() - size.width() - offset_x
    if y + size.height() > bounds.bottom() - margin:
        y = cursor.y() - size.height() - offset_y

    pos = clamp_popup_position(QPoint(x, y), size, bounds, margin=margin)
    label.move(pos)
    return pos


def ensure_tooltip_label(
    owner: QWidget,
    attr_name: str,
    *,
    window_flags: Qt.WindowType = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint,
) -> QLabel:
    """Return a lazily created floating tooltip QLabel stored on ``owner``."""
    lbl = getattr(owner, attr_name, None)
    if lbl is None:
        lbl = QLabel(None, window_flags)
        lbl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        setattr(owner, attr_name, lbl)
    return lbl


def _graphic_button_tooltip_stylesheet() -> str:
    from theme.theme_service import get_active_theme

    return get_active_theme().graphic_button_tooltip_stylesheet()


def _normalize_css_image_path(raw: str) -> str:
    path = raw.strip().strip('"').strip("'")
    if path.startswith("file://"):
        return QUrl(path).toLocalFile()
    return path


def _stylesheet_image_path(stylesheet: str) -> str | None:
    match = _CSS_IMAGE_URL_RE.search(stylesheet or "")
    if not match:
        return None
    path = _normalize_css_image_path(match.group(1))
    return path or None


def _pixmap_for_tooltip(source: QPixmap, size_px: int) -> QPixmap:
    """Scale to fit within size_px square; normalize DPR for layout sizing."""
    if source.isNull():
        return QPixmap()
    scaled = source.scaled(
        QSize(size_px, size_px),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(1.0)
    return scaled


def _icon_pixmap(icon: QIcon, size_px: int) -> QPixmap:
    target = QSize(size_px, size_px)
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        for state in (QIcon.State.Off, QIcon.State.On):
            pixmap = icon.pixmap(target, mode, state)
            if not pixmap.isNull():
                return _pixmap_for_tooltip(pixmap, size_px)
    return QPixmap()


def _pixmap_from_path(path: str, size_px: int) -> QPixmap:
    return _pixmap_for_tooltip(QPixmap(path), size_px)


def is_graphic_icon_button(widget: QWidget | None) -> bool:
    """True for push/tool buttons styled with an icon or CSS image (not text-only)."""
    if widget is None or not isinstance(widget, _ICON_BUTTON_TYPES):
        return False
    if not widget.icon().isNull():
        return True
    normal_icon = getattr(widget, "_normal_icon", None)
    if isinstance(normal_icon, QIcon) and not normal_icon.isNull():
        return True
    asset_name = widget.property("_tooltip_icon_asset")
    if isinstance(asset_name, str) and asset_name.strip():
        return True
    return bool(_stylesheet_image_path(widget.styleSheet()))


def is_titlebar_tooltip_button(widget: QWidget | None) -> bool:
    """Titlebar chip buttons keep standard text-only tooltips."""
    if widget is None or not isinstance(widget, _ICON_BUTTON_TYPES):
        return False
    if getattr(widget, "_titlebar_icon_swap", None) is not None:
        return True
    host = widget.parentWidget()
    while host is not None:
        if type(host).__name__ == "HeaderWidget":
            return True
        host = host.parentWidget()
    return False


def tooltip_pixmap_for_button(
    button: QWidget, *, size_px: int = GRAPHIC_TOOLTIP_ICON_PX
) -> QPixmap:
    """Return a tooltip-sized pixmap for a graphic button, or a null pixmap."""
    if not isinstance(button, _ICON_BUTTON_TYPES):
        return QPixmap()

    asset_name = button.property("_tooltip_icon_asset")
    if isinstance(asset_name, str) and asset_name.strip():
        from theme.theme_base import asset_path

        pixmap = _pixmap_from_path(asset_path(asset_name.strip()), size_px)
        if not pixmap.isNull():
            return pixmap

    icon = button.icon()
    if icon.isNull():
        normal_icon = getattr(button, "_normal_icon", None)
        if isinstance(normal_icon, QIcon):
            icon = normal_icon
    if not icon.isNull():
        pixmap = _icon_pixmap(icon, size_px)
        if not pixmap.isNull():
            return pixmap

    css_path = _stylesheet_image_path(button.styleSheet())
    if css_path:
        return _pixmap_from_path(css_path, size_px)
    return QPixmap()


class GraphicTooltipPopup(QWidget):
    """Floating tooltip with optional 48x48 icon left of wrapped text."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        window_flags: Qt.WindowType = Qt.WindowType.ToolTip
        | Qt.WindowType.FramelessWindowHint,
    ) -> None:
        super().__init__(parent, window_flags)
        self.setObjectName("graphicButtonTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            _GRAPHIC_TOOLTIP_MARGIN_LEFT,
            _GRAPHIC_TOOLTIP_MARGIN_TOP,
            _GRAPHIC_TOOLTIP_MARGIN_RIGHT,
            _GRAPHIC_TOOLTIP_MARGIN_BOTTOM,
        )
        layout.setSpacing(_GRAPHIC_TOOLTIP_SPACING)
        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("graphicButtonTooltipIcon")
        self._icon_label.setFixedSize(GRAPHIC_TOOLTIP_ICON_PX, GRAPHIC_TOOLTIP_ICON_PX)
        self._icon_label.setContentsMargins(0, 0, 0, 0)
        self._icon_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._text_label = QLabel(self)
        self._text_label.setObjectName("graphicButtonTooltipText")
        self._text_label.setContentsMargins(0, 0, 0, 0)
        self._text_label.setWordWrap(True)
        self._text_label.setMaximumWidth(_GRAPHIC_TOOLTIP_TEXT_MAX_WIDTH)
        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label)

    def show_tip(
        self,
        text: str,
        pixmap: QPixmap,
        *,
        stylesheet: str,
        clamp_widget: QWidget | None = None,
    ) -> None:
        if pixmap.isNull():
            self._icon_label.hide()
            self._icon_label.clear()
        else:
            self._icon_label.setPixmap(pixmap)
            self._icon_label.show()
        self._text_label.setText(text)
        self.setStyleSheet(stylesheet)
        self.adjustSize()
        position_tooltip_near_cursor(self, clamp_widget=clamp_widget)
        self.show()
        self.raise_()


def present_graphic_button_tooltip(
    button: QWidget,
    text: str,
    popup: GraphicTooltipPopup,
    *,
    clamp_widget: QWidget | None = None,
    stylesheet_fn: Callable[[], str] | None = None,
) -> bool:
    """Show icon+text tooltip for graphic buttons. Returns True when handled."""
    tip = (text or "").strip()
    if not tip or not is_graphic_icon_button(button) or is_titlebar_tooltip_button(button):
        return False
    pixmap = tooltip_pixmap_for_button(button)
    if pixmap.isNull():
        return False
    stylesheet = (stylesheet_fn or _graphic_button_tooltip_stylesheet)()
    popup.show_tip(
        tip,
        pixmap,
        stylesheet=stylesheet,
        clamp_widget=clamp_widget or button,
    )
    return True


class IconGraphicTooltipFilter(QObject):
    """App-wide filter: graphic push/tool buttons get icon+text tooltips."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._popup = GraphicTooltipPopup()
        self._source_widget: QWidget | None = None

    def _hide_tooltip(self) -> None:
        if isValid(self._popup):
            self._popup.hide()
        self._source_widget = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not isinstance(obj, QWidget):
            return False

        if event.type() == QEvent.Type.ToolTip and isinstance(obj, _ICON_BUTTON_TYPES):
            tip = obj.toolTip()
            if present_graphic_button_tooltip(obj, tip, self._popup):
                self._source_widget = obj
                return True
            return False

        if event.type() == QEvent.Type.Leave and obj is self._source_widget:
            self._hide_tooltip()
        elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            source = self._source_widget
            if source is None:
                pass
            elif not isValid(source):
                # Button may already be deleted (e.g. parent tear-down).
                self._hide_tooltip()
            elif obj is source or obj is source.window():
                self._hide_tooltip()

        return False


def install_icon_graphic_tooltip_filter(
    parent: QObject | None = None,
) -> IconGraphicTooltipFilter:
    """Install app-wide icon+text tooltips for graphic push/tool buttons."""
    filt = IconGraphicTooltipFilter(parent)
    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(filt)
    return filt


class SettingsDialogTooltipFilter(QObject):
    """Replace native QToolTip in settings with an opaque floating label."""

    def __init__(
        self,
        dialog: QWidget,
        stylesheet_fn: Callable[[], str],
        *,
        graphic_stylesheet_fn: Callable[[], str] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent or dialog)
        self._dialog = dialog
        self._stylesheet_fn = stylesheet_fn
        self._graphic_stylesheet_fn = graphic_stylesheet_fn or _graphic_button_tooltip_stylesheet
        self._label = ensure_tooltip_label(dialog, "_settings_dialog_tooltip_label")
        self._graphic_popup = GraphicTooltipPopup()
        self._source_widget: QWidget | None = None
        self._active = True
        dialog.installEventFilter(self)
        dialog.finished.connect(self._hide_tooltip)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            dialog.destroyed.connect(self._on_dialog_destroyed)

    def _is_descendant(self, widget: QWidget) -> bool:
        host = widget
        while host is not None:
            if host is self._dialog:
                return True
            host = host.parentWidget()
        return False

    def _on_dialog_destroyed(self, *_args) -> None:
        if not self._active:
            return
        self._active = False
        self._hide_tooltip()
        if isValid(self._dialog):
            self._dialog.removeEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def _hide_tooltip(self) -> None:
        if isValid(self._label):
            self._label.hide()
        if isValid(self._graphic_popup):
            self._graphic_popup.hide()
        self._source_widget = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._active or not isValid(self._dialog):
            self._on_dialog_destroyed()
            return False
        if obj is self._dialog and event.type() in (
            QEvent.Type.Hide,
            QEvent.Type.Close,
        ):
            self._hide_tooltip()
            return False
        if not self._dialog.isVisible():
            self._hide_tooltip()
            return False
        if not isinstance(obj, QWidget) or not self._is_descendant(obj):
            return False

        if event.type() == QEvent.Type.ToolTip:
            tip = obj.toolTip()
            if tip:
                if present_graphic_button_tooltip(
                    obj,
                    tip,
                    self._graphic_popup,
                    clamp_widget=self._dialog,
                    stylesheet_fn=self._graphic_stylesheet_fn,
                ):
                    if isValid(self._label):
                        self._label.hide()
                    self._source_widget = obj
                    return True
                self._graphic_popup.hide()
                self._label.setStyleSheet(self._stylesheet_fn())
                self._label.setText(tip)
                self._label.adjustSize()
                position_tooltip_near_cursor(self._label, clamp_widget=self._dialog)
                self._label.show()
                self._label.raise_()
                self._source_widget = obj
            else:
                self._hide_tooltip()
            return True

        if event.type() == QEvent.Type.Leave and obj is self._source_widget:
            self._hide_tooltip()

        return False


def install_settings_dialog_tooltip_filter(
    dialog: QWidget,
    stylesheet_fn: Callable[[], str],
    *,
    graphic_stylesheet_fn: Callable[[], str] | None = None,
) -> SettingsDialogTooltipFilter:
    """Show opaque custom tooltips for all controls inside the settings dialog."""
    filt = SettingsDialogTooltipFilter(
        dialog,
        stylesheet_fn,
        graphic_stylesheet_fn=graphic_stylesheet_fn,
        parent=dialog,
    )
    dialog._settings_dialog_tooltip_filter = filt  # type: ignore[attr-defined]
    return filt
