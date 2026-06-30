#!/usr/bin/env python3
"""
Dialog for editing EXIF UserComment on a single image file.
"""

import os
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QMessageBox, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QTextCursor
from thumbnails.thumbnail_constants import (
    DIALOG_BACKGROUND_HEX,
    DIALOG_TEXT_COLOR_HEX,
    DEFAULT_BORDER_COLOR,
    MULTISELECT_BORDER_COLOR_HEX,
    BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
    BUTTON_BG_PRESSED_HEX, BUTTON_FOCUS_TEXT_HEX, CURRENT_IMAGE_BORDER_COLOR_HEX,
    ACCENT_COLOR_HEX, TEXT_DISABLED_HEX, WIDGET_BG_DISABLED_HEX, VALIDATION_SUCCESS_COLOR_HEX,
)
from config import get_config
from exif.exif_utils import truncate_usercomment_before_prompt
from theme.theme_service import get_active_theme
from utils import create_gear_icon, get_main_window


def _lmstudio_ui_enabled() -> bool:
    try:
        from bundle_capabilities import lmstudio_ui_enabled

        return lmstudio_ui_enabled()
    except ImportError:
        return True


def _voice_input_ui_enabled() -> bool:
    try:
        from bundle_capabilities import voice_input_ui_enabled

        return voice_input_ui_enabled()
    except ImportError:
        return True


def _imagegen_ui_enabled() -> bool:
    try:
        from bundle_capabilities import imagegen_ui_enabled

        return imagegen_ui_enabled()
    except ImportError:
        return True


def _audio_output_ui_enabled() -> bool:
    try:
        from bundle_capabilities import audio_output_ui_enabled

        return audio_output_ui_enabled()
    except ImportError:
        return True


def _is_lmstudio_services_available() -> bool:
    if not _lmstudio_ui_enabled():
        return False
    try:
        from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available

        return is_lmstudio_services_available()
    except ImportError:
        return False


def _imagegen_create_from_text_available() -> bool:
    if not _imagegen_ui_enabled():
        return False
    try:
        from imagegen_plugins.image_gen_menu import imagegen_create_from_text_available

        return imagegen_create_from_text_available()
    except ImportError:
        return False


def _initial_prompt_from_usercomment(text: str):
    if not _imagegen_ui_enabled():
        return text.strip()
    try:
        from imagegen_plugins.image_gen_menu import initial_prompt_from_usercomment

        return initial_prompt_from_usercomment(text)
    except ImportError:
        return text.strip()


def _open_imagegen_create_from_text_dialog(main_window, *, user_comment: str) -> None:
    if not _imagegen_ui_enabled():
        return
    try:
        from imagegen_plugins.image_gen_menu import open_imagegen_create_from_text_dialog

        open_imagegen_create_from_text_dialog(main_window, user_comment=user_comment)
    except ImportError:
        return


def _maybe_wrap_plain_text_edit_with_voice_mic(edit):
    if not _voice_input_ui_enabled():
        return edit
    try:
        from whisper_voice_input import maybe_wrap_plain_text_edit_with_voice_mic

        return maybe_wrap_plain_text_edit_with_voice_mic(edit)
    except ImportError:
        return edit


def _stop_whisper_dictation() -> None:
    if not _voice_input_ui_enabled():
        return
    try:
        from whisper_voice_input import stop_whisper_dictation

        stop_whisper_dictation()
    except ImportError:
        pass


def _speak_or_stop(text: str) -> bool:
    if not _audio_output_ui_enabled():
        return False
    from speech_utils import speak_or_stop

    return speak_or_stop(text)


def _qtcolor_to_hex(color):
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def _create_copy_icon(color: str = ACCENT_COLOR_HEX) -> QIcon:
    """Create a copy icon: two small squares offset diagonally (standard copy graphic)."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Back square (top-left)
    painter.drawRect(2, 2, 8, 8)
    # Front square (offset down-right)
    painter.drawRect(6, 6, 8, 8)
    painter.end()
    return QIcon(pixmap)


def _create_check_icon(color: str = VALIDATION_SUCCESS_COLOR_HEX) -> QIcon:
    """Create a checkmark icon for copy confirmation feedback."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 2.0))
    painter.drawLine(3, 9, 7, 14)
    painter.drawLine(7, 14, 15, 4)
    painter.end()
    return QIcon(pixmap)


