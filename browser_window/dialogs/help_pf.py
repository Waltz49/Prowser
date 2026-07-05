#!/usr/bin/env python3
"""
PF Keys Help Dialog
Shows function-key (PF1-PF12) assignments for Prowser / Image Browser.
"""

from __future__ import annotations

from markdown_dialog import MarkdownDialog

# QTextEdit ignores <style> in HTML; setDefaultStyleSheet supports this subset.
_PF_KEYS_STYLESHEET = """
h1 { margin-top: 0; }
table { width: 100%; }
tr {height: 4em;}
td.pf-key {
    font-size: 16pt;
    font-weight: bold;
    padding-right: 12px;
    text-align: right;
    vertical-align: top;
}
td.pf-desc {
    vertical-align: top; font-size: 14pt;
}
"""


def format_pf_keys_html() -> str:
    """HTML for PF (function) keys — edit this string directly."""
    return """
<h1>PF Keys (F1–F12)</h1>
<table>
<tbody>
<tr><td class="pf-key">F1</td><td class="pf-desc">Keyboard Shortcuts (busy, but comprehensive)</td></tr>
<tr><td class="pf-key">F2</td><td class="pf-desc">Quick Rename</td></tr>
<tr><td class="pf-key">F3</td><td class="pf-desc">Image History</td></tr>
<tr><td class="pf-key">F4</td><td class="pf-desc">Toggle Chrome (hide/show all sidebars and status bar)</td></tr>
<tr><td class="pf-key">F5</td><td class="pf-desc">Show reference graph for the active image (EXIF references saved by image generation; thumbnail or browse view)</td></tr>
<tr><td class="pf-key">F10</td><td class="pf-desc">Clear forward and backward history stacks (thumbnail view)</td></tr>
<tr><td class="pf-key">F12</td><td class="pf-desc">List View Toggle (experimental)</td></tr>
</tbody>
</table>
"""


class PFKeysHelpDialog(MarkdownDialog):
    """Dialog showing PF (function) key usage."""

    def __init__(self, parent=None):
        super().__init__("PF Keys", format_pf_keys_html(), parent)

    def load_content(self, content):
        self.content_area.document().setDefaultStyleSheet(_PF_KEYS_STYLESHEET)
        self.content_area.setHtml(content)


def main():
    """Test function to run the dialog independently."""
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = PFKeysHelpDialog()
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
