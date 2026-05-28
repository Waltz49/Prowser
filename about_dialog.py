#!/usr/bin/env python
"""
About Dialog for Image Browser
Shows application information including build date
"""

import os
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QApplication, QTextBrowser,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from theme_service import get_active_theme

# Add a constant to toggle JIT info visibility
SHOW_JIT_INFO = False

# Credits shown in the HTML popup (libraries + model sources; links open in the system browser).
_CREDITS_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
body { font-family:  "Helvetica Neue", "Helvetica", "Arial", sans-serif; font-size: 13px; line-height: 1.45; }
h2 { font-size: 15px; margin: 1em 0 0.4em 0; }
h3 { font-size: 13px; margin: 1em 0 0.35em 0; }
ul { margin: 0.2em 0 0.6em 1.2em; padding: 0; }
li { margin: 0.2em 0; }
p { margin: 0.4em 0; }
a { color: __LINK_COLOR__; text-decoration: none; }
.note { color: __NOTE_COLOR__; font-size: 12px; font-style: italic;white-space: nowrap;margin-left:4em;}
</style>
</head>
<body>
<h2>Author</h2>
<p>Doug Nadel, and a myriad of AI zombies who wrote some code in exchange for brains.<br>
<span style="font-size: 10px; color: __SUBNOTE_COLOR__;">I've said too much.</span><br>
Contact: <a href="mailto:sillysotsoftware@yahoo.com">sillysotsoftware@yahoo.com</a>
<br>Github:  <a href="https://github.com/dnadel">GitHub: dnadel</a> (not populated yet)
</p>
<h3>License</h3>
<p>Business Source License 1.1 (BSL 1.1)</p>

<h3>Credits</h3>
<p>Prowser is distributed under the Business Source License 1.1 (source-available; converts to MIT on the Change Date). See the License section for details.</p>
<p>All intellectual property included in this work is owned by the original authors and contributors. If any work remains uncredited, it is an ommission due to error.</p>


<h2>Libraries &amp; frameworks</h2>
<ul>
<li><b>PySide6</b> (Qt for Python) — <a href="https://www.qt.io/qt-for-python">qt.io/qt-for-python</a></li>
<li><b>Pillow</b> (PIL) — <a href="https://python-pillow.org/">python-pillow.org</a></li>
<li><b>pillow-heif</b> (HEIF/HEIC) — <a href="https://github.com/bigcat88/pillow_heif">GitHub: bigcat88/pillow_heif</a></li>
<li><b>NumPy</b> — <a href="https://numpy.org/">numpy.org</a></li>
<li><b>piexif</b> — <a href="https://github.com/hMatoba/Piexif">GitHub: hMatoba/Piexif</a></li>
<li><b>PyTorch</b> &amp; <b>torchvision</b> (CNN similarity, pretrained ResNet weights) — <a href="https://pytorch.org/">pytorch.org</a></li>
<li><b>Hugging Face Transformers</b> (CLIP text/image models) — <a href="https://github.com/huggingface/transformers">GitHub: huggingface/transformers</a></li>
<li><b>face_recognition</b> — <a href="https://github.com/ageitgey/face_recognition">GitHub: ageitgey/face_recognition</a>
  (uses <b>dlib</b> — <a href="http://dlib.net/">dlib.net</a>)</li>
<li>Pretrained dlib shape predictor / face recognition models bundled via the
  <b>face_recognition_models</b> package — <a href="https://github.com/ageitgey/face_recognition_models">GitHub: ageitgey/face_recognition_models</a></li>
</ul>

<h2>Models (may download on first use)</h2>
<p class="note">CLIP weights are fetched via Hugging Face Hub (cache: typically <code>~/.cache/huggingface</code>).<br>
ResNet ImageNet checkpoints are typically cached under <code>~/.cache/torch</code>.</p>

<h3>Hugging Face — CLIP (settings may use either)</h3>
<ul>
<li><a href="https://huggingface.co/openai/clip-vit-base-patch32">openai/clip-vit-base-patch32</a> (default)</li>
<li><a href="https://huggingface.co/openai/clip-vit-large-patch14">openai/clip-vit-large-patch14</a></li>
</ul>

<h3>Face recognition (dlib / face_recognition)</h3>
<p>Detector and 128-D embedding weights are provided by the
<a href="https://github.com/ageitgey/face_recognition_models">face_recognition_models</a> distribution
(not hosted on Hugging Face). Credit: Davis King (dlib) and Adam Geitgey (face_recognition ecosystem).</p>

