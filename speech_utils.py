#!/usr/bin/env python3
"""
Text-to-speech utilities for macOS.

Uses PROWSER_SAY_EXIT when configured; otherwise the system ``say`` command.
"""

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable

_say_process = None
_say_lock = threading.Lock()
_speech_active = False
_stop_requested = False
_speech_listeners: list[Callable[[bool], None]] = []
_speech_listener_lock = threading.Lock()
_SAY_EXIT_TIMEOUT_SEC = 300
_TERMINATE_GRACE_SEC = 0.4


def register_speech_state_listener(callback: Callable[[bool], None]) -> None:
    with _speech_listener_lock:
        if callback not in _speech_listeners:
            _speech_listeners.append(callback)


def unregister_speech_state_listener(callback: Callable[[bool], None]) -> None:
    with _speech_listener_lock:
        try:
            _speech_listeners.remove(callback)
        except ValueError:
            pass


def _notify_speech_listeners(speaking: bool) -> None:
    with _speech_listener_lock:
        listeners = list(_speech_listeners)
    for callback in listeners:
        try:
            callback(speaking)
        except Exception:
            pass


def is_speaking() -> bool:
    """Return True if speech is currently running."""
    with _say_lock:
        return _speech_active


def _popen_kwargs() -> dict:
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    return kwargs


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=_TERMINATE_GRACE_SEC)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except Exception:
                pass


def stop_speech() -> None:
    """Stop the currently running speech. Safe to call from any thread."""
    global _say_process, _speech_active, _stop_requested
    with _say_lock:
        was_active = _speech_active
        _stop_requested = True
        _speech_active = False
        proc = _say_process
        _say_process = None
    if proc is not None:
        _terminate_process_tree(proc)
    if was_active:
        _notify_speech_listeners(False)


def _speak_argv(text: str) -> list[str] | None:
    from speech_exit import resolve_say_exit_command, say_exit_argv

    if resolve_say_exit_command():
        argv = say_exit_argv(text)
        return argv or None
    raw = os.environ.get("PROWSER_SAY_EXIT", "").strip()
    if raw:
        print(
            f"DEBUG speech_utils: PROWSER_SAY_EXIT not usable ({raw!r}); "
            "falling back to macOS say",
            file=sys.stderr,
        )
    if sys.platform != "darwin":
        return None
    return ["say", "-f", "-"]


def _run_speech_process(argv: list[str], text: str) -> None:
    global _say_process, _speech_active, _stop_requested
    proc = None
    notified_start = False
    try:
        with _say_lock:
            if _stop_requested:
                return
        if argv[:1] == ["say"]:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                **_popen_kwargs(),
            )
        else:
            proc = subprocess.Popen(argv, **_popen_kwargs())
        with _say_lock:
            if _stop_requested:
                _terminate_process_tree(proc)
                return
            _say_process = proc
        _notify_speech_listeners(True)
        notified_start = True
        if argv[:1] == ["say"]:
            proc.communicate(input=text.encode("utf-8"), timeout=_SAY_EXIT_TIMEOUT_SEC)
        else:
            proc.wait(timeout=_SAY_EXIT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        if proc:
            _terminate_process_tree(proc)
    except Exception as e:
        print(f"DEBUG speech_utils: speak_text failed: {e}")
    finally:
        notify_stop = False
        with _say_lock:
            _speech_active = False
            _stop_requested = False
            if _say_process is proc:
                _say_process = None
                notify_stop = notified_start
        if notify_stop:
            _notify_speech_listeners(False)


def speak_text(text: str) -> bool:
    """
    Speak text via PROWSER_SAY_EXIT or macOS ``say``.
    Runs in a background thread to avoid blocking UI.
    Returns True if speak was started successfully, False otherwise.
    """
    global _speech_active, _stop_requested
    if not text or not text.strip():
        return False
    text = text.strip()
    argv = _speak_argv(text)
    if not argv:
        return False

    with _say_lock:
        if _speech_active:
            return False
        _speech_active = True
        _stop_requested = False

    def _run_say():
        _run_speech_process(argv, text)

    try:
        thread = threading.Thread(target=_run_say, daemon=True)
        thread.start()
        return True
    except Exception:
        with _say_lock:
            _speech_active = False
        return False


def speak_or_stop(text: str) -> bool:
    """
    If speech is running, stop it. Otherwise start speaking text.
    Both ear buttons use this so either can stop speech started by the other.
    Returns True if speech was started, False if stopped or no text.
    """
    try:
        from bundle_capabilities import audio_output_ui_enabled

        if not audio_output_ui_enabled():
            return False
    except ImportError:
        pass
    if is_speaking():
        stop_speech()
        return False
    if not text or not text.strip():
        return False
    return speak_text(text)
