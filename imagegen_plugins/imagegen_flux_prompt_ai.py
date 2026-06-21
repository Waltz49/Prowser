#!/usr/bin/env python3
"""AI / Undo AI buttons for image-gen dialogs: refine prompts via LM Studio for FLUX."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_form_layout import (
    image_gen_prompt_edit_set_plain_text,
    image_gen_prompt_stream_session_begin,
    image_gen_prompt_stream_session_end,
)
from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available
from workers.model_tasks_worker import flux_prompt_system_message
from utils import get_main_window


def _show_ai_caption_error_dialog(*args, **kwargs):
    from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog

    return show_ai_caption_error_dialog(*args, **kwargs)


class ImageGenFluxPromptAi:
    """Attach AI controls beside the prompt field and stream results into it."""

    def __init__(
        self,
        dialog: QWidget,
        *,
        task_kind: str,
        get_prompt_text: Callable[[], str],
        set_prompt_text: Callable[[str], None],
        get_pass_image: Optional[Callable[[], bool]] = None,
        get_image_path: Optional[Callable[[], str]] = None,
        get_prompt_edit: Optional[Callable[[], Optional[QPlainTextEdit]]] = None,
    ):
        self._dialog = dialog
        self._task_kind = task_kind
        self._get_prompt_text = get_prompt_text
        self._set_prompt_text = set_prompt_text
        self._get_pass_image = get_pass_image
        self._get_image_path = get_image_path
        self._get_prompt_edit = get_prompt_edit
        self._ai_btn: Optional[QPushButton] = None
        self._undo_btn: Optional[QPushButton] = None
        self._connected = False
        self._streaming_started = False
        self._prompt_before_ai = ""
        self._dot_phase = 0
        self._dot_timer = QTimer(dialog)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._on_dot_tick)

    def add_button(self, btn_col: QVBoxLayout) -> None:
        for button in self.make_action_buttons():
            btn_col.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)

    def make_action_buttons(self) -> list[QPushButton]:
        if not is_lmstudio_services_available():
            return []
        self._ai_btn = QPushButton("AI")
        self._ai_btn.setObjectName("flux_prompt_ai_btn")
        self._ai_btn.setToolTip(
            "Refine this prompt for FLUX using LMStudio\n"
            "(requires a text model loaded in LM Studio)"
        )
        self._ai_btn.clicked.connect(self._on_ai_clicked)

        self._undo_btn = QPushButton("Undo AI")
        self._undo_btn.setObjectName("flux_prompt_undo_ai_btn")
        self._undo_btn.setToolTip(
            "Restore the prompt from before the last AI refinement"
        )
        self._undo_btn.clicked.connect(self._on_undo_clicked)
        self._update_undo_visibility()
        return [self._ai_btn, self._undo_btn]

    def _update_undo_visibility(self) -> None:
        if self._undo_btn is None:
            return
        self._undo_btn.setVisible(bool(self._prompt_before_ai))

    def _on_undo_clicked(self) -> None:
        if not self._prompt_before_ai:
            return
        self._set_prompt_text(self._prompt_before_ai)
        self._prompt_before_ai = ""
        self._update_undo_visibility()

    def _imagegen_controller(self):
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        mw = get_main_window() or self._dialog.parent()
        if mw is None:
            return None
        return get_imagegen_controller(mw)

    def _on_ai_clicked(self) -> None:
        if self._ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if controller.has_pending_work():
            _show_ai_caption_error_dialog(
                self._dialog,
                "Wait for the job queue to finish or cancel queued jobs "
                "before refining a prompt with AI.",
                window_title="AI Prompt Error",
                on_run_foreground=lambda: self._start_ai_refine(foreground=True),
                run_foreground_tooltip=(
                    "Run AI prompt refinement concurrent with image generation. "
                    "May be slow."
                ),
            )
            return
        self._start_ai_refine(foreground=False)

    def _start_ai_refine(self, *, foreground: bool = False) -> None:
        if self._ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if foreground and controller.is_foreground_caption_running():
            _show_ai_caption_error_dialog(
                self._dialog,
                "A foreground AI text task is already running.",
                window_title="AI Prompt Error",
            )
            return

        self._prompt_before_ai = self._get_prompt_text()
        self._update_undo_visibility()
        self._begin_prompt_stream_scroll_session()

        self._ai_btn.setEnabled(False)
        self._ai_btn.setText("…")
        self._dot_phase = 0
        self._dot_timer.start()

        if not self._connected:
            controller.flux_prompt_chunk.connect(self._on_chunk)
            controller.flux_prompt_ready.connect(self._on_ready)
            controller.flux_prompt_error.connect(self._on_error)
            controller.flux_prompt_finished.connect(self._on_finished)
            self._connected = True

        user_prompt = self._prompt_before_ai.strip()
        image_path = self._resolve_image_path_for_refine()
        system_prompt = flux_prompt_system_message(
            self._task_kind, with_image=bool(image_path)
        )
        self._streaming_started = False
        if foreground:
            started = controller.start_flux_prompt_refine_foreground(
                system_prompt, user_prompt, image_path=image_path
            )
        else:
            started = controller.start_flux_prompt_refine(
                system_prompt, user_prompt, image_path=image_path
            )
        if not started:
            self._on_finished()
            _show_ai_caption_error_dialog(
                self._dialog,
                "Could not start AI prompt refinement (another task may be running).",
                window_title="AI Prompt Error",
            )

    def _resolve_image_path_for_refine(self) -> str | None:
        if self._get_pass_image is None or not self._get_pass_image():
            return None
        if self._get_image_path is None:
            return None
        path = (self._get_image_path() or "").strip()
        if path and os.path.isfile(path):
            return path
        return None

    def _prompt_edit_widget(self) -> QPlainTextEdit | None:
        if self._get_prompt_edit is None:
            return None
        return self._get_prompt_edit()

    def _begin_prompt_stream_scroll_session(self) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_stream_session_begin(edit)

    def _end_prompt_stream_scroll_session(self) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_stream_session_end(edit)

    def _set_streaming_prompt_text(self, text: str) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_edit_set_plain_text(edit, text, streaming=True)
            return
        self._set_prompt_text(text)

    def _on_dot_tick(self) -> None:
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)
        self._set_streaming_prompt_text(dots)

    def _stop_dots(self) -> None:
        self._dot_timer.stop()

    def _on_chunk(self, chunk: str) -> None:
        if not self._streaming_started:
            self._streaming_started = True
            self._stop_dots()
            self._set_streaming_prompt_text(chunk)
        else:
            self._set_streaming_prompt_text(self._get_prompt_text() + chunk)

    def _on_ready(self, text: str) -> None:
        self._set_streaming_prompt_text(text)

    def _on_error(self, error_msg: str) -> None:
        self._end_prompt_stream_scroll_session()
        self._set_prompt_text(self._prompt_before_ai)
        self._prompt_before_ai = ""
        self._update_undo_visibility()
        _show_ai_caption_error_dialog(
            self._dialog, error_msg, window_title="AI Prompt Error"
        )

    def _on_finished(self) -> None:
        self._stop_dots()
        self._end_prompt_stream_scroll_session()
        if self._ai_btn is not None:
            self._ai_btn.setEnabled(True)
            self._ai_btn.setText("Prompt AI")
        self._update_undo_visibility()