</body>
</html>
"""


# Business Source License 1.1 — full text for the License popup (Parameters as a table).
_BUSL_LICENSE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
body { font-family: "Helvetica Neue", "Helvetica", "Arial", sans-serif; font-size: 13px; line-height: 1.45; }
h1 { font-size: 16px; margin: 0 0 0.5em 0; }
h2 { font-size: 14px; margin: 1em 0 0.35em 0; }
p { margin: 0.4em 0; }
.header { color: __NOTE_COLOR__; font-size: 12px; }
table.params { width: 100%; border-collapse: collapse; margin: 0.4em 0 0.8em 0; }
table.params th, table.params td {
  border: 1px solid __BORDER_COLOR__;
  padding: 6px 8px;
  vertical-align: top;
  text-align: left;
}
table.params th { background-color: __TABLE_HEADER_BG__; font-weight: bold; }
table.params td.param { width: 28%; font-weight: bold; white-space: nowrap; }
.terms p { margin: 0.65em 0; }
</style>
</head>
<body>
<h1>Business Source License 1.1</h1>
<p class="header">License text copyright &copy; 2026 Doug Nadel, All Rights Reserved.<br>
&quot;Business Source License&quot; is a trademark of MariaDB plc.</p>

<h2>Parameters</h2>
<table class="params">
<thead>
<tr><th>Parameter</th><th>Value</th></tr>
</thead>
<tbody>
<tr><td class="param">Licensor</td><td>Doug Nadel</td></tr>
<tr><td class="param">Licensed Work</td><td>Prowser (Image Browser)<br>
The Licensed Work is &copy; 2026 Doug Nadel</td></tr>
<tr><td class="param">Additional Use Grant</td><td>You may make production use of the Licensed Work for personal,
non-commercial purposes, and for use within your organization
(including affiliates under common control).</td></tr>
<tr><td class="param">Change Date</td><td>Four years from the first public distribution of a specific
version of the Licensed Work under this License.</td></tr>
<tr><td class="param">Change License</td><td>MIT</td></tr>
</tbody>
</table>

<h2>Notice</h2>
<p>Business Source License 1.1</p>

<h2>Terms</h2>
<div class="terms">
<p>The Licensor hereby grants you the right to copy, modify, create derivative
works, redistribute, and make non-production use of the Licensed Work. The
Licensor may make an Additional Use Grant, above, permitting limited
production use.</p>
<p>Effective on the Change Date, or the fourth anniversary of the first publicly
available distribution of a specific version of the Licensed Work under this
License, whichever comes first, the Licensor hereby grants you rights under
the terms of the Change License, and the rights granted in the paragraph
above terminate.</p>
<p>If your use of the Licensed Work does not comply with the requirements
currently in effect as described in this License, you must purchase a
commercial license from the Licensor, its affiliated entities, or authorized
resellers, or you must refrain from using the Licensed Work.</p>
<p>All copies of the original and modified Licensed Work, and derivative works
of the Licensed Work, are subject to this License. This License applies
separately for each version of the Licensed Work and the Change Date may vary
for each version of the Licensed Work released by Licensor.</p>
<p>You must conspicuously display this License on each original or modified copy
of the Licensed Work. If you receive the Licensed Work in original or
modified form from a third party, the terms and conditions set forth in this
License apply to your use of that work.</p>
<p>Any use of the Licensed Work in violation of this License will automatically
terminate your rights under this License for the current and all other
versions of the Licensed Work.</p>
<p>This License does not grant you any right in any trademark or logo of
Licensor or its affiliates (provided that you may use a trademark or logo of
Licensor as expressly required by this License).</p>
<p>TO THE EXTENT PERMITTED BY APPLICABLE LAW, THE LICENSED WORK IS PROVIDED ON
AN &quot;AS IS&quot; BASIS. LICENSOR HEREBY DISCLAIMS ALL WARRANTIES AND CONDITIONS,
EXPRESS OR IMPLIED, INCLUDING (WITHOUT LIMITATION) WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND
TITLE.</p>
</div>
</body>
</html>
"""


def _themed_credits_html() -> str:
    th = get_active_theme()
    return (
        _CREDITS_HTML
        .replace("__LINK_COLOR__", th.accent_color_hex)
        .replace("__NOTE_COLOR__", th.text_disabled_hex)
        .replace("__SUBNOTE_COLOR__", th.text_disabled_hex)
    )


def _themed_busl_license_html() -> str:
    th = get_active_theme()
    return (
        _BUSL_LICENSE_HTML
        .replace("__NOTE_COLOR__", th.text_disabled_hex)
        .replace("__BORDER_COLOR__", th.border_default_hex)
        .replace("__TABLE_HEADER_BG__", th.dialog_background_hex)
    )


