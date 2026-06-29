#!/usr/bin/env python3
"""Toggleable LM Studio instructions pane (shared by EXIF and image-gen dialogs)."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from theme.theme_base import asset_path
from theme.theme_service import apply_view_chrome_splitter_theme, get_active_theme
from thumbnails.thumbnail_constants import (
    BUTTON_BG_DEFAULT_HEX,
    BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BORDER_HOVER_HEX,
    BUTTON_TEXT_HOVER_HEX,
    TEXT_DISABLED_HEX,
)
from whisper_voice_input import maybe_wrap_plain_text_edit_with_voice_mic

LMSTUDIO_INSTRUCTIONS_LINE_COUNT = 5


def lmstudio_instructions_button_stylesheet(
    *,
    selector: str = "QPushButton#instructions_btn",
) -> str:
    """Match Edit EXIF User Comment dialog #instructions_btn chrome."""
    return f"""
        {selector} {{
            background-color: {BUTTON_BG_DEFAULT_HEX};
            color: {TEXT_DISABLED_HEX};
            border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
            border-radius: 6px;
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
            padding: 2px;
            font-size: 16px;
        }}
        {selector}:hover {{
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
    """


def apply_lmstudio_instructions_button_style(
    button: QPushButton, *, active: bool = False
) -> None:
    button.setObjectName("instructions_btn")
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(24, 24)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    th = get_active_theme()
    if active:
        button.setStyleSheet(
            lmstudio_instructions_button_stylesheet()
            + f"""
        QPushButton#instructions_btn {{
            background-color: {th.tab_button_hover_bg_hex};
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
        """
        )
    else:
        button.setStyleSheet(lmstudio_instructions_button_stylesheet())


def create_lmstudio_instructions_icon() -> QIcon:
    """Theme-aware AI icon for the instructions toggle button."""
    th = get_active_theme()
    name = (
        "ai_icon_info_light.png"
        if getattr(th, "theme_id", "dark") == "light"
        else "ai_icon_info_dark.png"
    )
    return QIcon(asset_path(name))


