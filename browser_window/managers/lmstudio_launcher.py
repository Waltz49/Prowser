#!/usr/bin/env python3
"""
LM Studio macOS app launcher: verify installation and open the app.
"""

import os

_LMSTUDIO_DOWNLOAD_URL = "https://lmstudio.ai/"


def is_lmstudio_app_installed() -> bool:
    """Return True if LM Studio is installed as a macOS app."""
    paths = [
        "/Applications/LM Studio.app",
        os.path.expanduser("~/Applications/LM Studio.app"),
    ]
    for path in paths:
        if os.path.isdir(path):
            return True
    return False


def launch_lmstudio() -> bool:
    """
    Launch LM Studio if installed. Return True if launched, False if not installed or failed.
    """
    if not is_lmstudio_app_installed():
        return False
    try:
        from macos_process import open_application

        open_application("LM Studio", start_new_session=True)
        return True
    except Exception:
        return False


def open_lmstudio_or_show_install_help(parent) -> None:
    """
    Launch LM Studio when installed; otherwise explain how to install it
    and optionally open the download page.
    """
    if is_lmstudio_app_installed():
        if launch_lmstudio():
            return
        from utils import show_styled_warning

        show_styled_warning(
            parent,
            "Open LM Studio",
            "LM Studio appears to be installed but could not be launched.",
        )
        return

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox
    from utils import show_styled_question

    reply = show_styled_question(
        parent,
        "Install LM Studio",
        "LM Studio is not installed.\n\n"
        "Download it from lmstudio.ai, then drag LM Studio.app into "
        "Applications (or ~/Applications).\n\n"
        "With LM Studio running and a vision model loaded, Prowser can use it "
        "for AI EXIF captions and image-generation prompts.\n\n"
        "Open the download page in your browser?",
        default_no=False,
    )
    if reply == QMessageBox.StandardButton.Yes:
        QDesktopServices.openUrl(QUrl(_LMSTUDIO_DOWNLOAD_URL))


def show_ai_caption_error_dialog(
    parent,
    error_msg: str,
    *,
    window_title: str = "AI Caption Error",
    cancel_label: str = "Ok",
    on_run_foreground=None,
    on_run_now=None,
    run_foreground_tooltip: str = (
        "Run AI captioning concurrent with image generation. May be slow."
    ),
    run_now_tooltip: str | None = None,
    on_queue_job=None,
    queue_job_tooltip: str = (
        "Queue image generation with AI prompt refinement as the first stage."
    ),
) -> None:
    """
    Show an AI / LM Studio error dialog with dismiss, optional run-now, queue, LM Studio.

    When *on_run_foreground* or *on_run_now* is provided, adds a concurrent-run button.
    When *on_queue_job* is provided, adds a Queue Job button.
    """
    run_callback = on_run_now if on_run_now is not None else on_run_foreground
    run_tooltip = (
        run_now_tooltip
        if run_now_tooltip is not None
        else run_foreground_tooltip
    )
    run_label = "Run Now" if on_run_now is not None else "Run Foreground"
    lmstudio_label = "LM Studio" if on_queue_job is not None else "LM Studio..."
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QMessageBox, QStyle,
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocument
    from utils import get_button_style, get_dialog_shell_stylesheet

    dialog = QDialog(parent)
    dialog.setWindowTitle(window_title)
    dialog.setWindowFlags(
        Qt.Dialog | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
        | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint
    )
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(340)

    dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(18)
    main_layout.setContentsMargins(22, 18, 22, 18)

    icon_layout = QHBoxLayout()
    icon_label = QLabel()
    icon_label.setPixmap(
        dialog.style().standardIcon(QStyle.SP_MessageBoxWarning).pixmap(44, 44)
    )
    icon_layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_label = QLabel(error_msg)
    text_label.setWordWrap(True)
    text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    text_label.setMinimumWidth(240)
    font_metrics = text_label.fontMetrics()
    doc = QTextDocument()
    doc.setDefaultFont(text_label.font())
    doc.setTextWidth(240)
    doc.setPlainText(error_msg)
    ideal_height = doc.size().height()
    padding = max(14, font_metrics.descent() + font_metrics.leading() + 10)
    calculated_height = max(
        int(ideal_height) + padding,
        font_metrics.height() + padding,
    )
    text_label.setMinimumHeight(calculated_height)
    icon_layout.addWidget(text_label)
    main_layout.addLayout(icon_layout)

    button_bar = QHBoxLayout()
    button_bar.addStretch()
    button_style = get_button_style()

    def _dismiss():
        dialog.accept()

    ok_btn = QPushButton(cancel_label)
    ok_btn.setStyleSheet(button_style)
    ok_btn.setFocus()
    ok_btn.clicked.connect(_dismiss)
    button_bar.addWidget(ok_btn)

    if run_callback is not None:

        def _on_run():
            run_callback()
            _dismiss()

        run_btn = QPushButton(run_label)
        run_btn.setStyleSheet(button_style)
        run_btn.setToolTip(run_tooltip)
        run_btn.setDefault(True)
        run_btn.clicked.connect(_on_run)
        button_bar.addWidget(run_btn)

    if on_queue_job is not None:

        def _on_queue():
            on_queue_job()
            _dismiss()

        queue_btn = QPushButton("Queue Job")
        queue_btn.setStyleSheet(button_style)
        queue_btn.setToolTip(queue_job_tooltip)
        queue_btn.clicked.connect(_on_queue)
        button_bar.addWidget(queue_btn)

    def _on_lmstudio():
        if is_lmstudio_app_installed():
            launch_lmstudio()
        _dismiss()

    lmstudio_btn = QPushButton(lmstudio_label)
    lmstudio_btn.setStyleSheet(button_style)
    lmstudio_btn.clicked.connect(_on_lmstudio)
    button_bar.addWidget(lmstudio_btn)

    button_bar.addStretch()
    main_layout.addLayout(button_bar)

    dialog.exec()