def _show_credits_popup(parent=None):
    """Small modal dialog with read-only HTML and working external links."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Credits")
    dlg.setModal(True)
    dlg.setMinimumSize(640, 420)
    th = get_active_theme()
    dlg.setStyleSheet(f"QDialog {{ background-color: {th.dialog_background_hex}; color: {th.dialog_text_color_hex}; }}")
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(12, 12, 12, 12)

    browser = QTextBrowser()
    browser.setReadOnly(True)
    browser.setOpenExternalLinks(True)
    browser.setStyleSheet(
        f"QTextBrowser {{ background-color: {th.dialog_background_hex}; color: {th.dialog_text_color_hex}; border: 1px solid {th.border_default_hex}; }}"
    )
    browser.setHtml(_themed_credits_html())
    layout.addWidget(browser)

    row = QHBoxLayout()
    row.addStretch()
    close = QPushButton("Close")
    close.setDefault(True)
    close.clicked.connect(dlg.accept)
    row.addWidget(close)
    layout.addLayout(row)
    dlg.exec()


def _show_license_popup(parent=None):
    """Modal dialog showing the Business Source License (read-only HTML)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("License")
    dlg.setModal(True)
    dlg.setMinimumSize(640, 420)
    th = get_active_theme()
    dlg.setStyleSheet(f"QDialog {{ background-color: {th.dialog_background_hex}; color: {th.dialog_text_color_hex}; }}")
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(12, 12, 12, 12)

    browser = QTextBrowser()
    browser.setReadOnly(True)
    browser.setOpenExternalLinks(True)
    browser.setStyleSheet(
        f"QTextBrowser {{ background-color: {th.dialog_background_hex}; color: {th.dialog_text_color_hex}; border: 1px solid {th.border_default_hex}; }}"
    )
    browser.setHtml(_themed_busl_license_html())
    layout.addWidget(browser)

    row = QHBoxLayout()
    row.addStretch()
    close = QPushButton("Close")
    close.setDefault(True)
    close.clicked.connect(dlg.accept)
    row.addWidget(close)
    layout.addLayout(row)
    dlg.exec()