class _InstructionsButtonHoverFilter(QObject):
    def __init__(self, button: QPushButton, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._button = button
        self._icon_normal = create_lmstudio_instructions_icon()
        self._icon_hover = create_lmstudio_instructions_icon()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._button:
            if event.type() == QEvent.Type.Enter:
                self._button.setIcon(self._icon_hover)
            elif event.type() == QEvent.Type.Leave:
                self._button.setIcon(self._icon_normal)
        return super().eventFilter(obj, event)


class LmStudioInstructionsPane:
    """Toggle button + hideable instructions editor with optional splitter wrap."""

    def __init__(
        self,
        parent: QWidget,
        *,
        label_text: str = "System Prompt",
        placeholder: str = "Provide system instructions for the AI…",
        toggle_tooltip: str = "Show/hide system prompt for Prompt AI",
        line_count: int = LMSTUDIO_INSTRUCTIONS_LINE_COUNT,
        image_gen_styled: bool = False,
        on_visibility_changed: Optional[Callable[[], None]] = None,
        on_text_changed: Optional[Callable[[], None]] = None,
    ):
        self._parent = parent
        self._on_visibility_changed = on_visibility_changed
        self._on_text_changed = on_text_changed
        self._visible = False
        self._toggle_btn: Optional[QPushButton] = None
        self._hover_filter: Optional[_InstructionsButtonHoverFilter] = None
        self._splitter: Optional[QSplitter] = None
        self._label_text = label_text
        self._placeholder = placeholder
        self._line_count = max(1, int(line_count))
        self._toggle_tooltip = toggle_tooltip
        self._image_gen_styled = bool(image_gen_styled)
        self._instructions_edit: Optional[QPlainTextEdit] = None
        self._widget: Optional[QWidget] = None
        self._toolbar_host: Optional[QWidget] = None
        self._build_instructions_widget()

    def _widget_is_alive(self) -> bool:
        from shiboken6 import isValid

        if self._widget is None:
            return False
        try:
            return isValid(self._widget)
        except Exception:
            return False

    def _build_instructions_widget(self) -> None:
        saved_text = ""
        if self._instructions_edit is not None:
            try:
                from shiboken6 import isValid

                if isValid(self._instructions_edit):
                    saved_text = self._instructions_edit.toPlainText()
            except Exception:
                pass

        if self._image_gen_styled:
            from imagegen_plugins.image_gen_form_layout import (
                IMAGE_GEN_FIELD_BORDER_PAD,
                IMAGE_GEN_FIELD_LABEL_SPACING,
                create_image_gen_prompt_edit,
                make_image_gen_field_label,
                wrap_image_gen_bordered_field,
                wrap_image_gen_field_control_indent,
            )

            group_parent = QWidget(self._parent)
            col = QVBoxLayout(group_parent)
            col.setContentsMargins(1, 0, IMAGE_GEN_FIELD_BORDER_PAD, 0)
            col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
            col.addWidget(make_image_gen_field_label(self._label_text, group_parent), 0)
            edit = create_image_gen_prompt_edit(
                min_lines=self._line_count,
                max_lines=self._line_count,
            )
            edit.setPlaceholderText(self._placeholder)
            if saved_text:
                edit.setPlainText(saved_text)
            if self._on_text_changed is not None:
                edit.textChanged.connect(self._on_text_changed)
            display_control = maybe_wrap_plain_text_edit_with_voice_mic(edit)
            prompt_stack = QWidget(group_parent)
            prompt_stack.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            prompt_stack_layout = QVBoxLayout(prompt_stack)
            prompt_stack_layout.setContentsMargins(0, 0, 0, IMAGE_GEN_FIELD_BORDER_PAD)
            prompt_stack_layout.setSpacing(0)
            prompt_stack_layout.addWidget(
                wrap_image_gen_bordered_field(display_control, bottom_pad=0),
                0,
            )
            self._toolbar_host = QWidget(prompt_stack)
            self._toolbar_host.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            toolbar_col = QVBoxLayout(self._toolbar_host)
            toolbar_col.setContentsMargins(0, 0, 0, 0)
            toolbar_col.setSpacing(0)
            prompt_stack_layout.addWidget(self._toolbar_host, 0)
            col.addWidget(
                wrap_image_gen_field_control_indent(prompt_stack, group_parent),
                0,
            )
            widget = group_parent
            self._instructions_edit = edit
        else:
            label = QLabel(self._label_text)
            from imagegen_plugins.image_gen_form_layout import create_image_gen_prompt_edit

            instructions_container = QVBoxLayout()
            instructions_container.setSpacing(4)
            instructions_container.setContentsMargins(0, 0, 0, 0)
            edit = create_image_gen_prompt_edit(
                min_lines=self._line_count,
                max_lines=self._line_count,
            )
            edit.setPlaceholderText(self._placeholder)
            if saved_text:
                edit.setPlainText(saved_text)
            if self._on_text_changed is not None:
                edit.textChanged.connect(self._on_text_changed)
            instructions_container.addWidget(label)
            instructions_container.addWidget(
                maybe_wrap_plain_text_edit_with_voice_mic(edit), 0
            )
            widget = QWidget(self._parent)
            widget.setLayout(instructions_container)
            self._instructions_edit = edit
        widget.setVisible(self._visible)
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        if self._toolbar_host is not None:
            self._toolbar_host.setVisible(self._visible)
        self._widget = widget
        self.sync_toggle_highlight()

    def toolbar_host(self) -> Optional[QWidget]:
        self._ensure_widget()
        return self._toolbar_host

    def set_toolbar_widget(self, toolbar: QWidget) -> None:
        host = self.toolbar_host()
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
                child.deleteLater()
        layout.addWidget(toolbar, 0)

    def sync_toggle_highlight(self) -> None:
        if self._toggle_btn is None:
            return
        apply_lmstudio_instructions_button_style(
            self._toggle_btn, active=self._visible
        )

    def _ensure_widget(self) -> QWidget:
        if not self._widget_is_alive():
            self._build_instructions_widget()
        assert self._widget is not None
        return self._widget

    def instructions_edit(self) -> QPlainTextEdit:
        self._ensure_widget()
        assert self._instructions_edit is not None
        return self._instructions_edit

    def widget(self) -> QWidget:
        return self._ensure_widget()

    def is_visible(self) -> bool:
        return self._visible

    def set_visible(self, visible: bool) -> None:
        was_visible = self._visible
        self._visible = bool(visible)
        widget = self._ensure_widget()
        widget.setVisible(self._visible)
        if self._toolbar_host is not None:
            self._toolbar_host.setVisible(self._visible)
        if self._splitter is not None:
            total = max(sum(self._splitter.sizes()), 1)
            if self._visible:
                top = max(self._splitter.sizes()[0], 80) if was_visible else 100
                self._splitter.setSizes([top, max(total - top, 120)])
            else:
                self._splitter.setSizes([0, total])
        if self._on_visibility_changed is not None:
            self._on_visibility_changed()
        self.sync_toggle_highlight()

    def effective_override_text(self) -> Optional[str]:
        if not self._visible:
            return None
        if not self._widget_is_alive() or self._instructions_edit is None:
            return None
        text = self._instructions_edit.toPlainText().strip()
        return text or None

    def plain_text(self) -> str:
        if not self._widget_is_alive() or self._instructions_edit is None:
            return ""
        return self._instructions_edit.toPlainText()

    def set_plain_text(self, text: str) -> None:
        self._ensure_widget()
        assert self._instructions_edit is not None
        self._instructions_edit.setPlainText(text)

    def splitter(self) -> Optional[QSplitter]:
        return self._splitter

    def set_splitter_sizes(self, sizes: list[int]) -> None:
        if self._splitter is None:
            return
        if (
            isinstance(sizes, list)
            and len(sizes) == 2
            and sum(sizes) > 0
        ):
            self._splitter.setSizes(sizes)

    def splitter_sizes(self) -> list[int]:
        if self._splitter is None:
            return []
        return self._splitter.sizes()

    def toggle_button(self, *, recreate: bool = False) -> QPushButton:
        if self._toggle_btn is not None and not recreate:
            return self._toggle_btn
        if self._toggle_btn is not None:
            self._toggle_btn.deleteLater()
        btn = QPushButton(self._parent)
        apply_lmstudio_instructions_button_style(btn)
        icon = create_lmstudio_instructions_icon()
        btn.setIcon(icon)
        btn.setToolTip(self._toggle_tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_toggle)
        self._hover_filter = _InstructionsButtonHoverFilter(btn, btn)
        btn.installEventFilter(self._hover_filter)
        self._toggle_btn = btn
        return btn

    def _on_toggle(self) -> None:
        self.set_visible(not self._visible)

    def wrap_above_in_splitter(self, main_widget: QWidget) -> QSplitter:
        self._splitter = None
        splitter = QSplitter(Qt.Orientation.Vertical, self._parent)
        splitter.setChildrenCollapsible(False)
        apply_view_chrome_splitter_theme(splitter)
        splitter.addWidget(self._ensure_widget())
        splitter.addWidget(main_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([100, 200])
        self._splitter = splitter
        return splitter
