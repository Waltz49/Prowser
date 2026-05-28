"""
Redirect print() (stdout) to a single chmod-600 file per POSIX uid under the temp dir,
while also teeing to the real terminal. All app processes for that user share this path
so one `less +F` session can follow the combined output.
"""

import os
import sys
import tempfile
import threading

PRINT_LOG_FILE_PATH = None
_print_log_lock = threading.Lock()


class _StdoutToPrintLog:
    def __init__(self, path):
        self._path = path
        self._file = open(path, 'a', buffering=1)
        self._terminal = getattr(sys, '__stdout__', None) or sys.stdout
        self.encoding = getattr(self._terminal, 'encoding', 'utf-8')
        self.errors = getattr(self._terminal, 'errors', 'strict')

    def write(self, s):
        with _print_log_lock:
            self._file.write(s)
            self._terminal.write(s)

    def flush(self):
        with _print_log_lock:
            self._file.flush()
            self._terminal.flush()

    def fileno(self):
        return self._terminal.fileno()

    def isatty(self):
        return self._terminal.isatty()


def session_print_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), f'image_browser_print_{os.getuid()}.log')


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
