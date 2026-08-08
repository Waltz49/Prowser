"""
Redirect print() (stdout) to a single chmod-600 file per POSIX uid under the profile
logs directory, while also teeing to the real terminal. All app processes for that
user share this path so one `less +F` session can follow the combined output.
"""

import os
import re
import sys
import threading
import contextlib

PRINT_LOG_FILE_PATH = None
_print_log_lock = threading.Lock()

# Drop indented emoji chatter (e.g. mflux "   🔀 Fusing with existing LoRA at ...").
# Top-level status lines that start with an emoji (no leading whitespace) are kept.
_INDENTED_EMOJI_LINE = re.compile(
    r"^[ \t]+"
    r"(?:"
    r"[\U0001F300-\U0001FAFF]"
    r"|[\u2600-\u27BF]"
    r")"
    r"[\uFE0E\uFE0F]?"
)


def _suppress_print_log_line(line: str) -> bool:
    """True when a completed log line should be omitted from terminal and View log."""
    return bool(_INDENTED_EMOJI_LINE.match(line))


class _NullTerminal:
    def write(self, _s):
        pass

    def flush(self):
        pass

    def fileno(self):
        return -1

    def isatty(self):
        return False


@contextlib.contextmanager
def quiet_console_stdout():
    """Suppress tee to the terminal; View log file still receives output."""
    out = sys.stdout
    if not isinstance(out, _StdoutToPrintLog):
        yield
        return
    saved = out._terminal
    out._terminal = _NullTerminal()
    try:
        yield
    finally:
        out._terminal = saved


class _StdoutToPrintLog:
    def __init__(self, path):
        self._path = path
        self._file = open(path, 'a', buffering=1)
        self._terminal = getattr(sys, '__stdout__', None) or sys.stdout
        self.encoding = getattr(self._terminal, 'encoding', 'utf-8')
        self.errors = getattr(self._terminal, 'errors', 'strict')
        self._pending = ""

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        with _print_log_lock:
            self._pending += s
            while True:
                idx = self._pending.find("\n")
                if idx < 0:
                    break
                line = self._pending[: idx + 1]
                self._pending = self._pending[idx + 1 :]
                if _suppress_print_log_line(line):
                    continue
                self._file.write(line)
                self._terminal.write(line)

    def flush(self):
        with _print_log_lock:
            if self._pending and not _suppress_print_log_line(self._pending):
                self._file.write(self._pending)
                self._terminal.write(self._pending)
                self._pending = ""
            self._file.flush()
            self._terminal.flush()

    def fileno(self):
        return self._terminal.fileno()

    def isatty(self):
        return self._terminal.isatty()


def write_process_stdout_line(line: str) -> None:
    """Write one line to the process stdout pipe only (not the View log file).

    Used for worker JSON IPC when stdout is tee'd to the shared print log.
    """
    out = sys.stdout
    terminal = getattr(out, "_terminal", None)
    if terminal is not None:
        with _print_log_lock:
            terminal.write(line + "\n")
            terminal.flush()
        return
    with _print_log_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def write_print_log_file(text: str) -> None:
    """Write to the View log file only (Tools > Debug > View log), not the terminal."""
    line = text if text.endswith("\n") else text + "\n"
    out = sys.stdout
    if isinstance(out, _StdoutToPrintLog):
        with _print_log_lock:
            out._file.write(line)
            out._file.flush()
        return
    path = PRINT_LOG_FILE_PATH or session_print_log_path()
    with _print_log_lock:
        with open(path, "a", buffering=1) as log_file:
            log_file.write(line)
            log_file.flush()


def clear_print_log_file() -> None:
    """Truncate the shared print log file and reset any active stdout tee handle."""
    path = PRINT_LOG_FILE_PATH or session_print_log_path()
    with _print_log_lock:
        out = sys.stdout
        if isinstance(out, _StdoutToPrintLog) and out._path == path:
            try:
                out._file.close()
            except OSError:
                pass
            out._pending = ""
            open(path, "w").close()
            out._file = open(path, "a", buffering=1)
        else:
            open(path, "w").close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def session_print_log_path() -> str:
    try:
        from config import get_config

        logs_dir = get_config().logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        return str(logs_dir / f"image_browser_print_{os.getuid()}.log")
    except Exception:
        log_dir = os.path.join(os.path.expanduser("~"), ".prowser", "logs")
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"image_browser_print_{os.getuid()}.log")


def setup_stdout_print_log(truncate: bool = False) -> None:
    """Idempotent per process: attach stdout tee to the session log file.

    truncate: If True, replace the log with an empty file (use once at GUI startup only;
    background workers must use False so they do not wipe the main process output).
    """
    global PRINT_LOG_FILE_PATH
    path = session_print_log_path()
    PRINT_LOG_FILE_PATH = path
    if isinstance(sys.stdout, _StdoutToPrintLog) and getattr(sys.stdout, '_path', None) == path:
        return
    if truncate:
        open(path, 'w').close()
    elif not os.path.exists(path):
        open(path, 'w').close()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    sys.stdout = _StdoutToPrintLog(path)
