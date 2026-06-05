#!/usr/bin/env python3
"""
Dialog for editing EXIF UserComment on a single image file.
"""

import os
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QMessageBox, QWidget, QSplitter, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QEvent
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from thumbnail_constants import (
    DEFAULT_BACKGROUND_COLOR,
    DIALOG_TEXT_COLOR_HEX,
    DEFAULT_BORDER_COLOR,
    MULTISELECT_BORDER_COLOR_HEX,
    BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
    BUTTON_BG_PRESSED_HEX, BUTTON_FOCUS_TEXT_HEX, CURRENT_IMAGE_BORDER_COLOR_HEX,
    ACCENT_COLOR_HEX, TEXT_DISABLED_HEX, WIDGET_BG_DISABLED_HEX, VALIDATION_SUCCESS_COLOR_HEX,
)
from config import get_config
from exif_utils import truncate_usercomment_before_prompt
from theme_base import asset_path
from theme_service import get_active_theme
from lmstudio_caption import is_lmstudio_services_available
from speech_utils import speak_or_stop
from utils import create_gear_icon, get_main_window

try:
    from imagegen_plugins.image_gen_menu import (
        imagegen_plugins_available,
        open_imagegen_prompt_dialog,
    )
except ImportError:
    imagegen_plugins_available = lambda: False  # type: ignore[misc, assignment]
    open_imagegen_prompt_dialog = None  # type: ignore[misc, assignment]


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


def _create_ai_instructions_icon() -> QIcon:
    """Theme-aware 'AI' icon (40x40 asset) for the system-prompt toggle button."""
    th = get_active_theme()
    name = (
        "ai_icon_info_light.png"
        if getattr(th, "theme_id", "dark") == "light"
        else "ai_icon_info_dark.png"
    )
    return QIcon(asset_path(name))


