#!/usr/bin/env python3
"""
Command Line Help Dialog
Displays markdown-formatted text showing command line help output
"""

import os
import re
import subprocess
import sys

from markdown_dialog import MarkdownDialog


class CommandLineHelpDialog(MarkdownDialog):
    """Dialog showing markdown-formatted text with command line help output"""

    def __init__(self, parent=None):
        markdown_content = self._get_markdown_content()
        super().__init__("Command Line Help", markdown_content, parent)

    def _remove_ansi_sequences(self, text):
        """Remove ANSI escape sequences from text"""
        # ANSI escape sequence pattern: ESC [ ... m (and other control sequences)
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def _project_root(self):
        """Repository root (parent of browser_window/)."""
        return os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    def _get_command_line_help(self):
        """Run prowser.py -h and capture the output"""
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, '-h']
            cwd = os.path.dirname(os.path.abspath(sys.executable))
        else:
            project_root = self._project_root()
            prowser_py = os.path.join(project_root, 'prowser.py')
            venv_python = os.path.join(
                project_root, 'venv_image_browser', 'bin', 'python'
            )
            python_exe = (
                venv_python if os.path.exists(venv_python) else sys.executable
            )
            cmd = [python_exe, prowser_py, '-h']
            cwd = project_root

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                return f"Error running command: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out"
        except Exception as e:
            return f"Error running command: {str(e)}"

    def _get_markdown_content(self):
        """Get the markdown content for this dialog"""
        # Get command line help output
        help_text = self._get_command_line_help()
        
        # Remove ANSI sequences
        help_text = self._remove_ansi_sequences(help_text)
        
        # Format as markdown code block
        return f"""# Command Line Options

The following command line options are available:

```
{help_text}
```
"""


def main():
    """Test function to run the dialog independently"""
    import sys
    from PySide6.QtWidgets import QApplication

    # Create QApplication instance
    app = QApplication(sys.argv)

    # Create and show the dialog
    dialog = CommandLineHelpDialog()
    dialog.show()

    # Run the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