class AboutDialog(QDialog):
    """About dialog showing application information and build date"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Prowser")
        self.setModal(True)
        self.setMinimumSize(400, 200)
        
        self.setup_ui()
        self.load_build_info()
        
        # Auto-size the dialog to fit its content
        self.adjustSize()
    
    def setup_ui(self):
        """Setup the about dialog UI"""
        # Use the __version__ variable from the package's __init__.py
        try:
            from __init__ import __version__ as Version
        except ImportError:
            Version = "Unknown"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)  # Reduced margins
        layout.setSpacing(10)  # Reduced spacing
        
        # App Icon
        icon_label = QLabel()
        icon_path = os.path.join(os.path.dirname(__file__), "Prowser.icns")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            # Scale the icon to a reasonable size (64x64 pixels)
            scaled_pixmap = pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
            icon_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon_label)
        
        # Title
        title = QLabel("Prowser - Image Browser")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Version
        version_label = QLabel(f"Version: {Version}")
        version_label.setAlignment(Qt.AlignCenter)
        version_font = QFont()
        version_font.setPointSize(12)
        version_label.setFont(version_font)
        layout.addWidget(version_label)

        # Python version
        python_version_text = f"Python Version: {sys.version.split()[0]} ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})"
        python_version_label = QLabel(python_version_text)
        python_version_label.setAlignment(Qt.AlignCenter)
        python_version_label.setFont(version_font)
        layout.addWidget(python_version_label)


        # JIT-related information (conditionally show)
        if SHOW_JIT_INFO:
            # Show the Python executable/module location (like 'which python')
            # python_location = sys.executable if hasattr(sys, "executable") else "Unknown"
            # python_location_label = QLabel(f"Python Location: {python_location}")
            # python_location_label.setAlignment(Qt.AlignCenter)
            # python_location_label.setFont(version_font)
            # layout.addWidget(python_location_label)

            jit_info_layout = QVBoxLayout()
            jit_info_layout.setSpacing(2)  # Smaller spacing to keep labels close vertically

            # sys._jit module availability
            sys_jit_available = hasattr(sys, '_jit')
            sys_jit_text = f"sys._jit module: {'Available' if sys_jit_available else 'Not available'}"
            sys_jit_label = QLabel(sys_jit_text)
            sys_jit_label.setAlignment(Qt.AlignCenter)
            sys_jit_label.setFont(version_font)
            jit_info_layout.addWidget(sys_jit_label)

            # PYTHON_JIT environment variable
            python_jit_env = os.environ.get('PYTHON_JIT', 'Not set')
            python_jit_env_text = f"PYTHON_JIT env var: {python_jit_env}"
            python_jit_env_label = QLabel(python_jit_env_text)
            python_jit_env_label.setAlignment(Qt.AlignCenter)
            python_jit_env_label.setFont(version_font)
            jit_info_layout.addWidget(python_jit_env_label)

            # JIT availability
            jit_available = sys_jit_available and sys._jit.is_available()
            jit_available_text = f"JIT Available: {'Yes' if jit_available else 'No'}"
            jit_available_label = QLabel(jit_available_text)
            jit_available_label.setAlignment(Qt.AlignCenter)
            jit_available_label.setFont(version_font)
            jit_info_layout.addWidget(jit_available_label)

            # JIT enabled
            if jit_available:
                jit_enabled_text = f"JIT Enabled: {'Yes' if sys._jit.is_enabled() else 'No'}"
            else:
                jit_enabled_text = "JIT Enabled: N/A"
            jit_enabled_label = QLabel(jit_enabled_text)
            jit_enabled_label.setAlignment(Qt.AlignCenter)
            jit_enabled_label.setFont(version_font)
            jit_info_layout.addWidget(jit_enabled_label)

            # JIT active
            if jit_available:
                jit_active_text = f"JIT Active: {'Yes' if sys._jit.is_active() else 'No'}"
            else:
                jit_active_text = "JIT Active: N/A"
            jit_active_label = QLabel(jit_active_text)
            jit_active_label.setAlignment(Qt.AlignCenter)
            jit_active_label.setFont(version_font)
            jit_info_layout.addWidget(jit_active_label)

            # Add the whole block to the dialog's main layout, keeping the labels packed together
            layout.addLayout(jit_info_layout)

        # Build date
        self.build_date_label = QLabel("Build Date: Unknown")
        self.build_date_label.setAlignment(Qt.AlignCenter)
        self.build_date_label.setFont(version_font)
        layout.addWidget(self.build_date_label)
        
        # Description
        desc_label = QLabel("A native image browser for macOS")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Technology info
        tech_label = QLabel("Built with Python and PySide6")
        tech_label.setAlignment(Qt.AlignCenter)
        tech_label.setFont(version_font)
        layout.addWidget(tech_label)
                
        # Add stretch to push button to bottom
        layout.addStretch()
        
        # Credits + Close
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        license_button = QPushButton("License")
        license_button.clicked.connect(lambda: _show_license_popup(self))

        credits_button = QPushButton("Credits")
        credits_button.clicked.connect(lambda: _show_credits_popup(self))

        close_button = QPushButton("Close")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)

        button_layout.addWidget(license_button)
        button_layout.addWidget(credits_button)
        button_layout.addWidget(close_button)
        button_layout.addStretch()

        layout.addLayout(button_layout)
    
    def showEvent(self, event):
        """Override showEvent to ensure close button has focus when dialog is shown"""
        super().showEvent(event)
        # Find and focus the close button
        for widget in self.findChildren(QPushButton):
            if widget.text() == "Close":
                widget.setFocus()
                break
    
    def load_build_info(self):
        """Load build date information by finding the most recent .py file modification date"""
        build_date = "Unknown"
        try:
            # Find the most recent modification date among .py files in the codebase
            build_date = self._find_latest_py_file_date()
        except Exception:
            # Fallback: generate current date
            import time
            build_date = time.strftime('%Y-%m-%d %H:%M:%S')
        
        self.build_date_label.setText(f"Build Date: {build_date}")
    
    def _find_latest_py_file_date(self):
        """Find the most recent modification date among .py files in the codebase"""
        import time
        import glob
        
        # Get the directory containing this script (the codebase root)
        codebase_root = os.path.dirname(os.path.abspath(__file__))
        
        # Find all .py files recursively, excluding venv directories
        py_files = []
        for root, dirs, files in os.walk(codebase_root):
            # Skip venv directories
            dirs[:] = [d for d in dirs if d not in ['venv', 'venv_image_browser', 'venv_pyinstaller', '__pycache__', 'build', 'dist']]
            
            for file in files:
                if file.endswith('.py'):
                    py_files.append(os.path.join(root, file))
        
        if not py_files:
            # No .py files found, use current time
            return time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Find the most recent modification time
        latest_mtime = 0
        for py_file in py_files:
            try:
                mtime = os.path.getmtime(py_file)
                if mtime > latest_mtime:
                    latest_mtime = mtime
            except (OSError, IOError):
                # Skip files that can't be accessed
                continue
        
        if latest_mtime > 0:
            return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(latest_mtime))
        else:
            # Fallback if no valid files found
            return time.strftime('%Y-%m-%d %H:%M:%S')

def main():
    """Test function to run the about dialog independently"""
    import sys

    # Ensure package root is on path so `from __init__ import __version__` works when not launched via main.py
    _root = os.path.dirname(os.path.abspath(__file__))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    # Create QApplication instance
    app = QApplication(sys.argv)
    
    # Create and show the about dialog
    dialog = AboutDialog()
    dialog.show()
    
    # Run the application event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