class EditExifUserCommentDialog(QDialog):
    """Dialog for viewing and editing the EXIF UserComment of a single image."""

    def __init__(self, file_path: str, original_text: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.original_text = original_text
        self._caption_connected = False
        self._base_filename = os.path.basename(file_path)
        self._dot_phase = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._on_dot_tick)

        bg_color = _qtcolor_to_hex(DEFAULT_BACKGROUND_COLOR)
        text_color = DIALOG_TEXT_COLOR_HEX
        border_color = _qtcolor_to_hex(DEFAULT_BORDER_COLOR)

        self.setWindowTitle("Edit EXIF User Comment")
        self.setMinimumWidth(480)
        self.setMinimumHeight(320)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

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
            QPushButton#ai_btn {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {BUTTON_TEXT_DEFAULT_HEX};
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                min-width: 42px;
                padding: 6px 10px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton#ai_btn:hover {{
                background-color: {BUTTON_BG_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton#ai_btn:pressed {{
                background-color: {BUTTON_BG_PRESSED_HEX};
                color: {BUTTON_FOCUS_TEXT_HEX};
            }}
            QPushButton#ai_btn:disabled {{
                background-color: {WIDGET_BG_DISABLED_HEX};
                color: {TEXT_DISABLED_HEX};
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
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
        btn_stack.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        if is_lmstudio_services_available():
            self.instructions_btn = QPushButton()
            self.instructions_btn.setObjectName("instructions_btn")
            self._instructions_icon_normal = _create_ai_instructions_icon()
            self._instructions_icon_hover = _create_ai_instructions_icon()
            self.instructions_btn.setIcon(self._instructions_icon_normal)
            self.instructions_btn.setIconSize(QSize(16, 16))
            self.instructions_btn.setToolTip("Show/hide Instructions field (override AI user prompt)")
            self.instructions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.instructions_btn.clicked.connect(self._on_toggle_instructions)
            self.instructions_btn.installEventFilter(self)
            btn_stack.addWidget(self.instructions_btn, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.instructions_btn = None
        header_row.addLayout(btn_stack, 0)

        main_layout.addLayout(header_row)

        # Instructions + user comment (resizable when LMS available)
        self._instructions_visible = False
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(original_text)
        self.text_edit.setPlaceholderText("Enter user comment…")
        self.text_edit.setMinimumHeight(80)
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if is_lmstudio_services_available():
            instructions_container = QVBoxLayout()
            instructions_container.setSpacing(4)
            instructions_container.setContentsMargins(0, 0, 0, 0)
            self.instructions_label = QLabel("System Prompt")
            self.instructions_edit = QPlainTextEdit()
            self.instructions_edit.setPlaceholderText("Provide system instructions for the AI…")
       
            self.instructions_edit.setMinimumHeight(60)
            self.instructions_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            instructions_container.addWidget(self.instructions_label)
            instructions_container.addWidget(self.instructions_edit, 1)
            self._instructions_widget = QWidget()
            self._instructions_widget.setLayout(instructions_container)
            self._instructions_widget.setVisible(False)
            self._instructions_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self._text_splitter = QSplitter(Qt.Orientation.Vertical)
            self._text_splitter.setChildrenCollapsible(False)
            self._text_splitter.setHandleWidth(6)
            self._text_splitter.addWidget(self._instructions_widget)
            self._text_splitter.addWidget(self.text_edit)
            self._text_splitter.setStretchFactor(0, 0)
            self._text_splitter.setStretchFactor(1, 1)
            self._text_splitter.setSizes([100, 200])
            main_layout.addWidget(self._text_splitter, 1)
        else:
            self._instructions_widget = None
            self.instructions_edit = None
            self._text_splitter = None
            main_layout.addWidget(self.text_edit, 1)

        # Buttons row: Reset + [AI] on left, Cancel + Save on right
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Reset text to original value")
        reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(reset_btn)

        if imagegen_plugins_available():
            create_btn = QPushButton("Create")
            create_btn.setToolTip("Open image generation prompt (⌥/)")
            create_btn.clicked.connect(self._on_create_image_prompt)
            btn_row.addWidget(create_btn)

        if is_lmstudio_services_available():
            self.ai_btn = QPushButton("[AI]")
            self.ai_btn.setObjectName("ai_btn")
            self.ai_btn.setToolTip(
                "Generate an AI caption using LMStudio\n"
                "(requires a vision model loaded in LMStudio)"
            )
            self.ai_btn.clicked.connect(self._on_ai_caption)
            btn_row.addWidget(self.ai_btn)
        else:
            self.ai_btn = None

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

    def eventFilter(self, obj, event):
        """Swap icon buttons to hover/normal icons on enter/leave; thumbnail border on hover."""
        if event.type() == QEvent.Type.Enter:
            if obj is self.thumb_label:
                self.thumb_label.setStyleSheet(
                    f"border: 1px solid {BUTTON_BORDER_HOVER_HEX}; border-radius: 5px;"
                )
            elif obj is self.copy_btn:
                self.copy_btn.setIcon(self._copy_icon_hover)
            elif obj is self.settings_btn:
                self.settings_btn.setIcon(self._settings_icon_hover)
            elif self.instructions_btn is not None and obj is self.instructions_btn:
                self.instructions_btn.setIcon(self._instructions_icon_hover)
        elif event.type() == QEvent.Type.Leave:
            if obj is self.thumb_label:
                self.thumb_label.setStyleSheet(
                    f"border: 1px solid {MULTISELECT_BORDER_COLOR_HEX}; border-radius: 5px;"
                )
            elif obj is self.copy_btn:
                self.copy_btn.setIcon(self._copy_icon_normal)
            elif obj is self.settings_btn:
                self.settings_btn.setIcon(self._settings_icon_normal)
            elif self.instructions_btn is not None and obj is self.instructions_btn:
                self.instructions_btn.setIcon(self._instructions_icon_normal)
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
        if self.instructions_edit is not None:
            try:
                self._config.update_setting('edit_exif_usercomment_instructions', self.instructions_edit.toPlainText())
                self._config.update_setting('edit_exif_usercomment_instructions_visible', self._instructions_visible)
            except Exception:
                pass

    def showEvent(self, event):
        """Restore saved geometry and Instructions field when dialog is about to be shown."""
        try:
            settings = self._config.load_settings()
            geom_hex = settings.get('edit_exif_usercomment_dialog_geometry')
            if geom_hex:
                self.restoreGeometry(QByteArray(bytes.fromhex(geom_hex)))
            if self.instructions_edit is not None:
                self.instructions_edit.setPlainText(settings.get('edit_exif_usercomment_instructions', ''))
                self._instructions_visible = settings.get('edit_exif_usercomment_instructions_visible', False)
                self._instructions_widget.setVisible(self._instructions_visible)
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
        super().showEvent(event)

    def closeEvent(self, event):
        """Save geometry when closed via X button (accept/reject use finished signal)."""
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
        self.text_edit.setPlainText(self.original_text)

    def _on_create_image_prompt(self):
        main_window = self.parent()
        if main_window is None or open_imagegen_prompt_dialog is None:
            return
        open_imagegen_prompt_dialog(
            main_window, user_comment=self.text_edit.toPlainText()
        )

    def _on_toggle_instructions(self):
        if self.instructions_btn is None or self._instructions_widget is None:
            return
        self._instructions_visible = not self._instructions_visible
        self._instructions_widget.setVisible(self._instructions_visible)

    def _on_open_captioning_settings(self):
        parent = self.parent()
        if parent and hasattr(parent, 'show_settings'):
            parent.show_settings(tab_index=7)

    def _on_read_aloud(self):
        text = self.text_edit.toPlainText().strip()
        text = truncate_usercomment_before_prompt(text)
        speak_or_stop(text)

    def _on_copy_to_clipboard(self):
        mods = QApplication.keyboardModifiers()
        raw = bool(
            mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier)
        )
        text = self.text_edit.toPlainText()
        if not raw:
            text = truncate_usercomment_before_prompt(text)
            text = text.replace("\n", "\\n")  # escape newlines for clipboard
            text = text.replace(";", ".")  # replace semicolons with periods for clipboard copy only
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.copy_btn.setIcon(_create_check_icon(VALIDATION_SUCCESS_COLOR_HEX))
        self.copy_btn.setStyleSheet(f"QPushButton#copy_btn {{ border: 1px solid {VALIDATION_SUCCESS_COLOR_HEX}; }}")
        self.copy_btn.setToolTip("Copied!")
        QTimer.singleShot(1500, self._restore_copy_btn)

    def _restore_copy_btn(self):
        self.copy_btn.setIcon(
            self._copy_icon_hover if self.copy_btn.underMouse() else self._copy_icon_normal
        )
        self.copy_btn.setStyleSheet("")
        self.copy_btn.setToolTip("Copy user comment to clipboard.\nOption+click to copy raw text.")

    def _on_dot_tick(self):
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)  # 1, 2, 3, or 4 periods
        self.text_edit.setPlainText(dots)

    def _restore_filename(self):
        self._dot_timer.stop()

    def _imagegen_controller(self):
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        mw = get_main_window() or self.parent()
        if mw is None:
            return None
        return get_imagegen_controller(mw)

    def _on_ai_caption(self):
        if self.ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if controller.has_pending_work():
            from lmstudio_launcher import show_ai_caption_error_dialog
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
            from lmstudio_launcher import show_ai_caption_error_dialog
            show_ai_caption_error_dialog(
                self,
                "A foreground AI caption is already running.",
            )
            return
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("…")
        self._text_before_ai = self.text_edit.toPlainText()
        self._dot_phase = 0
        self._dot_timer.start()
        user_override = None
        if self._instructions_visible and self.instructions_edit is not None:
            user_override = self.instructions_edit.toPlainText().strip() or None
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
        if not started:
            self._on_caption_finished()
            from lmstudio_launcher import show_ai_caption_error_dialog
            show_ai_caption_error_dialog(
                self,
                "Could not start AI caption (another task may be running).",
            )

    def _on_caption_chunk(self, chunk: str):
        if not self._streaming_started:
            self._streaming_started = True
            self._dot_timer.stop()
            self.text_edit.setPlainText(chunk)
        else:
            self.text_edit.setPlainText(self.text_edit.toPlainText() + chunk)

    def _on_caption_ready(self, caption: str):
        self.text_edit.setPlainText(caption)

    def _on_caption_error(self, error_msg: str):
        self.text_edit.setPlainText(self._text_before_ai)
        from lmstudio_launcher import show_ai_caption_error_dialog
        show_ai_caption_error_dialog(self, error_msg)

    def _on_caption_finished(self):
        self._restore_filename()
        if self.ai_btn is not None:
            self.ai_btn.setEnabled(True)
            self.ai_btn.setText("[AI]")

    def get_text(self) -> str:
        return self.text_edit.toPlainText()
