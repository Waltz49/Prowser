#!/usr/bin/env python3
"""
Text-to-speech utilities for macOS. Uses the system 'say' command.
"""

import subprocess
import sys
import threading

_say_process = None
_say_lock = threading.Lock()


def is_speaking() -> bool:
    """Return True if speech is currently running."""
    with _say_lock:
        return _say_process is not None and _say_process.poll() is None


def stop_speech() -> None:
    """Stop the currently running speech. Safe to call from any thread."""
    global _say_process
    with _say_lock:
        if _say_process is not None:
            try:
                _say_process.terminate()
            except Exception:
                pass
            _say_process = None


def speak_text(text: str) -> bool:
    """
    Speak text using macOS 'say' command. Runs in a background thread to avoid blocking UI.
    Returns True if speak was started successfully, False otherwise.
    """
    if not text or not text.strip():
        return False
    text = text.strip()

    def _run_say():
        global _say_process
        proc = None
        try:
            proc = subprocess.Popen(
                ['say', '-f', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with _say_lock:
                _say_process = proc
            proc.communicate(input=text.encode('utf-8'), timeout=300)
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
        except Exception as e:
            print(f"DEBUG speech_utils: speak_text failed: {e}")
        finally:
            with _say_lock:
                if _say_process is proc:
                    _say_process = None

    if sys.platform != 'darwin':
        return False
    try:
        thread = threading.Thread(target=_run_say, daemon=True)
        thread.start()
        return True
    except Exception:
        return False


def speak_or_stop(text: str) -> bool:
    """
    If speech is running, stop it. Otherwise start speaking text.
    Both ear buttons use this so either can stop speech started by the other.
    Returns True if speech was started, False if stopped or no text.
    """
    if is_speaking():
        stop_speech()
        return False
    if not text or not text.strip():
        return False
    return speak_text(text)
