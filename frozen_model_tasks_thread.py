#!/usr/bin/env python3
"""In-process model-tasks worker for frozen macOS (avoids QProcess space/focus steal)."""

from __future__ import annotations

import json
import queue
import sys
import threading

from PySide6.QtCore import QObject, Signal


class FrozenModelTasksWorkerBridge(QObject):
    """Qt signal bridge; worker runs on a plain Python thread (not QThread)."""

    json_line = Signal(str)
    finished = Signal()


class FrozenModelTasksWorkerThread:
    """Runs model_tasks_worker in threading.Thread — keeps MLX off Qt's QThread."""

    def __init__(self, parent=None):
        self._bridge = FrozenModelTasksWorkerBridge(parent)
        self.json_line = self._bridge.json_line
        self.finished = self._bridge.finished
        self._cmd_queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def send_command_json(self, line: str) -> None:
        self._cmd_queue.put(line)

    def request_stop(self) -> None:
        self._cmd_queue.put(None)

    def isRunning(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, msec: int) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=max(0, msec) / 1000.0)
        return not self.isRunning()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="model-tasks-worker",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            if sys.platform == "darwin":
                try:
                    import multiprocessing as mp

                    mp.set_start_method("fork", force=True)
                except (RuntimeError, ValueError):
                    pass
            from model_tasks_worker import run_worker_event_loop

            def _read_line() -> str | None:
                return self._cmd_queue.get()

            def _emit(msg: dict) -> None:
                self._bridge.json_line.emit(json.dumps(msg))

            run_worker_event_loop(_read_line, _emit)
        finally:
            self._bridge.finished.emit()
