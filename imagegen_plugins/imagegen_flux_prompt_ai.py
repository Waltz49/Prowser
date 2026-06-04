#!/usr/bin/env python3
"""AI / Undo AI buttons for image-gen dialogs: refine prompts via LM Studio for FLUX."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from lmstudio_caption import is_lmstudio_services_available
from lmstudio_flux_prompt import flux_prompt_system_message
from utils import get_main_window


class ImageGenFluxPromptAi:
    """Attach AI controls beside the prompt field and stream results into it."""

    def __init__(
        self,
        dialog: QWidget,
        *,
        task_kind: str,
        get_prompt_text: Callable[[], str],
        set_prompt_text: Callable[[str], None],
    ):
        self._dialog = dialog
        self._task_kind = task_kind
        self._get_prompt_text = get_prompt_text
        self._set_prompt_text = set_prompt_text
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
        if not is_lmstudio_services_available():
            return
        self._ai_btn = QPushButton("AI")
        self._ai_btn.setObjectName("flux_prompt_ai_btn")
        self._ai_btn.setToolTip(
            "Refine this prompt for FLUX using LMStudio\n"
            "(requires a text model loaded in LM Studio)"
        )
        self._ai_btn.clicked.connect(self._on_ai_clicked)
        btn_col.addWidget(self._ai_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._undo_btn = QPushButton("Undo AI")
        self._undo_btn.setObjectName("flux_prompt_undo_ai_btn")
        self._undo_btn.setToolTip("Restore the prompt from before the last AI refinement")
        self._undo_btn.clicked.connect(self._on_undo_clicked)
        self._undo_btn.hide()
        btn_col.addWidget(self._undo_btn, 0, Qt.AlignmentFlag.AlignTop)

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
            from lmstudio_launcher import show_ai_caption_error_dialog

            show_ai_caption_error_dialog(
                self._dialog,
                "Wait for the job queue to finish or cancel queued jobs "
                "before refining a prompt with AI.",
                window_title="AI Prompt Error",
            )
            return

        self._prompt_before_ai = self._get_prompt_text()
        self._update_undo_visibility()

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

        system_prompt = flux_prompt_system_message(self._task_kind)
        user_prompt = self._prompt_before_ai.strip()
        self._streaming_started = False
        if not controller.start_flux_prompt_refine(system_prompt, user_prompt):
            self._on_finished()
            from lmstudio_launcher import show_ai_caption_error_dialog

            show_ai_caption_error_dialog(
                self._dialog,
                "Could not start AI prompt refinement (another task may be running).",
                window_title="AI Prompt Error",
            )

    def _on_dot_tick(self) -> None:
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)
        self._set_prompt_text(dots)

    def _stop_dots(self) -> None:
        self._dot_timer.stop()

    def _on_chunk(self, chunk: str) -> None:
        if not self._streaming_started:
            self._streaming_started = True
            self._stop_dots()
            self._set_prompt_text(chunk)
        else:
            self._set_prompt_text(self._get_prompt_text() + chunk)

    def _on_ready(self, text: str) -> None:
        self._set_prompt_text(text)

    def _on_error(self, error_msg: str) -> None:
        self._set_prompt_text(self._prompt_before_ai)
        self._prompt_before_ai = ""
        self._update_undo_visibility()
        from lmstudio_launcher import show_ai_caption_error_dialog

        show_ai_caption_error_dialog(
            self._dialog, error_msg, window_title="AI Prompt Error"
        )

    def _on_finished(self) -> None:
        self._stop_dots()
        if self._ai_btn is not None:
            self._ai_btn.setEnabled(True)
            self._ai_btn.setText("AI")
        self._update_undo_visibility()
