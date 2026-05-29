#!/usr/bin/env python3
"""
Thin macOS subprocess port: `open`, `osascript`, and related helpers.

Import direction: UI and application services may call this module. Domain/pure logic should not
depend on it. Keeps platform shell usage in one place for tests and future native replacement.
"""

from __future__ import annotations

import subprocess

Completed = subprocess.CompletedProcess


def reveal_in_finder(path: str, *, timeout: float = 5) -> Completed:
    """Reveal ``path`` in Finder (``open -R``). Raises on failure."""
    return subprocess.run(
        ["open", "-R", path],
        check=True,
        timeout=timeout,
        capture_output=True,
        text=True,
    )


def open_document_with_app(app_name: str, file_path: str, *, timeout: int = 10) -> Completed:
    """Open ``file_path`` with application ``app_name`` (``open -a``)."""
    return subprocess.run(
        ["open", "-a", app_name, file_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def open_application(app_name: str, *, start_new_session: bool = False) -> subprocess.Popen:
    """Launch ``app_name`` without a document (``open -a``). Returns the Popen handle."""
    if start_new_session:
        return subprocess.Popen(["open", "-a", app_name], start_new_session=True)
    return subprocess.Popen(["open", "-a", app_name])


def run_osascript(script: str, *, timeout: int = 10) -> Completed:
    """Run AppleScript source with ``osascript -e``."""
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_terminal_script(shell_command: str, *, activate: bool = False) -> subprocess.Popen:
    """Open Terminal.app and run ``shell_command`` via AppleScript tell block."""
    escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    args = ["osascript"]
    if activate:
        args.extend(
            [
                "-e",
                'tell application "Terminal"',
                "-e",
                "activate",
                "-e",
                f'do script "{escaped}"',
                "-e",
                "end tell",
            ]
        )
    else:
        args.extend(["-e", f'tell application "Terminal" to do script "{escaped}"'])
    return subprocess.Popen(args)
