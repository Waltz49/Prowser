#!/usr/bin/env python3
"""Short chat usage tips dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from utils import get_button_style, get_dialog_shell_stylesheet

CHAT_TIPS_DIALOG_MIN_WIDTH = 680

_CHAT_TIPS_HTML = """
<h2>Chat tips</h2>
<ul style="margin-top: 0; margin-bottom: 0; padding-left: 1.2em; list-style-type: none;">
  <li style="margin-bottom: 1em; list-style-type: none;">
    <b>Drag and drop</b> &mdash; 
    <ul style="margin-top: 0; margin-bottom: 0; padding-left: 1.2em; list-style-type: none;">
      <li style="margin-bottom: 1em; list-style-type: none;">
        Drop image files onto the prompt or onto a message.
      </li>
    </ul>
  </li>
  <li style="margin-bottom: 1em; list-style-type: none;">
    <b>Triggers</b>
    <ul style="margin-top: 0; margin-bottom: 0; padding-left: 1.2em; list-style-type: none;">
      <li style="margin-bottom: 1em; list-style-type: none;">
        <b>/image</b> trigger &mdash; 
        Include <code>/image</code> (or <code>/im</code>) in your message to automatically generate images.<br>
        Uses the values set in <b>Image &rarr; Create</b> or <b>Edit</b>, so set them up first.<br>
        When the reply finishes, generation runs automatically.<br>
        (Uses the <b>Edit</b> dialog if images are attached, <b>Create</b> dialog if not.)<br>
        The <code>/image</code> token stays in chat history but is removed from the text sent to the model.
      </li>
      <li style="margin-bottom: 1em; list-style-type: none;">
        <b>{}</b> trigger &mdash;<br>
        Include <code>{}</code> in your message to attach the current browse/thumbnail selection (up to 4 images). This replaces any images already on the message.
      </li>
    </ul>
  </li>
  <li style="margin-bottom: 1em; line-height: 1; list-style-type: none;">
    <b>Editing</b>
    <ul style="margin-top: 0; margin-bottom: 0; padding-left: 1.2em; list-style-type: none;">
      <li style="margin: 0; list-style-type: none;">
        Double-clicking the text is a shortcut for the edit button.
      </li>
      <li style="margin: 0; list-style-type: none;">
        Click images to open the current set of images in thumbnail view.
      </li>
    </ul>
  </li>
</ul>
""".strip()


def show_chat_tips_dialog(parent: QWidget | None) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Chat Tips")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(CHAT_TIPS_DIALOG_MIN_WIDTH)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    body = QLabel(_CHAT_TIPS_HTML)
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setOpenExternalLinks(False)
    layout.addWidget(body)

    button_row = QHBoxLayout()
    button_row.addStretch(1)
    ok_button = QPushButton("OK")
    ok_button.setDefault(True)
    ok_button.clicked.connect(dialog.accept)
    button_row.addWidget(ok_button)
    layout.addLayout(button_row)

    dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    ok_button.setFocus()
    dialog.exec()
