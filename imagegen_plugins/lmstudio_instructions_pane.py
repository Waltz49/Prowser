#!/usr/bin/env python3
"""Toggleable LM Studio instructions pane (shared by EXIF and image-gen dialogs)."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from theme.ai_info_icon import AI_INFO_ICON_DISPLAY_PX, create_ai_info_icons
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
    button: QPushButton,
    *,
    active: bool = False,
    image_gen_styled: bool = False,
) -> None:
    button.setObjectName("instructions_btn")
    button.setIconSize(QSize(AI_INFO_ICON_DISPLAY_PX, AI_INFO_ICON_DISPLAY_PX))
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    th = get_active_theme()
    if image_gen_styled:
        from imagegen_plugins.image_gen_form_layout import (
            IMAGE_GEN_FIELD_RESET_BTN_SIZE,
            image_gen_prompt_copy_btn_stylesheet,
        )

        selector = "QPushButton#instructions_btn"
        base = image_gen_prompt_copy_btn_stylesheet(selector=selector)
        button.setFixedSize(
            IMAGE_GEN_FIELD_RESET_BTN_SIZE, IMAGE_GEN_FIELD_RESET_BTN_SIZE
        )
        if active:
            button.setStyleSheet(
                base
                + f"""
        {selector} {{
            background-color: {th.tab_button_hover_bg_hex};
            border: 1px solid {th.tab_button_hover_bg_hex};
        }}
        """
            )
        else:
            button.setStyleSheet(base)
        return

    button.setFixedSize(24, 24)
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
    return create_ai_info_icons()[0]


class _InstructionsButtonHoverFilter(QObject):
    def __init__(
        self,
        button: QPushButton,
        normal_icon: QIcon,
        highlight_icon: QIcon,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._button = button
        self._icon_normal = normal_icon
        self._icon_highlight = highlight_icon
        self._active = False
        self._hovered = False
        self._sync_icon()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._sync_icon()

    def _sync_icon(self) -> None:
        icon = (
            self._icon_highlight
            if self._active or self._hovered
            else self._icon_normal
        )
        self._button.setIcon(icon)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._button:
            if event.type() == QEvent.Type.Enter:
                self._hovered = True
                self._sync_icon()
            elif event.type() == QEvent.Type.Leave:
                self._hovered = False
                self._sync_icon()
        return False


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
        self._editor_block: Optional[QWidget] = None
        self._action_col: Optional[QWidget] = None
        self._action_layout: Optional[QVBoxLayout] = None
        self._copy_btn: Optional[QPushButton] = None
        self._mic_btn: Optional[QPushButton] = None
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
                build_image_gen_prompt_field_action_column,
                create_image_gen_prompt_edit,
                make_image_gen_prompt_label_row,
                wrap_image_gen_bordered_field,
                wrap_image_gen_field_control_indent,
            )

            group_parent = QWidget(self._parent)
            col = QVBoxLayout(group_parent)
            col.setContentsMargins(1, 0, IMAGE_GEN_FIELD_BORDER_PAD, 0)
            col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
            edit = create_image_gen_prompt_edit(
                min_lines=self._line_count,
                max_lines=self._line_count,
            )
            edit.setPlaceholderText(self._placeholder)
            if saved_text:
                edit.setPlainText(saved_text)
            if self._on_text_changed is not None:
                edit.textChanged.connect(self._on_text_changed)
            col.addWidget(
                make_image_gen_prompt_label_row(
                    self._label_text,
                    edit,
                    group_parent,
                    label_row_object_name="imageGenSystemPromptLabelRow",
                    clear_object_name="imageGenSystemPromptClearBtn",
                ),
                0,
            )
            self._editor_block = QWidget(group_parent)
            editor_block_layout = QVBoxLayout(self._editor_block)
            editor_block_layout.setContentsMargins(0, 0, 0, 0)
            editor_block_layout.setSpacing(0)
            editor_block_layout.addWidget(
                wrap_image_gen_bordered_field(edit, bottom_pad=0),
                0,
            )
            self._toolbar_host = QWidget(self._editor_block)
            self._toolbar_host.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            toolbar_col = QVBoxLayout(self._toolbar_host)
            toolbar_col.setContentsMargins(0, 0, 0, 0)
            toolbar_col.setSpacing(0)
            editor_block_layout.addWidget(self._toolbar_host, 0)

            field_row = QWidget(group_parent)
            field_row_layout = QHBoxLayout(field_row)
            field_row_layout.setContentsMargins(0, 0, 0, IMAGE_GEN_FIELD_BORDER_PAD)
            field_row_layout.setSpacing(4)
            field_row_layout.addWidget(self._editor_block, 1)
            (
                self._action_col,
                self._action_layout,
                self._copy_btn,
                self._mic_btn,
            ) = build_image_gen_prompt_field_action_column(
                edit,
                field_row,
                copy_object_name="imageGenSystemPromptCopyBtn",
                mic_object_name="imageGenSystemPromptVoiceMicBtn",
                action_column_object_name="imageGenSystemPromptActionCol",
            )
            field_row_layout.addWidget(
                self._action_col,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )
            field_row.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            col.addWidget(
                wrap_image_gen_field_control_indent(field_row, group_parent),
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
        if self._image_gen_styled:
            widget.setVisible(True)
            self._apply_content_visibility()
        else:
            widget.setVisible(self._visible)
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
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

    def _apply_content_visibility(self) -> None:
        vis = self._visible
        if self._widget is not None:
            self._widget.setVisible(vis)
        if not vis:
            return
        if self._editor_block is not None:
            self._editor_block.setVisible(True)
        if self._toolbar_host is not None and self._toolbar_host.parent() is self._editor_block:
            self._toolbar_host.setVisible(True)
        if self._copy_btn is not None:
            self._copy_btn.setVisible(True)
        if self._mic_btn is not None:
            self._mic_btn.setVisible(True)

    def _sync_toggle_location(self) -> None:
        if not self._image_gen_styled or self._toggle_btn is None:
            return
        from imagegen_plugins.flux_prompt_system_mount import (
            sync_flux_prompt_system_toggle_location,
        )

        sync_flux_prompt_system_toggle_location(self._parent)

    def sync_toggle_highlight(self) -> None:
        if self._toggle_btn is None:
            return
        apply_lmstudio_instructions_button_style(
            self._toggle_btn,
            active=self._visible,
            image_gen_styled=self._image_gen_styled,
        )
        if self._hover_filter is not None:
            self._hover_filter.set_active(self._visible)

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
        self._ensure_widget()
        if self._image_gen_styled:
            self._apply_content_visibility()
        elif self._widget is not None:
            self._widget.setVisible(self._visible)
        if self._splitter is not None:
            total = max(sum(self._splitter.sizes()), 1)
            if self._visible:
                top = max(self._splitter.sizes()[0], 80) if was_visible else 100
                self._splitter.setSizes([top, max(total - top, 120)])
            else:
                self._splitter.setSizes([0, total])
        if self._on_visibility_changed is not None:
            self._on_visibility_changed()
        self._sync_toggle_location()
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
        btn = QPushButton(self._action_col or self._parent)
        normal_icon, highlight_icon = create_ai_info_icons()
        apply_lmstudio_instructions_button_style(
            btn, image_gen_styled=self._image_gen_styled
        )
        btn.setIcon(normal_icon)
        btn.setToolTip(self._toggle_tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_toggle)
        self._hover_filter = _InstructionsButtonHoverFilter(
            btn, normal_icon, highlight_icon, btn
        )
        btn.installEventFilter(self._hover_filter)
        self._toggle_btn = btn
        self.sync_toggle_highlight()
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