def _overlay_chip_stylesheet() -> str:
    """Green chip styling matching File Information copy-feedback overlays."""
    th = get_active_theme()
    success_hex = th.validation_success_color_hex
    chip_bg = th.information_action_chip_bg_hex
    return f"""
        QPushButton {{
            background-color: {chip_bg};
            color: {success_hex};
            border: 1px solid {success_hex};
            border-radius: 4px;
            padding: 4px 10px;
            font-size: 11pt;
            min-width: 0;
        }}
        QPushButton:hover:enabled {{
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
        QPushButton:disabled {{
            color: {TEXT_DISABLED_HEX};
            border: 1px solid {TEXT_DISABLED_HEX};
        }}
    """


class EditExifUserCommentDialog(QDialog):
    """Dialog for viewing and editing the EXIF UserComment of a single image."""

    def __init__(self, file_path: str, original_text: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.original_text = original_text
        self._caption_connected = False
        self._caption_cancelled_on_close = False
        self._text_before_ai = original_text
        self._ai_caption_error_dialog_open = False
        self._base_filename = os.path.basename(file_path)
        self._dot_phase = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._on_dot_tick)
        self._text_edit_container = None
        self.generate_btn = None
        self.ai_btn = None

        bg_color = _qtcolor_to_hex(QColor(DIALOG_BACKGROUND_HEX))
        text_color = DIALOG_TEXT_COLOR_HEX
        border_color = _qtcolor_to_hex(DEFAULT_BORDER_COLOR)

        self.setWindowTitle("Edit EXIF User Comment")
        self.setMinimumWidth(480)
        self.setMinimumHeight(320)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
            }}
            QLabel {{
                color: {text_color};
                font-size: 13px;
            }}
            QPlainTextEdit {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
                selection-background-color: {ACCENT_COLOR_HEX};
            }}
            QPushButton {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {BUTTON_TEXT_DEFAULT_HEX};
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                border-radius: 5px;
                padding: 6px 18px;
                min-width: 80px;
                font-size: 13px;
                font-family: 'Arial Narrow', Arial;
                letter-spacing: 0.5px;
            }}
            QPushButton:focus {{
                background-color: {bg_color};
                color: {BUTTON_FOCUS_TEXT_HEX};
                border: 1px solid {CURRENT_IMAGE_BORDER_COLOR_HEX};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {BUTTON_BG_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton:pressed {{
                background-color: {BUTTON_BG_PRESSED_HEX};
                color: {BUTTON_FOCUS_TEXT_HEX};
            }}
            QPushButton#ear_btn {{
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
            QPushButton#ear_btn:hover {{
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton#copy_btn {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {TEXT_DISABLED_HEX};
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                border-radius: 6px;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
                padding: 2px;
            }}
            QPushButton#copy_btn:hover {{
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton#copy_btn:pressed {{
                background-color: {BUTTON_BG_PRESSED_HEX};
                border: 1px solid {VALIDATION_SUCCESS_COLOR_HEX};
            }}
            QPushButton#settings_btn {{
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
            QPushButton#settings_btn:hover {{
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton#instructions_btn {{
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
            QPushButton#instructions_btn:hover {{
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton#voice_mic_btn {{
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                min-width: 0px;
                max-width: 24px;
                min-height: 0px;
                max-height: 24px;
            }}
            QSplitter::handle {{
                background-color: #000000;
                border: none;
            }}
            QSplitter::handle:vertical {{
                height: 6px;
            }}
            QSplitter::handle:vertical:hover,
            QSplitter::handle:vertical:pressed {{
                background-color: #808080;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(20, 18, 20, 18)

        # Header: thumbnail on left, filename on right
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        from utils import create_dialog_thumbnail_label
        self.thumb_label = create_dialog_thumbnail_label(file_path, 128)
        self.thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb_label.setToolTip("Click to open in browse mode")
        self.thumb_label.mousePressEvent = self._make_thumb_click_handler()
        self.thumb_label.installEventFilter(self)
        header_row.addWidget(self.thumb_label)

        self.filename_label = QLabel(f"<b>{self._base_filename}</b>")
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("font-size: 16px;")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        header_row.addWidget(self.filename_label, 1)

        # Ear, copy, and settings buttons (upper right) - stacked vertically
        btn_stack = QVBoxLayout()
        btn_stack.setSpacing(0)
        btn_stack.setContentsMargins(0, 0, 0, 0)
        self.ear_btn = QPushButton("꡴")  # ear emoji
        self.ear_btn.setObjectName("ear_btn")
        self.ear_btn.setToolTip("Read text aloud (click again to stop)")
        self.ear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ear_btn.clicked.connect(self._on_read_aloud)
        if not _audio_output_ui_enabled():
            self.ear_btn.hide()
        btn_stack.addWidget(self.ear_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.copy_btn = QPushButton()
        self.copy_btn.setObjectName("copy_btn")
        self._copy_icon_normal = _create_copy_icon(TEXT_DISABLED_HEX)
        self._copy_icon_hover = _create_copy_icon(BUTTON_TEXT_HOVER_HEX)
        self.copy_btn.setIcon(self._copy_icon_normal)
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setToolTip("Copy user comment to clipboard (UTF-8).\nOption+click to copy raw text.")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy_to_clipboard)
        self.copy_btn.installEventFilter(self)
        btn_stack.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settings_btn")
        self._settings_icon_normal = create_gear_icon(TEXT_DISABLED_HEX)
        self._settings_icon_hover = create_gear_icon(BUTTON_TEXT_HOVER_HEX)
        self.settings_btn.setIcon(self._settings_icon_normal)
        self.settings_btn.setIconSize(QSize(16, 16))
        self.settings_btn.setToolTip("Open Captioning settings")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self._on_open_captioning_settings)
        self.settings_btn.installEventFilter(self)
        if not _lmstudio_ui_enabled():
            self.settings_btn.hide()
        btn_stack.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        self._instructions_pane = None
        if _is_lmstudio_services_available():
            from imagegen_plugins.lmstudio_instructions_pane import LmStudioInstructionsPane

            self._instructions_pane = LmStudioInstructionsPane(
                self,
                toggle_tooltip=(
                    "Show/hide Instructions field (override AI user prompt)"
                ),
            )
            self.instructions_btn = self._instructions_pane.toggle_button()
            btn_stack.addWidget(self.instructions_btn, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.instructions_btn = None
        header_row.addLayout(btn_stack, 0)

        main_layout.addLayout(header_row)

        # Instructions + user comment (resizable when LMS available)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(original_text)
        self.text_edit.setPlaceholderText("Enter user comment…")
        self.text_edit.setMinimumHeight(80)
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_edit.textChanged.connect(self._sync_generate_btn_enabled)
        self._text_edit_display = _maybe_wrap_plain_text_edit_with_voice_mic(self.text_edit)
        text_edit_widget = self._wrap_text_edit_with_overlays()

        if _is_lmstudio_services_available() and self._instructions_pane is not None:
            self._instructions_widget = self._instructions_pane.widget()
            self.instructions_edit = self._instructions_pane.instructions_edit()

            self._text_splitter = self._instructions_pane.wrap_above_in_splitter(
                text_edit_widget
            )
            main_layout.addWidget(self._text_splitter, 1)
        else:
            self._instructions_widget = None
            self.instructions_edit = None
            self._text_splitter = None
            main_layout.addWidget(text_edit_widget, 1)

        # Buttons row: Reset on left, Cancel + Save on right
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip(
            "Reset text to original value\n"
            "(stops AI captioning if in progress)"
        )
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)

        main_layout.addLayout(btn_row)

        # Config for geometry persistence (use parent's config when available for profile consistency)
        self._config = parent.config if (parent and hasattr(parent, 'config')) else get_config()

        # Save geometry when dialog finishes (closeEvent is NOT called for accept/reject)
        self.finished.connect(self._save_geometry)

        self.text_edit.setFocus()

    def _wrap_text_edit_with_overlays(self) -> QWidget:
        """Wrap the comment editor so action chips can overlay the lower-right corner."""
        has_generate = _imagegen_create_from_text_available()
        has_recaption = _is_lmstudio_services_available()
        if not has_generate and not has_recaption:
            return self._text_edit_display

        self._text_edit_container = QWidget()
        container_layout = QVBoxLayout(self._text_edit_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self._text_edit_display)

        if has_generate:
            self.generate_btn = QPushButton("Create", self._text_edit_container)
            self.generate_btn.setToolTip(
                "Open Create an image from text with this caption as the prompt"
            )
            self.generate_btn.clicked.connect(self._on_generate_image_from_caption)
            self.generate_btn.setEnabled(False)
            self.generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.generate_btn.setStyleSheet(_overlay_chip_stylesheet())

        if has_recaption:
            self.ai_btn = QPushButton("Recaption", self._text_edit_container)
            self.ai_btn.setToolTip(
                "Generate an AI caption using LMStudio\n"
                "(requires a vision model loaded in LMStudio)"
            )
            self.ai_btn.clicked.connect(self._on_ai_caption)
            self.ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.ai_btn.setStyleSheet(_overlay_chip_stylesheet())

        self._text_edit_container.installEventFilter(self)
        self._position_text_edit_overlays()
        return self._text_edit_container

    def _position_text_edit_overlays(self) -> None:
        if self._text_edit_container is None:
            return
        container = self._text_edit_container
        right = container.width() - 2
        bottom = container.height() - 2
        gap = 4

        if self.generate_btn is not None:
            btn = self.generate_btn
            btn.adjustSize()
            btn.move(right - btn.width(), bottom - btn.height())
            btn.raise_()
            right = btn.x() - gap

        if self.ai_btn is not None:
            btn = self.ai_btn
            btn.adjustSize()
            btn.move(right - btn.width(), bottom - btn.height())
            btn.raise_()

    def eventFilter(self, obj, event):
        """Swap icon buttons to hover/normal icons on enter/leave; thumbnail border on hover."""
        if (
            self._text_edit_container is not None
            and obj is self._text_edit_container
            and event.type() == QEvent.Type.Resize
        ):
            self._position_text_edit_overlays()
        if event.type() == QEvent.Type.Enter:
            if obj is self.thumb_label:
                self.thumb_label.setStyleSheet(
                    f"border: 1px solid {BUTTON_BORDER_HOVER_HEX}; border-radius: 5px;"
                )
            elif obj is self.copy_btn:
                self.copy_btn.setIcon(self._copy_icon_hover)
            elif obj is self.settings_btn:
                self.settings_btn.setIcon(self._settings_icon_hover)
        elif event.type() == QEvent.Type.Leave:
            if obj is self.thumb_label:
                self.thumb_label.setStyleSheet(
                    f"border: 1px solid {MULTISELECT_BORDER_COLOR_HEX}; border-radius: 5px;"
                )
            elif obj is self.copy_btn:
                self.copy_btn.setIcon(self._copy_icon_normal)
            elif obj is self.settings_btn:
                self.settings_btn.setIcon(self._settings_icon_normal)
        return super().eventFilter(obj, event)

    def _save_geometry(self):
        """Persist dialog geometry and Instructions field for future sessions."""
        try:
            self._config.update_setting('edit_exif_usercomment_dialog_geometry', self.saveGeometry().data().hex())
        except Exception:
            pass
        if self._text_splitter is not None:
            try:
                self._config.update_setting(
                    'edit_exif_usercomment_splitter_sizes',
                    self._text_splitter.sizes(),
                )
            except Exception:
                pass
        if self.instructions_edit is not None and self._instructions_pane is not None:
            try:
                self._config.update_setting(
                    'edit_exif_usercomment_instructions',
                    self._instructions_pane.plain_text(),
                )
                self._config.update_setting(
                    'edit_exif_usercomment_instructions_visible',
                    self._instructions_pane.is_visible(),
                )
            except Exception:
                pass

    def showEvent(self, event):
        """Restore saved geometry and Instructions field when dialog is about to be shown."""
        try:
            settings = self._config.load_settings()
            geom_hex = settings.get('edit_exif_usercomment_dialog_geometry')
            if geom_hex:
                self.restoreGeometry(QByteArray(bytes.fromhex(geom_hex)))
            if self._instructions_pane is not None:
                self._instructions_pane.set_plain_text(
                    settings.get('edit_exif_usercomment_instructions', '')
                )
                self._instructions_pane.set_visible(
                    settings.get('edit_exif_usercomment_instructions_visible', False)
                )
                self.instructions_edit = self._instructions_pane.instructions_edit()
            if self._text_splitter is not None:
                saved_sizes = settings.get('edit_exif_usercomment_splitter_sizes')
                if (
                    isinstance(saved_sizes, list)
                    and len(saved_sizes) == 2
                    and sum(saved_sizes) > 0
                ):
                    self._text_splitter.setSizes(saved_sizes)
        except Exception:
            pass
        self._sync_generate_btn_enabled()
        self._position_text_edit_overlays()
        super().showEvent(event)

    def reject(self):
        _stop_whisper_dictation()
        self._cancel_active_ai_caption()
        super().reject()

    def accept(self):
        _stop_whisper_dictation()
        self._cancel_active_ai_caption()
        super().accept()

    def closeEvent(self, event):
        """Save geometry when closed via X button (accept/reject use finished signal)."""
        _stop_whisper_dictation()
        self._cancel_active_ai_caption()
        self._save_geometry()
        super().closeEvent(event)

    def _make_thumb_click_handler(self):
        """Return a mousePressEvent handler that opens the image in browse mode."""
        def handler(event):
            if event.button() == Qt.MouseButton.LeftButton:
                parent = self.parent()
                if parent and hasattr(parent, 'load_file_with_directory_thumbnails'):
                    parent.load_file_with_directory_thumbnails(self.file_path)
        return handler

    def _on_reset(self):
        self._stop_active_caption(disconnect=False)
        self.text_edit.setPlainText(self.original_text)
        self._sync_generate_btn_enabled()

    def _has_caption_for_generate(self) -> bool:
        return bool(_initial_prompt_from_usercomment(self.text_edit.toPlainText()))

    def _sync_generate_btn_enabled(self) -> None:
        if self.generate_btn is None:
            return
        in_progress = self.ai_btn is not None and not self.ai_btn.isEnabled()
        self.generate_btn.setEnabled(
            self._has_caption_for_generate() and not in_progress
        )

    def _on_generate_image_from_caption(self):
        main_window = get_main_window() or self.parent()
        if main_window is None:
            return
        _open_imagegen_create_from_text_dialog(
            main_window, user_comment=self.text_edit.toPlainText()
        )

    def _on_open_captioning_settings(self):
        parent = self.parent()
        if parent and hasattr(parent, 'show_settings'):
            parent.show_settings(tab_index=7)

    def _on_read_aloud(self):
        text = self.text_edit.toPlainText().strip()
        text = truncate_usercomment_before_prompt(text)
        _speak_or_stop(text)

    def _on_copy_to_clipboard(self):
        mods = QApplication.keyboardModifiers()
        raw = bool(
            mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier)
        )
        text = self.text_edit.toPlainText()
        if not raw:
            text = truncate_usercomment_before_prompt(text)
            text = text.replace(";", ".")  # replace semicolons with periods for clipboard copy only
        from copy_feedback import copy_text_to_clipboard

        copy_text_to_clipboard(text, anchor=self.text_edit)

    def _on_dot_tick(self):
        if self._ai_caption_error_dialog_open:
            return
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)  # 1, 2, 3, or 4 periods
        self.text_edit.setPlainText(dots)

    def _abort_ai_caption_waiting_ui(self) -> None:
        """Stop the waiting animation and put back the text from before [AI] caption."""
        self._dot_timer.stop()
        self.text_edit.setPlainText(self._text_before_ai)

    def _restore_filename(self):
        self._dot_timer.stop()

    def _imagegen_controller(self):
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        mw = get_main_window() or self.parent()
        if mw is None:
            return None
        return get_imagegen_controller(mw)

    def _ai_caption_in_progress(self) -> bool:
        return self.ai_btn is not None and not self.ai_btn.isEnabled()

    def _disconnect_caption_signals(self) -> None:
        if not self._caption_connected:
            return
        controller = self._imagegen_controller()
        if controller is not None:
            for signal, slot in (
                (controller.caption_chunk, self._on_caption_chunk),
                (controller.caption_ready, self._on_caption_ready),
                (controller.caption_error, self._on_caption_error),
                (controller.caption_finished, self._on_caption_finished),
            ):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._caption_connected = False

    def _stop_active_caption(self, *, disconnect: bool) -> None:
        """Halt an in-flight AI caption and restore the Recaption button."""
        if not self._ai_caption_in_progress():
            return
        self._caption_cancelled_on_close = True
        self._dot_timer.stop()
        self._streaming_started = False
        controller = self._imagegen_controller()
        if controller is not None:
            controller.cancel_caption()
        if disconnect:
            self._disconnect_caption_signals()
        if self.ai_btn is not None:
            self.ai_btn.setEnabled(True)
            self.ai_btn.setText("Recaption")
            self._position_text_edit_overlays()
        self._sync_generate_btn_enabled()
        if not disconnect:
            self._caption_cancelled_on_close = False

    def _cancel_active_ai_caption(self) -> None:
        """Stop worker caption and reset app state when the dialog closes (Esc/Cancel/X)."""
        if self._caption_cancelled_on_close:
            return
        self._stop_active_caption(disconnect=True)

    def _on_ai_caption(self):
        if self.ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if controller.has_pending_work():
            from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog
            show_ai_caption_error_dialog(
                self,
                "Wait for the job queue to finish or cancel queued jobs "
                "before starting AI caption.",
                on_run_foreground=lambda: self._start_ai_caption(foreground=True),
            )
            return
        self._start_ai_caption(foreground=False)

    def _start_ai_caption(self, *, foreground: bool = False):
        if self.ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if foreground and controller.is_foreground_caption_running():
            from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog
            show_ai_caption_error_dialog(
                self,
                "A foreground AI caption is already running.",
            )
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("…")
        self._position_text_edit_overlays()
        self._sync_generate_btn_enabled()
        self._text_before_ai = self.text_edit.toPlainText()
        self._dot_phase = 0
        self._dot_timer.start()
        user_override = None
        if self._instructions_pane is not None:
            user_override = self._instructions_pane.effective_override_text()
        if not self._caption_connected:
            controller.caption_chunk.connect(self._on_caption_chunk)
            controller.caption_ready.connect(self._on_caption_ready)
            controller.caption_error.connect(self._on_caption_error)
            controller.caption_finished.connect(self._on_caption_finished)
            self._caption_connected = True
        self._streaming_started = False
        if foreground:
            started = controller.start_caption_foreground(
                self.file_path, user_override
            )
        else:
            started = controller.start_caption(self.file_path, user_override)
        if started:
            self._caption_cancelled_on_close = False
        else:
            self._abort_ai_caption_waiting_ui()
            self._on_caption_finished()
            self._show_ai_caption_error(
                "Could not start AI caption (another task may be running).",
            )

    def _scroll_text_edit_to_bottom(self, edit: QPlainTextEdit) -> None:
        bar = edit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_text_edit_streaming_content(self, edit: QPlainTextEdit, text: str) -> None:
        """Replace all text without resetting scroll to top (caption stream start / final)."""
        cursor = edit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        edit.setTextCursor(cursor)
        self._scroll_text_edit_to_bottom(edit)

    def _append_text_edit_streaming(self, edit: QPlainTextEdit, text: str) -> None:
        """Append streamed tokens at the end and keep the viewport pinned to the bottom."""
        if not text:
            return
        cursor = edit.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        cursor.endEditBlock()
        edit.setTextCursor(cursor)
        self._scroll_text_edit_to_bottom(edit)

    def _on_caption_chunk(self, chunk: str):
        if not chunk or self._caption_cancelled_on_close:
            return
        edit = self.text_edit
        edit.blockSignals(True)
        try:
            if not self._streaming_started:
                self._streaming_started = True
                self._dot_timer.stop()
                self._set_text_edit_streaming_content(edit, chunk)
            else:
                self._append_text_edit_streaming(edit, chunk)
        finally:
            edit.blockSignals(False)

    def _on_caption_ready(self, caption: str):
        self.text_edit.blockSignals(True)
        try:
            self._set_text_edit_streaming_content(self.text_edit, caption)
        finally:
            self.text_edit.blockSignals(False)
        self._sync_generate_btn_enabled()

    def _show_ai_caption_error(self, error_msg: str) -> None:
        if self._ai_caption_error_dialog_open:
            return
        self._abort_ai_caption_waiting_ui()
        self._ai_caption_error_dialog_open = True
        try:
            from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog

            show_ai_caption_error_dialog(self, error_msg)
        finally:
            self._ai_caption_error_dialog_open = False
            self._abort_ai_caption_waiting_ui()

    def _on_caption_error(self, error_msg: str):
        self._show_ai_caption_error(error_msg)

    def _on_caption_finished(self):
        if self._caption_cancelled_on_close:
            return
        self._dot_timer.stop()
        if self._ai_caption_error_dialog_open:
            self.text_edit.setPlainText(self._text_before_ai)
        self._restore_filename()
        if self.ai_btn is not None:
            self.ai_btn.setEnabled(True)
            self.ai_btn.setText("Recaption")
            self._position_text_edit_overlays()
        self._sync_generate_btn_enabled()

    def get_text(self) -> str:
        return self.text_edit.toPlainText()
