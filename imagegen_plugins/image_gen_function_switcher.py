#!/usr/bin/env python3
"""Bottom bar for switching between image-generation function dialogs."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QPushButton, QWidget

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)
from thumbnails.thumbnail_constants import CMD_SYMBOL, ENTER_SYMBOL
from imagegen_plugins.image_gen_source_nav import resolve_image_gen_main_window
from theme.theme_base import asset_path

_FUNCTION_SWITCHER_BTN_SIZE = 28

_SWITCHER_ENTRIES = (
    (FUNCTION_CREATE, "fromText.png", "Create an image from text..."),
    (FUNCTION_EDIT, "editAI.png", "Edit an image with AI..."),
    (FUNCTION_EXPAND, "expand_icon.png", "Expand existing image..."),
    (FUNCTION_INFILL_PAINT, "infill.png", "Infill by painting..."),
)

def _thumbnail_default_border_color() -> str:
    from thumbnails.thumbnail_constants import DEFAULT_IMAGE_COLOR_HEX

    color = (DEFAULT_IMAGE_COLOR_HEX or "#606060").strip()
    return color if color else "#606060"


def _highlight_function(function: str) -> str:
    if function in (FUNCTION_INFILL, FUNCTION_INFILL_PAINT):
        return FUNCTION_INFILL_PAINT
    return function


def _should_switch(current_function: str, target_function: str) -> bool:
    return current_function != target_function


def _function_switcher_button_stylesheet(
    icon_name: str,
    *,
    hover_icon_name: str,
    border_width_px: int,
) -> str:
    border_color = _thumbnail_default_border_color()
    icon_url = f"url({asset_path(icon_name)})"
    hover_url = f"url({asset_path(hover_icon_name)})"
    sz = _FUNCTION_SWITCHER_BTN_SIZE
    return f"""
        QPushButton {{
            background-color: transparent;
            border: {border_width_px}px solid {border_color};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:focus {{
            outline: none;
        }}
        QPushButton:hover {{
            image: {hover_url};
        }}
    """


def switch_imagegen_function_dialog(dialog, target_function: str) -> None:
    """Switch generation type inside the unified dialog."""
    current_function = getattr(dialog, "_function", None)
    if not current_function or not _should_switch(current_function, target_function):
        return

    main_window = resolve_image_gen_main_window(dialog)
    if main_window is None:
        main_window = getattr(dialog, "_main_window", None)
    if main_window is None:
        return

    from imagegen_plugins.image_gen_menu import switch_imagegen_function_dialog_in_place

    switch_imagegen_function_dialog_in_place(dialog, target_function, main_window)


def _make_function_switcher_button(
    dialog,
    function: str,
    icon_name: str,
    tooltip: str,
    *,
    highlighted_function: str,
) -> QPushButton:
    hover_name = icon_name.replace(".png", "_hover.png")
    is_active = function == highlighted_function
    border_width = 2 if is_active else 1
    display_icon = hover_name if is_active else icon_name
    btn = QPushButton()
    btn.setObjectName("imageGenFunctionSwitcherButton")
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFlat(True)
    btn.setStyleSheet(
        _function_switcher_button_stylesheet(
            display_icon,
            hover_icon_name=hover_name,
            border_width_px=border_width,
        )
    )
    btn.clicked.connect(
        lambda _checked=False, fn=function: switch_imagegen_function_dialog(
            dialog, fn
        )
    )
    return btn


def add_image_gen_function_switcher_buttons(
    row: QHBoxLayout,
    dialog,
    current_function: str,
) -> None:
    """Append four function-switcher icon buttons at the start of a footer row."""
    highlighted = _highlight_function(current_function)
    for function, icon_name, tooltip in _SWITCHER_ENTRIES:
        row.addWidget(
            _make_function_switcher_button(
                dialog,
                function,
                icon_name,
                tooltip,
                highlighted_function=highlighted,
            )
        )


def refresh_image_gen_function_switcher_highlight(
    footer: QWidget,
    dialog,
    current_function: str,
) -> None:
    """Replace only switcher icon buttons; keep stretch and action buttons."""
    row = footer.layout()
    if row is None:
        return
    for _ in range(len(_SWITCHER_ENTRIES)):
        item = row.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    highlighted = _highlight_function(current_function)
    for idx, (function, icon_name, tooltip) in enumerate(_SWITCHER_ENTRIES):
        row.insertWidget(
            idx,
            _make_function_switcher_button(
                dialog,
                function,
                icon_name,
                tooltip,
                highlighted_function=highlighted,
            ),
        )


def create_image_gen_close_on_generate_checkbox(
    *,
    on_changed: Optional[Callable[[bool], None]] = None,
) -> QCheckBox:
    checkbox = QCheckBox("Close dialog on generate")
    checkbox.setObjectName("imageGenCloseOnGenerateCheckbox")
    checkbox.setToolTip(
        "When checked, close this dialog after a job is submitted successfully. "
        "When unchecked, keep the dialog open and show a brief confirmation."
    )
    if on_changed is not None:
        checkbox.toggled.connect(on_changed)
    return checkbox


def create_image_gen_dialog_footer(
    dialog,
    current_function: str,
    right_widget: QWidget,
    *,
    center_widget: Optional[QWidget] = None,
) -> QWidget:
    """Footer row: function switcher (left) and dialog actions (right)."""
    from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

    footer = QWidget()
    footer.setObjectName("imageGenDialogFooter")
    apply_image_gen_preview_client_background(footer)
    row = QHBoxLayout(footer)
    row.setContentsMargins(0, 15, 0, 15)
    row.setSpacing(8)
    add_image_gen_function_switcher_buttons(row, dialog, current_function)
    row.addStretch(1)
    if center_widget is not None:
        row.addWidget(center_widget)
        row.addStretch(1)
    row.addWidget(right_widget)
    return footer


def create_image_gen_action_buttons(
    *,
    on_generate: Callable[[], None],
    on_close: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
    on_replace: Optional[Callable[[], None]] = None,
) -> QWidget:
    """Cancel (optional) + Close + Replace (optional) + primary action."""
    from imagegen_plugins.imagegen_control_tooltips import (
        apply_image_gen_action_button_tooltips,
    )
    from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

    widget = QWidget()
    widget.setObjectName("imageGenActionButtons")
    apply_image_gen_preview_client_background(widget)
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.setObjectName("imageGenCancelButton")
    cancel_btn.hide()
    close_btn = QPushButton("Close")
    generate_btn = QPushButton(f"Generate {CMD_SYMBOL}{ENTER_SYMBOL}")
    generate_btn.setObjectName("imageGenGenerateButton")
    apply_image_gen_action_button_tooltips(close_btn, generate_btn)
    cancel_btn.setToolTip(
        "Discard changes and close."
    )
    if on_cancel is not None:
        cancel_btn.clicked.connect(on_cancel)
    generate_btn.setDefault(True)
    generate_btn.setAutoDefault(True)
    close_btn.clicked.connect(on_close)
    generate_btn.clicked.connect(on_generate)
    replace_btn = QPushButton("Replace")
    replace_btn.setObjectName("imageGenReplaceButton")
    replace_btn.setToolTip(
        "Update this queued job with the current settings (does not add a new job)."
    )
    replace_btn.hide()
    if on_replace is not None:
        replace_btn.clicked.connect(on_replace)
    row.addWidget(cancel_btn)
    row.addWidget(close_btn)
    row.addWidget(replace_btn)
    row.addWidget(generate_btn)
    widget._imagegen_cancel_btn = cancel_btn  # type: ignore[attr-defined]
    widget._imagegen_close_btn = close_btn  # type: ignore[attr-defined]
    widget._imagegen_replace_btn = replace_btn  # type: ignore[attr-defined]
    widget._imagegen_generate_btn = generate_btn  # type: ignore[attr-defined]
    return widget


def _is_valid_qt_widget(widget) -> bool:
    if widget is None:
        return False
    try:
        from shiboken6 import isValid

        return bool(isValid(widget))
    except ImportError:
        return True


def set_image_gen_cancel_visible(actions: QWidget, visible: bool) -> None:
    cancel_btn = getattr(actions, "_imagegen_cancel_btn", None)
    if cancel_btn is None:
        cancel_btn = actions.findChild(QPushButton, "imageGenCancelButton")
    if _is_valid_qt_widget(cancel_btn):
        cancel_btn.setVisible(visible)


def install_image_gen_escape_handler(
    dialog: QDialog,
    on_escape: Callable[[], None],
) -> None:
    """Route Escape to the shell dismiss handler."""
    prior = dialog.keyPressEvent

    def keyPressEvent(event):
        if (
            event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            on_escape()
            event.accept()
            return
        prior(event)

    dialog.keyPressEvent = keyPressEvent


def install_image_gen_escape_to_close(
    dialog: QDialog,
    on_close: Optional[Callable[[], None]] = None,
) -> None:
    """Dismiss persistent panels on Escape (no QDialogButtonBox Cancel)."""
    if on_close is None:
        on_close = dialog.reject
    install_image_gen_escape_handler(dialog, on_close)


def _switcher_functions() -> tuple[str, ...]:
    return tuple(fn for fn, _, _ in _SWITCHER_ENTRIES)


def _neighbor_switcher_function(current_function: str, delta: int) -> str:
    order = _switcher_functions()
    current = _highlight_function(current_function)
    try:
        idx = order.index(current)
    except ValueError:
        return order[0]
    return order[(idx + delta) % len(order)]


class _FunctionFooterKeyFilter(QObject):
    """Cmd+Left/Right — prev/next footer function; Cmd+Return — Generate; Cmd+W — Close."""

    def __init__(self, dialog: QDialog, parent: QObject | None = None) -> None:
        super().__init__(parent or dialog)
        self._dialog = dialog

    def _click_close_button(self) -> bool:
        actions = self._dialog.findChild(QWidget, "imageGenActionButtons")
        close_btn = getattr(actions, "_imagegen_close_btn", None) if actions else None
        if not _is_valid_qt_widget(close_btn) or not close_btn.isVisible():
            return False
        close_btn.click()
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        mods = event.modifiers()
        if (
            key == Qt.Key.Key_W
            and mods == Qt.KeyboardModifier.ControlModifier
        ):
            return self._click_close_button()
        if not (mods & Qt.KeyboardModifier.ControlModifier):
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            current = getattr(self._dialog, "_function", None)
            if not current:
                return False
            delta = -1 if key == Qt.Key.Key_Left else 1
            switch_imagegen_function_dialog(
                self._dialog, _neighbor_switcher_function(current, delta)
            )
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            generate_btn = self._dialog.findChild(
                QPushButton, "imageGenGenerateButton"
            )
            if generate_btn is not None and generate_btn.isEnabled():
                generate_btn.click()
                return True
        return False


def _attach_footer_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_image_gen_footer_key_filter", None)
    if filt is None:
        return
    tracked: set[int] = (
        getattr(host, "_image_gen_footer_key_filter_widgets", None) or set()
    )
    for widget in (host, *host.findChildren(QWidget)):
        wid = id(widget)
        if wid in tracked:
            continue
        widget.installEventFilter(filt)
        tracked.add(wid)
    setattr(host, "_image_gen_footer_key_filter_widgets", tracked)


def install_image_gen_footer_keyboard_shortcuts(dialog: QDialog) -> None:
    """Cmd+Left/Right — cycle footer function icons; Cmd+Return — Generate; Cmd+W — Close."""
    filt = getattr(dialog, "_image_gen_footer_key_filter", None)
    if filt is None:
        filt = _FunctionFooterKeyFilter(dialog, parent=dialog)
        setattr(dialog, "_image_gen_footer_key_filter", filt)
    _attach_footer_key_filter(dialog)


def refresh_image_gen_footer_keyboard_shortcuts(host: QWidget) -> None:
    """Attach footer key filter to widgets added after install."""
    _attach_footer_key_filter(host)
