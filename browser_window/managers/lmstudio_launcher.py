#!/usr/bin/env python3
"""
LM Studio macOS app launcher: verify installation and open the app.
"""

import os
from typing import Callable

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
    from thumbnails.thumbnail_constants import is_vision_required_error
    from utils import show_scrollable_text_dialog, vision_required_icon_pixmap

    run_callback = on_run_now if on_run_now is not None else on_run_foreground
    run_tooltip = (
        run_now_tooltip
        if run_now_tooltip is not None
        else run_foreground_tooltip
    )
    run_label = "Run Now" if on_run_now is not None else "Run Foreground"
    lmstudio_label = "LM Studio" if on_queue_job is not None else "LM Studio..."

    icon = vision_required_icon_pixmap() if is_vision_required_error(error_msg) else None
    extra_actions: list[tuple[str, Callable[[], None], str | None, bool]] = []

    if run_callback is not None:
        extra_actions.append((run_label, run_callback, run_tooltip, True))

    if on_queue_job is not None:
        extra_actions.append(("Queue Job", on_queue_job, queue_job_tooltip, False))

    def _open_lmstudio() -> None:
        open_lmstudio_or_show_install_help(parent)

    extra_actions.append((lmstudio_label, _open_lmstudio, None, False))

    show_scrollable_text_dialog(
        parent,
        window_title,
        error_msg,
        ok_label=cancel_label,
        icon_pixmap=icon,
        use_standard_warning_icon=icon is None or icon.isNull(),
        extra_actions=extra_actions or None,
    )
