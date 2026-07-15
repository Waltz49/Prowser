#!/usr/bin/env python3
"""LM Studio grammar correction for chat prompt edit dialogs."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

_CHAT_PROMPT_END_PUNCT = frozenset("?!.:")


def format_chat_prompt_text_after_grammar(text: str) -> str:
    """Ensure non-empty prompt text ends with ? ! . or : (append . if needed)."""
    core = text.rstrip()
    if not core:
        return text
    if core[-1] in _CHAT_PROMPT_END_PUNCT:
        return core
    return f"{core}."


def format_chat_prompt_text_for_save(text: str) -> str:
    """On save: terminal punctuation, then one trailing space."""
    core = text.rstrip()
    if not core:
        return text
    if core[-1] not in _CHAT_PROMPT_END_PUNCT:
        core = f"{core}."
    return f"{core} "


def apply_chat_prompt_save_format_to_widget(text_edit: QWidget) -> None:
    text_edit.setPlainText(format_chat_prompt_text_for_save(text_edit.toPlainText()))


def _attach_prompt_grammar_api(
    dialog: QDialog,
    text_edit: QWidget,
    *,
    apply_grammar_punctuation: bool = True,
) -> None:
    def get_prompt_text() -> str:
        return text_edit.toPlainText()

    def set_prompt_text(text: str) -> None:
        text_edit.setPlainText(text)

    def _prompt_edit_widget() -> Optional[QPlainTextEdit]:
        if isinstance(text_edit, QPlainTextEdit):
            return text_edit
        return None

    dialog.get_prompt_text = get_prompt_text  # type: ignore[attr-defined]
    dialog.set_prompt_text = set_prompt_text  # type: ignore[attr-defined]
    dialog._prompt_edit_widget = _prompt_edit_widget  # type: ignore[attr-defined]

    if apply_grammar_punctuation:
        def _post_grammar_finish() -> None:
            text = text_edit.toPlainText()
            fixed = format_chat_prompt_text_after_grammar(text)
            if fixed != text:
                text_edit.setPlainText(fixed)

        dialog._chat_prompt_grammar_post_finish = _post_grammar_finish  # type: ignore[attr-defined]


def _hook_chat_prompt_grammar_cleanup(dialog: QDialog) -> None:
    if getattr(dialog, "_chat_prompt_grammar_finished_hooked", False):
        return
    from imagegen_plugins.imagegen_prompt_grammar import cancel_dialog_prompt_grammar

    dialog._chat_prompt_grammar_finished_hooked = True
    dialog.finished.connect(lambda: cancel_dialog_prompt_grammar(dialog))


def add_chat_prompt_grammar_button(
    dialog: QDialog,
    text_edit: QWidget,
    layout: QHBoxLayout,
    *,
    apply_grammar_punctuation: bool = True,
) -> bool:
    """Add a Grammar button to layout when LM Studio services are available."""
    from imagegen_plugins.imagegen_prompt_grammar import prompt_grammar_button
    from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available

    if not is_lmstudio_services_available():
        return False
    _attach_prompt_grammar_api(
        dialog,
        text_edit,
        apply_grammar_punctuation=apply_grammar_punctuation,
    )
    btn = prompt_grammar_button(dialog)
    if btn is None:
        return False
    layout.addWidget(btn)
    _hook_chat_prompt_grammar_cleanup(dialog)
    return True


def add_chat_prompt_button_row(
    dialog: QDialog,
    text_edit: QWidget,
    layout: QVBoxLayout,
    trailing: QWidget,
    *,
    apply_grammar_punctuation: bool = True,
) -> None:
    """One footer row: Grammar left (when available), trailing buttons right."""
    row = QHBoxLayout()
    add_chat_prompt_grammar_button(
        dialog,
        text_edit,
        row,
        apply_grammar_punctuation=apply_grammar_punctuation,
    )
    row.addStretch(1)
    row.addWidget(trailing)
    layout.addLayout(row)
