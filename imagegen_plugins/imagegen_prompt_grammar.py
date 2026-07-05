#!/usr/bin/env python3
"""Grammar / spelling correction for image-gen prompt fields via LM Studio."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QPlainTextEdit, QPushButton

from imagegen_plugins.image_gen_form_layout import (
    image_gen_prompt_edit_set_plain_text,
    image_gen_prompt_stream_session_begin,
    image_gen_prompt_stream_session_end,
)
from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available
from utils import get_main_window


_GRAMMAR_SYSTEM_PROMPT = (
    "You are a grammarian. correct the grammer and English sentance structure "
    "and spelling for the user supplied input. Make no commentary or analysis.  "
    "Correct the grammar and spelling only."
)
_GRAMMAR_BUTTON_LABEL = "Grammar"
_GRAMMAR_CANCEL_LABEL = "Cancel"
_GRAMMAR_TOOLTIP = "Correct grammar and spelling using LM Studio"
_GRAMMAR_CANCEL_TOOLTIP = "Stop the in-progress grammar correction"


def _append_leading_phrase_to_system_prompt(base: str, phrase: str) -> str:
    phrase = phrase.strip()
    if not phrase:
        return base
    if phrase[-1] not in ".!?":
        phrase = f"{phrase}."
    return f"{base} {phrase}"


def _grammar_system_and_user_prompts(prompt: str) -> tuple[str, str]:
    """
    Split a leading 'phrase: rest' prefix into the system prompt and user prompt.

    Example: 'add two clowns: a scene of war.' ->
      system: '<base> add two clowns.'
      user: 'a scene of war.'
    """
    idx = prompt.find(":")
    if idx < 0:
        return _GRAMMAR_SYSTEM_PROMPT, prompt
    leading = prompt[:idx].strip()
    remainder = prompt[idx + 1 :].strip()
    if not leading or not remainder:
        return _GRAMMAR_SYSTEM_PROMPT, prompt
    system_prompt = _append_leading_phrase_to_system_prompt(
        _GRAMMAR_SYSTEM_PROMPT, leading
    )
    return system_prompt, remainder


def _show_ai_caption_error_dialog(*args, **kwargs):
    from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog

    return show_ai_caption_error_dialog(*args, **kwargs)


def cancel_dialog_prompt_grammar(owner: Any) -> None:
    """Stop in-progress grammar correction on a dialog or unified shell."""
    panels = getattr(owner, "_panels", None)
    if isinstance(panels, dict):
        for panel in panels.values():
            cancel_dialog_prompt_grammar(panel)
        return
    grammar = getattr(owner, "_prompt_grammar", None)
    if grammar is not None:
        grammar.cancel_running()


class ImageGenPromptGrammar:
    """Grammar button and streaming LM Studio correction for a prompt field."""

    def __init__(
        self,
        dialog: Any,
        *,
        get_prompt_text: Callable[[], str],
        set_prompt_text: Callable[[str], None],
        get_prompt_edit: Callable[[], Optional[QPlainTextEdit]],
    ) -> None:
        self._dialog = dialog
        self._get_prompt_text = get_prompt_text
        self._set_prompt_text = set_prompt_text
        self._get_prompt_edit = get_prompt_edit
        self._btn: Optional[QPushButton] = None
        self._connected = False
        self._streaming_started = False
        self._running = False
        self._user_cancelled = False
        self._prompt_before = ""
        self._dot_phase = 0
        self._dot_timer = QTimer(dialog)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._on_dot_tick)

    def create_button(self) -> Optional[QPushButton]:
        if not is_lmstudio_services_available():
            return None
        if self._btn is None:
            from imagegen_plugins.image_gen_dialog import (
                configure_image_gen_prompt_import_button,
            )

            self._btn = QPushButton(_GRAMMAR_BUTTON_LABEL)
            self._btn.setObjectName("imageGenPromptGrammarBtn")
            self._btn.setToolTip(_GRAMMAR_TOOLTIP)
            configure_image_gen_prompt_import_button(self._btn)
            self._btn.clicked.connect(self._on_primary_clicked)
        return self._btn

    def cancel_running(self) -> None:
        if not self._running:
            return
        self._on_cancel_clicked()

    def _imagegen_controller(self):
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        mw = get_main_window() or self._dialog.parent()
        if mw is None:
            return None
        return get_imagegen_controller(mw)

    def _on_primary_clicked(self) -> None:
        if self._running:
            self._on_cancel_clicked()
        else:
            self._on_grammar_clicked()

    def _set_button_idle(self) -> None:
        if self._btn is None:
            return
        self._btn.setEnabled(True)
        self._btn.setText(_GRAMMAR_BUTTON_LABEL)
        self._btn.setToolTip(_GRAMMAR_TOOLTIP)

    def _set_button_running(self) -> None:
        if self._btn is None:
            return
        self._btn.setEnabled(True)
        self._btn.setText(_GRAMMAR_CANCEL_LABEL)
        self._btn.setToolTip(_GRAMMAR_CANCEL_TOOLTIP)

    def _on_cancel_clicked(self) -> None:
        controller = self._imagegen_controller()
        if controller is None:
            return
        self._user_cancelled = True
        controller.cancel_flux_prompt_refine()

    def _on_grammar_clicked(self) -> None:
        if self._btn is None:
            return
        prompt = self._get_prompt_text()
        if not prompt.strip():
            _show_ai_caption_error_dialog(
                self._dialog,
                "Enter a prompt before running grammar correction.",
                window_title="Grammar",
                cancel_label="Cancel",
            )
            return

        controller = self._imagegen_controller()
        if controller is None:
            return
        busy_msg = self._flux_prompt_stream_busy_message(controller)
        if busy_msg:
            _show_ai_caption_error_dialog(
                self._dialog,
                busy_msg,
                window_title="Grammar",
                cancel_label="Cancel",
            )
            return

        self._prompt_before = prompt
        self._user_cancelled = False
        self._running = True
        self._begin_prompt_stream_scroll_session()
        self._set_button_running()
        self._dot_phase = 0
        self._dot_timer.start()

        if not self._connected:
            controller.flux_prompt_chunk.connect(self._on_chunk)
            controller.flux_prompt_ready.connect(self._on_ready)
            controller.flux_prompt_error.connect(self._on_error)
            controller.flux_prompt_finished.connect(self._on_finished)
            self._connected = True

        self._streaming_started = False
        system_prompt, user_prompt = _grammar_system_and_user_prompts(prompt)
        started = controller.start_flux_prompt_refine_foreground(
            system_prompt,
            user_prompt,
            image_paths=[],
        )
        if not started:
            self._on_finished()
            _show_ai_caption_error_dialog(
                self._dialog,
                "Could not start grammar correction (another task may be running).",
                window_title="Grammar",
                cancel_label="Cancel",
            )

    def _prompt_edit_widget(self) -> QPlainTextEdit | None:
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
        if not self._running:
            return
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)
        self._set_streaming_prompt_text(dots)

    def _stop_dots(self) -> None:
        self._dot_timer.stop()

    def _on_chunk(self, chunk: str) -> None:
        if not self._running:
            return
        if not self._streaming_started:
            self._streaming_started = True
            self._stop_dots()
            self._set_streaming_prompt_text(chunk)
        else:
            self._set_streaming_prompt_text(self._get_prompt_text() + chunk)

    def _on_ready(self, text: str) -> None:
        if not self._running:
            return
        self._set_streaming_prompt_text(text)

    def _on_error(self, error_msg: str) -> None:
        if not self._running:
            return
        self._end_prompt_stream_scroll_session()
        self._set_prompt_text(self._prompt_before)
        self._prompt_before = ""
        self._running = False
        self._user_cancelled = False
        self._set_button_idle()
        _show_ai_caption_error_dialog(
            self._dialog,
            error_msg,
            window_title="Grammar",
            cancel_label="Cancel",
        )

    def _on_finished(self) -> None:
        if not self._running and not self._user_cancelled:
            return
        self._stop_dots()
        self._end_prompt_stream_scroll_session()
        self._set_button_idle()
        self._running = False
        if self._user_cancelled:
            self._set_prompt_text(self._prompt_before)
            self._user_cancelled = False
        self._prompt_before = ""
        if getattr(self._dialog, "_panel_mode", False) and hasattr(
            self._dialog, "state_changed"
        ):
            self._dialog.state_changed.emit()

    def _flux_prompt_stream_busy_message(self, controller) -> Optional[str]:
        flux_ai = getattr(self._dialog, "_flux_prompt_ai", None)
        if flux_ai is not None and getattr(flux_ai, "_running", False):
            return (
                "AI prompt refinement is already running.\n\n"
                "Wait for it to finish or cancel it first."
            )
        if (
            controller._foreground_tasks.is_running()
            and controller._foreground_tasks.active_kind == "flux_prompt"
        ):
            return (
                "Another prompt text task is already running.\n\n"
                "Wait for it to finish or cancel it first."
            )
        if (
            not getattr(controller, "_job_ai_stage_active", False)
            and controller._tasks.is_running()
            and controller._tasks.active_kind == "flux_prompt"
        ):
            return (
                "AI prompt refinement is already running.\n\n"
                "Wait for it to finish or cancel it first."
            )
        if controller.is_foreground_caption_running():
            return (
                "Another foreground AI text task is already running.\n\n"
                "Wait for it to finish first."
            )
        return None


def ensure_prompt_grammar(owner: Any) -> Optional[ImageGenPromptGrammar]:
    get_prompt = getattr(owner, "get_prompt_text", None)
    set_prompt = getattr(owner, "set_prompt_text", None)
    get_edit = getattr(owner, "_prompt_edit_widget", None)
    if not callable(get_prompt) or not callable(set_prompt) or not callable(get_edit):
        return None
    grammar = getattr(owner, "_prompt_grammar", None)
    if grammar is None:
        grammar = ImageGenPromptGrammar(
            owner,
            get_prompt_text=get_prompt,
            set_prompt_text=set_prompt,
            get_prompt_edit=get_edit,
        )
        owner._prompt_grammar = grammar
    return grammar


def prompt_grammar_button(owner: Any) -> Optional[QPushButton]:
    grammar = ensure_prompt_grammar(owner)
    if grammar is None:
        return None
    return grammar.create_button()
